from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from anthropic import Anthropic
from pydantic import ValidationError

from rca_copilot.models import Hypothesis, IncidentState

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


def run_baseline(
    alert: dict,
    window_start: datetime,
    window_end: datetime,
    sources: SourceBundle,
    client: Anthropic,
) -> IncidentState:

    state = IncidentState(
        incident_id=uuid4().hex[:8], alert=alert, window_start=window_start, window_end=window_end
    )

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

    for _ in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=system_prompt,
            tools=ALL_TOOLS + [submit_hypothesis],
            messages=messages,
        )

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

        for block in response.content:
            if block.type != "tool_use":
                continue

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
                state=state,
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

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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
