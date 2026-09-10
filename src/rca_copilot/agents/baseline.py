import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from anthropic import AsyncAnthropic
from opentelemetry.trace import Status as SpanStatus
from opentelemetry.trace import StatusCode
from pydantic import ValidationError

from rca_copilot.models import Hypothesis, IncidentState
from rca_copilot.telemetry.metrics import record_agent_duration, record_tokens
from rca_copilot.telemetry.tracing import tracer

from .tools import ALL_TOOLS, SourceBundle, evidence_to_tool_result, execute_tool, submit_hypothesis

# =================================================================
# =======================Constants=================================
# =================================================================
SERVICES = [
    "frontend-proxy",
    "frontend",
    "cart",
    "checkout",
    "payment",
    "currency",
    "recommendation",
    "ad",
    "shipping",
    "quote",
    "email",
    "product-catalog",
    "valkey-cart",
    "astronomy-db",
]

MODEL = "claude-haiku-4-5-20251001"
MAX_TURNS = 15


async def run_baseline(
    alert: dict,
    window_start: datetime,
    window_end: datetime,
    sources: SourceBundle,
    client: AsyncAnthropic,
) -> IncidentState:
    state = IncidentState(
        incident_id=uuid4().hex[:8],
        alert=alert,
        window_start=window_start,
        window_end=window_end,
    )

    with tracer.start_as_current_span("incident.diagnose") as root:
        root.set_attribute("incident.id", state.incident_id)
        root.set_attribute("config", "baseline")
        root.set_attribute("model", MODEL)
        started = time.perf_counter()
        try:
            prompt_path = Path(__file__).parent / "prompts" / "baseline.md"

            system_prompt = prompt_path.read_text(encoding="utf-8").format(
                window_start=window_start.isoformat(),
                window_end=window_end.isoformat(),
                alert=alert,
                services=", ".join(SERVICES),
            )

            messages = [
                {
                    "role": "user",
                    "content": "Diagnose this incident.",
                }
            ]

            turns = 0
            input_tokens = 0
            output_tokens = 0
            cache_creation_tokens = 0
            cache_read_tokens = 0

            for turn in range(MAX_TURNS):
                with tracer.start_as_current_span("llm.turn") as turn_span:
                    turn_span.set_attribute("turn", turn + 1)

                    response = await client.messages.create(
                        model=MODEL,
                        max_tokens=4000,
                        system=[
                            {
                                "type": "text",
                                "text": system_prompt,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                        tools=ALL_TOOLS + [submit_hypothesis],
                        messages=messages,
                    )

                    turns += 1
                    input_tokens += response.usage.input_tokens
                    output_tokens += response.usage.output_tokens

                    turn_cache_creation = (
                        getattr(response.usage, "cache_creation_input_tokens", 0) or 0
                    )
                    turn_cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0

                    cache_creation_tokens += turn_cache_creation
                    cache_read_tokens += turn_cache_read

                    turn_span.set_attribute("stop_reason", response.stop_reason)
                    turn_span.set_attribute("input_tokens", response.usage.input_tokens)
                    turn_span.set_attribute("output_tokens", response.usage.output_tokens)
                    turn_span.set_attribute("cache_creation_tokens", turn_cache_creation)
                    turn_span.set_attribute("cache_read_tokens", turn_cache_read)

                    state.run_meta["turns"] = turns
                    state.run_meta["input_tokens"] = input_tokens
                    state.run_meta["output_tokens"] = output_tokens
                    state.run_meta["cache_creation_tokens"] = cache_creation_tokens
                    state.run_meta["cache_read_tokens"] = cache_read_tokens

                    messages.append(
                        {
                            "role": "assistant",
                            "content": response.content,
                        }
                    )

                    if response.stop_reason != "tool_use":
                        final_text = " ".join(b.text for b in response.content if b.type == "text")
                        state.run_meta["final_text"] = final_text
                        state.run_meta["stop_reason"] = response.stop_reason
                        break

                    tool_results = []

                    tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                    turn_span.set_attribute("tool_calls", len(tool_use_blocks))

                    for block in tool_use_blocks:
                        if block.name == "submit_hypothesis":
                            try:
                                hypothesis = Hypothesis(
                                    agent="baseline",
                                    cause=block.input["cause"],
                                    confidence=block.input["confidence"],
                                    evidence_ids=block.input["evidence_ids"],
                                )

                                state.hypotheses.append(hypothesis)
                                return state

                            except ValidationError as exc:
                                state.run_meta.setdefault("validation_errors", []).append(str(exc))
                                return state

                        evidence = execute_tool(
                            name=block.name,
                            arguments=block.input,
                            sources=sources,
                            window_start=window_start,
                            window_end=window_end,
                            agent="baseline",
                        )

                        state.evidence.append(evidence)

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": evidence_to_tool_result(evidence),
                            }
                        )

                    messages.append(
                        {
                            "role": "user",
                            "content": tool_results,
                        }
                    )

            return state

        finally:
            record_agent_duration("baseline", time.perf_counter() - started)
            root.set_attribute("turns", state.run_meta.get("turns", 0))
            root.set_attribute("input_tokens", state.run_meta.get("input_tokens", 0))
            root.set_attribute("output_tokens", state.run_meta.get("output_tokens", 0))
            root.set_attribute(
                "cache_creation_tokens",
                state.run_meta.get("cache_creation_tokens", 0),
            )
            root.set_attribute("cache_read_tokens", state.run_meta.get("cache_read_tokens", 0))
            root.set_attribute("evidence_count", len(state.evidence))
            root.set_attribute("hypothesis_submitted", len(state.hypotheses) > 0)

            record_tokens("baseline", "input", state.run_meta.get("input_tokens", 0))
            record_tokens("baseline", "output", state.run_meta.get("output_tokens", 0))

            if state.hypotheses:
                root.set_attribute("hypothesis.confidence", state.hypotheses[0].confidence)
            else:
                root.set_status(SpanStatus(StatusCode.ERROR, "no hypothesis submitted"))

            if state.run_meta.get("validation_errors"):
                root.set_attribute("validation_error", True)


if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    from rca_copilot.sources.changelog import SnapshotChangesSource
    from rca_copilot.sources.snapshot import (
        SnapshotLogsSource,
        SnapshotMetricsSource,
        SnapshotTracesSource,
    )

    load_dotenv()

    scenario = Path("scenarios/C4-astronomy-db-down")

    sources = SourceBundle(
        logs=SnapshotLogsSource(scenario),
        metrics=SnapshotMetricsSource(scenario),
        traces=SnapshotTracesSource(scenario),
        changelog=SnapshotChangesSource("scenarios/_changelog_master.json"),
    )

    client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    state = run_baseline(
        alert={"service": "cart", "message": "elevated error rate on cart"},
        window_start=datetime(2026, 9, 3, 7, 36, 34, tzinfo=UTC),
        window_end=datetime(2026, 9, 3, 7, 51, 34, tzinfo=UTC),
        sources=sources,
        client=client,
    )

    print(f"Evidence gathered: {len(state.evidence)}")
    for e in state.evidence:
        print(f"  {e.evidence_id}  {e.source}: {e.summary}")

    print()
    if state.hypotheses:
        h = state.hypotheses[0]
        print(f"Cause:      {h.cause}")
        print(f"Confidence: {h.confidence}")
        print(f"Cites:      {h.evidence_ids}")
    else:
        print("No hypothesis submitted")
        print(f"run_meta: {state.run_meta}")
