import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request

from rca_copilot.agents.baseline import run_baseline
from rca_copilot.agents.graph import run_graph
from rca_copilot.agents.tools import SourceBundle
from rca_copilot.models import DiagnoseRequest, IncidentResponse, RankedCause, Verdict
from rca_copilot.sources.changelog import SnapshotChangesSource
from rca_copilot.sources.snapshot import (
    SnapshotLogsSource,
    SnapshotMetricsSource,
    SnapshotTracesSource,
)
from rca_copilot.store.aws import (
    get_incident,
    put_incident,
)
from rca_copilot.telemetry.metrics import setup_metrics
from rca_copilot.telemetry.tracing import setup_tracing

# =========================PATHS==============================
PROJECT_ROOT = Path(__file__).resolve().parents[3]

SCENARIOS_DIR = PROJECT_ROOT / "scenarios"

CHANGELOG_PATH = SCENARIOS_DIR / "_changelog_master.json"


# INCIDENTS: dict[str, "IncidentResponse"] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()

    setup_tracing()
    setup_metrics()

    api_key = os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not configured",
        )
    client = AsyncAnthropic(api_key=api_key)

    app.state.anthropic_client = client

    yield

    await client.close()


app = FastAPI(
    title="RCA Copilot API",
    lifespan=lifespan,
)


def build_snapshot_sources(scenario: str) -> SourceBundle:
    """
    Build the evidence sources for one stored scenario.

    The scenario name comes from the API request, so the resolved path is
    checked to ensure it remains underneath scenarios/.
    """
    scenarios_root = SCENARIOS_DIR.resolve()

    scenario_dir = (SCENARIOS_DIR / scenario).resolve()

    if scenarios_root not in scenario_dir.parents:
        raise HTTPException(
            status_code=400,
            detail="Invalid scenario name",
        )

    if not scenario_dir.is_dir():
        raise HTTPException(status_code=404, detail=(f"Scenario not found: {scenario}"))

    if not CHANGELOG_PATH.is_file():
        raise HTTPException(
            status_code=500,
            detail=("Snapshot changelog is unavailable"),
        )

    return SourceBundle(
        logs=SnapshotLogsSource(
            scenario_dir,
        ),
        metrics=SnapshotMetricsSource(
            scenario_dir,
        ),
        traces=SnapshotTracesSource(
            scenario_dir,
        ),
        changelog=SnapshotChangesSource(
            str(CHANGELOG_PATH),
        ),
    )


# ==================== Baseline adapter========================
def baseline_to_verdict(state) -> Verdict | None:
    """
    Convert the baseline's submitted Hypothesis into the same Verdict
    shape returned by the multi-agent graph.

    This gives the API one consistent response contract.
    """
    if not state.hypotheses:
        return None

    hypothesis = state.hypotheses[0]

    return Verdict(
        ranked_causes=[
            RankedCause(
                cause=hypothesis.cause,
                confidence=hypothesis.confidence,
                evidence_ids=hypothesis.evidence_ids,
            )
        ],
        overall_confidence=(hypothesis.confidence),
        dissent=None,
        escalate=False,
        escalation_reason=None,
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """
    Liveness only.

    Do NOT call Anthropic, Jaeger, Prometheus, or any other downstream
    dependency here.
    """
    return {
        "status": "ok",
    }


@app.post("/incidents", response_model=IncidentResponse)
async def create_incident(
    body: DiagnoseRequest,
    request: Request,
) -> IncidentResponse:
    sources = build_snapshot_sources(body.scenario)

    client: AsyncAnthropic = request.app.state.anthropic_client

    started = time.perf_counter()

    try:
        if body.config == "baseline":
            state = await run_baseline(
                alert=body.alert,
                window_start=body.window_start,
                window_end=body.window_end,
                sources=sources,
                client=client,
            )

            incident_id = state.incident_id
            verdict = baseline_to_verdict(state)
            run_meta = {"agents": [state.run_meta]}

        else:
            state = await run_graph(
                alert=body.alert,
                window_start=body.window_start,
                window_end=body.window_end,
                sources=sources,
                client=client,
            )

            incident_id = state["incident_id"]
            verdict = state["verdict"]
            run_meta = {"agents": state["run_metas"]}

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Diagnosis failed: {type(exc).__name__}",
        ) from exc

    elapsed = time.perf_counter() - started

    response = IncidentResponse(
        incident_id=incident_id,
        scenario=body.scenario,
        config=body.config,
        verdict=verdict,
        run_meta=run_meta,
        elapsed_seconds=elapsed,
    )

    put_incident(response)

    return response


@app.get(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
)
async def get_incident_endpoint(
    incident_id: str,
) -> IncidentResponse:
    incident = get_incident(incident_id)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return incident
