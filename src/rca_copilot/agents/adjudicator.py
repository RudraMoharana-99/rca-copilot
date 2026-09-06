from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from pydantic import ValidationError

from rca_copilot.agents.tools import (
    SourceBundle,
    evidence_to_tool_result,
    execute_tool,
    get_recent_changes,
    submit_verdict,
)
from rca_copilot.models import (
    Evidence,
    Hypothesis,
    RankedCause,
    Verdict,
)
import sys
import yaml

MODEL = "claude-haiku-4-5-20251001"


def format_investigator_report(
    agent_name: str,
    evidence: list[Evidence],
    hypotheses: list[Hypothesis],
) -> str:
    lines = [
        f"## Report from {agent_name}",
    ]

    sources = sorted({item.source for item in evidence})

    if sources:
        lines.append(f"Sources available: {', '.join(sources)}")
    else:
        lines.append("Sources available: none")

    lines.append("")
    lines.append("Evidence gathered:")

    if evidence:
        for item in evidence:
            lines.append(f"  {item.evidence_id}  {item.source:<10}  {item.summary}")
    else:
        lines.append("  None")

    lines.append("")
    lines.append("Hypotheses:")

    if hypotheses:
        for hypothesis in hypotheses:
            lines.append(f"  [{hypothesis.hypothesis_id}] confidence {hypothesis.confidence:.2f}")
            lines.append(f"  {hypothesis.cause}")
            lines.append(f"  Cites: {', '.join(hypothesis.evidence_ids)}")
    else:
        lines.append("  None")

    return "\n".join(lines)

def load_scenario(
    name: str,
) -> tuple[Path, dict, datetime, datetime]:
    scenario_dir = Path("scenarios") / name
    scenario_file = scenario_dir / "scenario.yaml"

    if not scenario_file.exists():
        raise FileNotFoundError(
            f"Scenario not found: {scenario_file}"
        )

    with scenario_file.open("r", encoding="utf-8") as file:
        scenario = yaml.safe_load(file)

    window_start = scenario["window"]["start"]
    

    window_end = scenario["window"]["end"]
    

    return (
        scenario_dir,
        scenario,
        window_start,
        window_end,
    )


def run_adjudicator(
    alert: dict,
    window_start: datetime,
    window_end: datetime,
    reports: list[str],
    investigator_evidence: list[Evidence],
    sources: SourceBundle,
    client: Anthropic,
    max_turns: int = 6,
) -> tuple[list[Evidence], Verdict | None, dict]:

    evidence: list[Evidence] = []

    run_meta = {
        "agent": "adjudicator",
        "turns": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    rejection_count = 0
    prompt_path = Path(__file__).parent / "prompts" / "adjudicator.md"

    system_prompt = prompt_path.read_text(encoding="utf-8").format(
        window_start=window_start,
        window_end=window_end,
        alert=alert,
    )

    investigator_report = "\n\n".join(reports)

    messages = [
        {
            "role": "user",
            "content": investigator_report,
        }
    ]

    for _ in range(max_turns):
        run_meta["turns"] += 1

        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=system_prompt,
            tools=[
                get_recent_changes,
                submit_verdict,
            ],
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

        tool_results = []

        if response.stop_reason != "tool_use":
            final_text = " ".join(b.text for b in response.content if b.type == "text")
            run_meta["final_text"] = final_text
            run_meta["stop_reason"] = response.stop_reason
            break

        tool_results = []

        for block in response.content:
            if block.type != "tool_use":
                continue

            if block.name == "submit_verdict":
                arguments = block.input

                valid_evidence_ids = {item.evidence_id for item in investigator_evidence}
                valid_evidence_ids.update(item.evidence_id for item in evidence)

                invalid_ids = []
                malformed = False

                for cause in arguments["ranked_causes"]:
                    if not isinstance(cause, dict):
                        malformed = True
                        break
                    for evidence_id in cause.get("evidence_ids", []):
                        if evidence_id not in valid_evidence_ids:
                            invalid_ids.append(evidence_id)

                if malformed:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": (
                                "Verdict rejected. Each item in "
                                "ranked_causes must be an object with "
                                "cause, confidence and evidence_ids "
                                "fields, not a plain string. Resubmit "
                                "using the correct structure."
                            ),
                        }
                    )
                    run_meta["malformed_verdict"] = True
                    rejection_count += 1
                    continue

                if invalid_ids:
                    run_meta["verdict_rejected"] = True
                    run_meta["invalid_evidence_ids"] = invalid_ids

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": (
                                "Verdict rejected. The following "
                                "evidence IDs do not exist: "
                                + ", ".join(invalid_ids)
                                + ". Submit the verdict again "
                                "using only valid evidence IDs."
                            ),
                        }
                    )
                    rejection_count += 1
                    continue

                try:
                    ranked_causes = [
                        RankedCause(
                            cause=item["cause"],
                            confidence=item["confidence"],
                            evidence_ids=item["evidence_ids"],
                        )
                        for item in arguments["ranked_causes"]
                    ]

                    verdict = Verdict(
                        ranked_causes=ranked_causes,
                        overall_confidence=arguments["overall_confidence"],
                        dissent=arguments.get("dissent"),
                        escalate=arguments.get("escalate", False),
                        escalation_reason=arguments.get("escalation_reason"),
                    )

                except (KeyError, ValidationError) as exc:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": (
                                f"Verdict rejected because it failed schema validation: {exc}"
                            ),
                        }
                    )
                    rejection_count += 1
                    continue

                run_meta["verdict_submitted"] = True

                return evidence, verdict, run_meta

            tool_evidence = execute_tool(
                name=block.name,
                arguments=block.input,
                sources=sources,
                window_start=window_start,
                window_end=window_end,
                agent="adjudicator",
            )

            evidence.append(tool_evidence)

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": evidence_to_tool_result(tool_evidence),
                }
            )

        if tool_results:
            messages.append(
                {
                    "role": "user",
                    "content": tool_results,
                }
            )
            if rejection_count > 0 and not run_meta.get("verdict_submitted"):
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your verdict was NOT recorded. It was rejected "
                            "for the reason given above. You must call "
                            "submit_verdict again with the corrected input. "
                            "Do not summarise your verdict in prose - only a "
                            "successful submit_verdict call counts."
                        ),
                    }
                )
                rejection_count = 0

    return evidence, None, run_meta


