import operator
import time
from datetime import datetime
from typing import Annotated, TypedDict
from uuid import uuid4

from anthropic import AsyncAnthropic
from langgraph.graph import END, START, StateGraph
from opentelemetry.trace import Status as SpanStatus
from opentelemetry.trace import StatusCode

from rca_copilot.models import Evidence, Hypothesis, Verdict
from rca_copilot.telemetry.metrics import record_agent_duration, record_tokens
from rca_copilot.telemetry.tracing import setup_tracing, tracer

from .adjudicator import (
    MODEL as ADJUDICATOR_MODEL,
)
from .adjudicator import (
    format_investigator_report,
    run_adjudicator,
)
from .investigators import (
    MODEL as INVESTIGATOR_MODEL,
)
from .investigators import (
    run_log_analyst,
    run_metrics_analyst,
)
from .tools import SourceBundle


class GraphState(TypedDict):
    incident_id: str
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
        with tracer.start_as_current_span("agent.log_analyst") as span:
            started = time.perf_counter()
            evidence, hypotheses, run_meta = await run_log_analyst(
                alert=state["alert"],
                window_start=state["window_start"],
                window_end=state["window_end"],
                sources=sources,
                client=client,
            )
            record_agent_duration("log_analyst", time.perf_counter() - started)
            span.set_attribute("agent", "log_analyst")
            span.set_attribute("turns", run_meta.get("turns", 0))
            span.set_attribute("input_tokens", run_meta.get("input_tokens", 0))
            span.set_attribute("output_tokens", run_meta.get("output_tokens", 0))
            span.set_attribute("cache_read_tokens", run_meta.get("cache_read_tokens", 0))
            span.set_attribute("evidence_count", len(evidence))
            span.set_attribute("hypothesis_count", len(hypotheses))
            span.set_attribute("stop_reason", run_meta.get("stop_reason", ""))

            record_tokens("log_analyst", "input", run_meta.get("input_tokens", 0))
            record_tokens("log_analyst", "output", run_meta.get("output_tokens", 0))

            if not hypotheses:
                span.set_status(SpanStatus(StatusCode.ERROR, "no hypotheses submitted"))
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
        with tracer.start_as_current_span("agent.metrics_analyst") as span:
            started = time.perf_counter()
            evidence, hypotheses, run_meta = await run_metrics_analyst(
                alert=state["alert"],
                window_start=state["window_start"],
                window_end=state["window_end"],
                sources=sources,
                client=client,
            )
            record_agent_duration("metrics_analyst", time.perf_counter() - started)
            span.set_attribute("agent", "metrics_analyst")
            span.set_attribute("turns", run_meta.get("turns", 0))
            span.set_attribute("input_tokens", run_meta.get("input_tokens", 0))
            span.set_attribute("output_tokens", run_meta.get("output_tokens", 0))
            span.set_attribute("cache_read_tokens", run_meta.get("cache_read_tokens", 0))
            span.set_attribute("evidence_count", len(evidence))
            span.set_attribute("hypothesis_count", len(hypotheses))
            span.set_attribute("stop_reason", run_meta.get("stop_reason", ""))
            record_tokens("metrics_analyst", "input", run_meta.get("input_tokens", 0))
            record_tokens("metrics_analyst", "output", run_meta.get("output_tokens", 0))

            if not hypotheses:
                span.set_status(SpanStatus(StatusCode.ERROR, "no hypotheses submitted"))
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
        with tracer.start_as_current_span("agent.adjudicator") as span:
            started = time.perf_counter()
            evidence, verdict, run_meta = await run_adjudicator(
                alert=state["alert"],
                window_start=state["window_start"],
                window_end=state["window_end"],
                reports=state["reports"],
                investigator_evidence=state["evidence"],
                sources=sources,
                client=client,
            )
            record_agent_duration("adjudicator", time.perf_counter() - started)
            span.set_attribute("agent", "adjudicator")
            span.set_attribute("turns", run_meta.get("turns", 0))
            span.set_attribute("input_tokens", run_meta.get("input_tokens", 0))
            span.set_attribute("output_tokens", run_meta.get("output_tokens", 0))
            span.set_attribute("cache_read_tokens", run_meta.get("cache_read_tokens", 0))
            span.set_attribute("reports_received", len(state["reports"]))
            span.set_attribute("verdict_submitted", verdict is not None)
            record_tokens("adjudicator", "input", run_meta.get("input_tokens", 0))
            record_tokens("adjudicator", "output", run_meta.get("output_tokens", 0))

            if verdict is None:
                span.set_status(SpanStatus(StatusCode.ERROR, "no verdict submitted"))
            else:
                span.set_attribute("escalate", verdict.escalate)
                span.set_attribute("overall_confidence", verdict.overall_confidence)
                span.set_attribute("ranked_causes", len(verdict.ranked_causes))

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

    incident_id = uuid4().hex[:8]
    initial_state: GraphState = {
        "incident_id": incident_id,
        "alert": alert,
        "window_start": window_start,
        "window_end": window_end,
        "evidence": [],
        "hypotheses": [],
        "reports": [],
        "run_metas": [],
        "verdict": None,
    }
    with tracer.start_as_current_span("incident.diagnose") as root_span:
        root_span.set_attribute(
            "incident.id",
            incident_id,
        )

        root_span.set_attribute(
            "config",
            "multi_agent",
        )

        root_span.set_attribute(
            "model.investigator",
            INVESTIGATOR_MODEL,
        )

        root_span.set_attribute(
            "model.adjudicator",
            ADJUDICATOR_MODEL,
        )
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

        setup_tracing()

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
