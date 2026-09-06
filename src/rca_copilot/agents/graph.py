import operator
from datetime import datetime
from typing import Annotated, TypedDict

from anthropic import AsyncAnthropic
from langgraph.graph import END, START, StateGraph

from rca_copilot.models import Evidence, Hypothesis, Verdict

from .adjudicator import (
    format_investigator_report,
    run_adjudicator,
)
from .investigators import (
    run_log_analyst,
    run_metrics_analyst,
)
from .tools import SourceBundle


class GraphState(TypedDict):
    alert: dict
    window_start: datetime
    window_end: datetime

    evidence: Annotated[list[Evidence], operator.add]
    hypotheses: Annotated[list[Hypothesis], operator.add]
    reports: Annotated[list[str], operator.add]
    run_metas: Annotated[list[dict], operator.add]

    verdict: Verdict | None


def build_graph(
    sources: SourceBundle,
    client: AsyncAnthropic,
):
    async def log_node(state: GraphState) -> dict:
        evidence, hypotheses, run_meta = await run_log_analyst(
            alert=state["alert"],
            window_start=state["window_start"],
            window_end=state["window_end"],
            sources=sources,
            client=client,
        )

        report = format_investigator_report(
            "log_analyst",
            evidence=evidence,
            hypotheses=hypotheses,
        )

        return {
            "evidence": evidence,
            "hypotheses": hypotheses,
            "reports": [report],
            "run_metas": [run_meta],
        }

    async def metrics_node(
        state: GraphState,
    ) -> dict:
        evidence, hypotheses, run_meta = await run_metrics_analyst(
            alert=state["alert"],
            window_start=state["window_start"],
            window_end=state["window_end"],
            sources=sources,
            client=client,
        )
        report = format_investigator_report(
            "metrics_analyst",
            evidence,
            hypotheses,
        )

        return {
            "evidence": evidence,
            "hypotheses": hypotheses,
            "reports": [report],
            "run_metas": [run_meta],
        }

    async def adjudicator_node(
        state: GraphState,
    ) -> dict:
        evidence, verdict, run_meta = await run_adjudicator(
            alert=state["alert"],
            window_start=state["window_start"],
            window_end=state["window_end"],
            reports=state["reports"],
            investigator_evidence=state["evidence"],
            sources=sources,
            client=client,
        )

        return {
            "evidence": evidence,
            "verdict": verdict,
            "run_metas": [run_meta],
        }

    builder = StateGraph(GraphState)

    builder.add_node("log_analyst", log_node)
    builder.add_node("metrics_analyst", metrics_node)
    builder.add_node("adjudicator", adjudicator_node)

    builder.add_edge(START, "log_analyst")
    builder.add_edge(START, "metrics_analyst")
    builder.add_edge("log_analyst", "adjudicator")
    builder.add_edge("metrics_analyst", "adjudicator")
    builder.add_edge("adjudicator", END)

    return builder.compile()


async def run_graph(
    alert: dict,
    window_start: datetime,
    window_end: datetime,
    sources: SourceBundle,
    client: AsyncAnthropic,
) -> GraphState:
    graph = build_graph(
        sources=sources,
        client=client,
    )

    initial_state: GraphState = {
        "alert": alert,
        "window_start": window_start,
        "window_end": window_end,
        "evidence": [],
        "hypotheses": [],
        "reports": [],
        "run_metas": [],
        "verdict": None,
    }

    result = await graph.ainvoke(initial_state)

    return result


if __name__ == "__main__":
    import asyncio
    import os
    import sys
    import time

    from dotenv import load_dotenv

    from rca_copilot.agents.adjudicator import load_scenario
    from rca_copilot.sources.changelog import SnapshotChangesSource
    from rca_copilot.sources.snapshot import (
        SnapshotLogsSource,
        SnapshotMetricsSource,
        SnapshotTracesSource,
    )

    async def main() -> None:
        load_dotenv()

        scenario_dir, scenario, window_start, window_end = load_scenario(sys.argv[1])

        print(f"Scenario: {scenario['id']} - {scenario['name']}\n")

        sources = SourceBundle(
            logs=SnapshotLogsSource(scenario_dir),
            metrics=SnapshotMetricsSource(scenario_dir),
            traces=SnapshotTracesSource(scenario_dir),
            changelog=SnapshotChangesSource("scenarios/_changelog_master.json"),
        )

        client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        started = time.perf_counter()

        result = await run_graph(
            alert={"message": "elevated error rate detected"},
            window_start=window_start,
            window_end=window_end,
            sources=sources,
            client=client,
        )

        elapsed = time.perf_counter() - started

        print(f"Reports: {len(result['reports'])}")
        print(f"Evidence: {len(result['evidence'])}")
        print(f"Hypotheses: {len(result['hypotheses'])}\n")

        verdict = result["verdict"]
        if verdict is None:
            print("No verdict submitted")
        else:
            for i, cause in enumerate(verdict.ranked_causes, 1):
                print(f"{i}. [{cause.confidence:.2f}] {cause.cause}")
            print(f"\nEscalate: {verdict.escalate}")

        print(f"\nCorrect answer: {scenario['correct_answer'].strip()}")

        for meta in result["run_metas"]:
            print(
                f"\n{meta['agent']}: turns={meta['turns']} "
                f"in={meta['input_tokens']} out={meta['output_tokens']}"
            )

        print(f"\nElapsed: {elapsed:.1f}s")

    asyncio.run(main())