# if __name__ == "__main__":
#     import sys

#     if len(sys.argv) != 2:
#         raise SystemExit(
#             "Usage: uv run python -m "
#             "rca_copilot.agents.adjudicator <scenario>"
#         )

#     scenario_name = sys.argv[1]

#     (
#         scenario_dir,
#         scenario,
#         window_start,
#         window_end,
#     ) = load_scenario(scenario_name)

#     print(f"Scenario directory: {scenario_dir}")
#     print(f"Scenario ID: {scenario['id']}")
#     print(f"Scenario name: {scenario['name']}")
#     print(f"Window start: {window_start}")
#     print(f"Window end: {window_end}")

if __name__ == "__main__":
    import os
    import sys

    from dotenv import load_dotenv

    from rca_copilot.agents.investigators import (
        run_log_analyst,
        run_metrics_analyst,
    )
    from rca_copilot.sources.changelog import SnapshotChangesSource
    from rca_copilot.sources.snapshot import (
        SnapshotLogsSource,
        SnapshotMetricsSource,
        SnapshotTracesSource,
    )

    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: uv run python -m rca_copilot.agents.adjudicator <scenario>"
        )

    load_dotenv()

    scenario_name = sys.argv[1]

    (
        scenario_dir,
        scenario,
        window_start,
        window_end,
    ) = load_scenario(scenario_name)

    print(f"Scenario: {scenario['id']} - {scenario['name']}")
    print(f"Window: {window_start} to {window_end}\n")

    sources = SourceBundle(
        logs=SnapshotLogsSource(scenario_dir),
        metrics=SnapshotMetricsSource(scenario_dir),
        traces=SnapshotTracesSource(scenario_dir),
        changelog=SnapshotChangesSource("scenarios/_changelog_master.json"),
    )

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    alert = {"message": "elevated error rate detected"}

    print("Running log analyst...")
    log_ev, log_hyp, log_meta = run_log_analyst(
        alert=alert,
        window_start=window_start,
        window_end=window_end,
        sources=sources,
        client=client,
    )
    print(f"  evidence={len(log_ev)} hypotheses={len(log_hyp)}")

    print("Running metrics analyst...")
    met_ev, met_hyp, met_meta = run_metrics_analyst(
        alert=alert,
        window_start=window_start,
        window_end=window_end,
        sources=sources,
        client=client,
    )
    print(f"  evidence={len(met_ev)} hypotheses={len(met_hyp)}")

    reports = [
        format_investigator_report("log_analyst", log_ev, log_hyp),
        format_investigator_report("metrics_analyst", met_ev, met_hyp),
    ]

    print("\n" + "=" * 60)
    print("\n\n".join(reports))
    print("=" * 60 + "\n")

    print("Running adjudicator...")
    adj_ev, verdict, adj_meta = run_adjudicator(
        alert=alert,
        window_start=window_start,
        window_end=window_end,
        reports=reports,
        investigator_evidence=log_ev + met_ev,
        sources=sources,
        client=client,
    )

    print(f"\nAdjudicator evidence: {len(adj_ev)}")
    for item in adj_ev:
        print(f"  {item.evidence_id}  {item.summary}")

    print()
    if verdict is None:
        print("No verdict submitted")
        print(f"run_meta: {adj_meta}")
    else:
        for i, cause in enumerate(verdict.ranked_causes, 1):
            print(f"{i}. [{cause.confidence:.2f}] {cause.cause}")
            print(f"   Cites: {', '.join(cause.evidence_ids)}")
        print(f"\nOverall confidence: {verdict.overall_confidence}")
        print(f"Escalate: {verdict.escalate}")
        if verdict.escalation_reason:
            print(f"Reason: {verdict.escalation_reason}")
        print(f"\nDissent: {verdict.dissent}")

    print(f"\nCorrect answer: {scenario['correct_answer'].strip()}")

    total_in = (
        log_meta["input_tokens"]
        + met_meta["input_tokens"]
        + adj_meta["input_tokens"]
    )
    total_out = (
        log_meta["output_tokens"]
        + met_meta["output_tokens"]
        + adj_meta["output_tokens"]
    )
    print(f"\nTotal tokens: {total_in} in, {total_out} out")