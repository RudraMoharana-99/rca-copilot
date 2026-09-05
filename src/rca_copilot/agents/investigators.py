from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from pydantic import ValidationError

from rca_copilot.models import Evidence, Hypothesis

from .tools import (
    SourceBundle,
    evidence_to_tool_result,
    execute_tool,
    find_traces,
    get_metrics,
    get_trace_detail,
    search_logs,
    submit_hypothesis,
)

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


def run_investigator(
    agent_name: str,
    prompt_file: str,
    tools: list[dict],
    alert: dict,
    window_start: datetime,
    window_end: datetime,
    sources: SourceBundle,
    client: Anthropic,
    max_turns: int = 15,
) -> tuple[list[Evidence], list[Hypothesis], dict]:

    evidence: list[Evidence] = []
    hypotheses: list[Hypothesis] = []

    run_meta = {
        "agent": agent_name,
        "turns": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }

    prompt_path = Path(__file__).parent / "prompts" / prompt_file

    system_prompt = prompt_path.read_text(encoding="utf-8").format(
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        alert=alert,
        services=", ".join(SERVICES),
    )

    messages = [
        {
            "role": "user",
            "content": "Investigate this incident.",
        }
    ]

    for _ in range(max_turns):
        run_meta["turns"] += 1

        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=system_prompt,
            tools=tools + [submit_hypothesis],
            messages=messages,
        )

        run_meta["input_tokens"] += response.usage.input_tokens
        run_meta["output_tokens"] += response.usage.output_tokens

        messages.append(
            {
                "role": "assistant",
                "content": response.content,
            }
        )

        if response.stop_reason != "tool_use":
            final_text = " ".join(b.text for b in response.content if b.type == "text")
            run_meta["final_text"] = final_text
            run_meta["stop_reason"] = response.stop_reason
            break

        tool_results = []

        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "submit_hypothesis":
                cited_evidence_ids = block.input["evidence_ids"]

                available_evidence_ids = {item.evidence_id for item in evidence}

                unknown_ids = [
                    evidence_id
                    for evidence_id in cited_evidence_ids
                    if evidence_id not in available_evidence_ids
                ]

                if unknown_ids:
                    message = "Hypothesis rejected. Unknown evidence IDs: " + ", ".join(unknown_ids)

                    run_meta.setdefault(
                        "validation_errors",
                        [],
                    ).append(message)

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": message,
                        }
                    )

                    continue

                try:
                    hypothesis = Hypothesis(
                        agent=agent_name,
                        cause=block.input["cause"],
                        confidence=block.input["confidence"],
                        evidence_ids=cited_evidence_ids,
                    )

                    hypotheses.append(hypothesis)

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Hypothesis recorded successfully.",
                        }
                    )

                except ValidationError as exc:
                    run_meta.setdefault(
                        "validation_errors",
                        [],
                    ).append(str(exc))

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Hypothesis rejected: {exc}",
                        }
                    )

                continue

            evidence_item = execute_tool(
                name=block.name,
                arguments=block.input,
                sources=sources,
                window_start=window_start,
                window_end=window_end,
                agent=agent_name,
            )

            evidence.append(evidence_item)

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": evidence_to_tool_result(evidence_item),
                }
            )

        if tool_results:
            messages.append(
                {
                    "role": "user",
                    "content": tool_results,
                }
            )
    return evidence, hypotheses, run_meta


def run_log_analyst(alert, window_start, window_end, sources, client):
    return run_investigator(
        agent_name="log_analyst",
        prompt_file="log_analyst.md",
        tools=[search_logs, find_traces, get_trace_detail],
        window_start=window_start,
        window_end=window_end,
        sources=sources,
        client=client,
        max_turns=15,
        alert=alert,
    )


def run_metrics_analyst(alert, window_start, window_end, sources, client):
    return run_investigator(
        agent_name="metrics_analyst",
        prompt_file="metrics_analyst.md",
        tools=[get_metrics],
        window_start=window_start,
        window_end=window_end,
        sources=sources,
        client=client,
        max_turns=15,
        alert=alert,
    )
