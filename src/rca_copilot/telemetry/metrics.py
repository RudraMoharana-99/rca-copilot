import os

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

_instruments: dict = {}


def setup_metrics(
    service_name: str = "rca-copilot",
) -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")

    if not endpoint:
        return

    resource = Resource.create({"service.name": service_name})

    exporter = OTLPMetricExporter(endpoint=endpoint)
    reader = PeriodicExportingMetricReader(exporter)

    provider = MeterProvider(
        resource=resource,
        metric_readers=[reader],
    )

    metrics.set_meter_provider(provider)


def _get_instruments() -> dict:
    if _instruments:
        return _instruments

    meter = metrics.get_meter("rca_copilot")

    _instruments["incidents"] = meter.create_counter(
        name="incidents_total",
        description="Number of RCA incidents processed",
    )
    _instruments["escalations"] = meter.create_counter(
        name="escalations_total",
        description="Number of RCA incidents escalated for human review",
    )
    _instruments["agent_duration"] = meter.create_histogram(
        name="agent_duration_seconds",
        unit="s",
        description="Duration of RCA agent executions",
    )
    _instruments["tokens"] = meter.create_counter(
        name="tokens_total",
        description="Number of LLM tokens consumed",
    )
    _instruments["cost"] = meter.create_counter(
        name="cost_micro_usd_total",
        description="Estimated LLM cost in millionths of a USD",
    )
    _instruments["tool_failures"] = meter.create_counter(
        name="tool_failures_total",
        description="Number of RCA evidence tool failures",
    )

    return _instruments


def record_incident(outcome: str, config: str) -> None:
    _get_instruments()["incidents"].add(1, {"outcome": outcome, "config": config})


def record_escalation(config: str) -> None:
    _get_instruments()["escalations"].add(1, {"config": config})


def record_agent_duration(agent: str, seconds: float) -> None:
    _get_instruments()["agent_duration"].record(seconds, {"agent": agent})


def record_tokens(agent: str, direction: str, count: int) -> None:
    _get_instruments()["tokens"].add(count, {"agent": agent, "direction": direction})


def record_cost(config: str, usd: float) -> None:
    _get_instruments()["cost"].add(int(usd * 1_000_000), {"config": config})


def record_tool_failure(source: str, tool: str) -> None:
    _get_instruments()["tool_failures"].add(1, {"source": source, "tool": tool})
