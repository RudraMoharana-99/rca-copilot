import json
from dataclasses import dataclass
from datetime import UTC, datetime

from rca_copilot.models import Evidence
from rca_copilot.sources.base import (
    ChangelogSource,
    LogsSource,
    MetricsSource,
    Severity,
    Status,
    TracesSource,
)

submit_hypothesis = {
    "name": "submit_hypothesis",
    "description": (
        "Submit your final root cause conclusion. Call this once you have "
        "gathered enough evidence. You must cite the evidence IDs that "
        "support your conclusion."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "cause": {
                "type": "string",
                "description": (
                    "The root cause in one sentence. Name the specific "
                    "component that failed and what the consequence was."
                ),
            },
            "confidence": {
                "type": "number",
                "description": (
                    "Your confidence from 0 to 1. Use a low value if the "
                    "evidence is weak or a source was unreachable."
                ),
            },
            "evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": ("The evidence IDs supporting this conclusion. Must not be empty."),
            },
        },
        "required": ["cause", "confidence", "evidence_ids"],
    },
}

search_logs = {
    "name": "search_logs",
    "description": (
        "Search logs for one service within the incident window. "
        "Use min_severity=ERROR to find failures and WARN to find warnings "
        "and errors. If min_severity is omitted, returns a sample of logs at "
        "all severities, which is useful for seeing normal behaviour before "
        "the break. A service may be silent even when it is failing, so "
        "absence of ERROR logs does not prove the service is healthy. "
        "The result includes a count and a truncated flag; if truncated, the "
        "query returned only part of what matched. "
        "Returns logs and a status indicating whether the query succeeded, "
        "returned no data, or the log source was unreachable."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "The service whose logs should be searched.",
            },
            "min_severity": {
                "type": "string",
                "enum": ["INFO", "WARN", "ERROR"],
                "description": (
                    "Minimum severity to return. Use ERROR for failures "
                    "and WARN for warnings and errors. Omit to see a sample "
                    "of all severities."
                ),
            },
        },
        "required": ["service"],
    },
}

get_metrics = {
    "name": "get_metrics",
    "description": (
        "Query a named metric for the incident window. Only the predefined "
        "queries listed in the schema are supported. "
        "call_rate_by_service, error_rate_by_service and "
        "latency_p95_by_service are broken down per service and describe "
        "request behaviour. container_memory_ratio and container_cpu are "
        "broken down per container and describe resource usage. "
        "Memory ratio is unreliable on its own, because healthy containers "
        "commonly sit above 90 percent of their limit; rising CPU combined "
        "with falling memory usually indicates a container thrashing under "
        "memory pressure. "
        "Returns a status indicating whether the query succeeded, returned "
        "no data, or the metric source was unreachable."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query_name": {
                "type": "string",
                "enum": [
                    "call_rate_by_service",
                    "error_rate_by_service",
                    "latency_p95_by_service",
                    "container_memory_ratio",
                    "container_cpu",
                ],
                "description": "Name of the predefined metric query to execute.",
            },
        },
        "required": ["query_name"],
    },
}

find_traces = {
    "name": "find_traces",
    "description": (
        "Find trace summaries for one service within the incident window. "
        "Use this to identify traces with errors, slow behaviour, or "
        "cross-service dependency failures. Each summary shows the services "
        "involved, span counts, timing, and an error_count field indicating "
        "how many spans in that trace failed; filter on error_count to find "
        "traces worth investigating. "
        "Use get_trace_detail with a trace ID when a specific trace needs "
        "deeper investigation. "
        "Returns a status indicating whether the query succeeded, returned "
        "no data, or the trace source was unreachable."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": ("The service whose trace summaries should be searched."),
            },
        },
        "required": ["service"],
    },
}

get_trace_detail = {
    "name": "get_trace_detail",
    "description": (
        "Retrieve the full trace for a specific trace ID. This call is "
        "expensive, so call find_traces first and select a trace with a "
        "non-zero error_count rather than fetching traces blindly. "
        "The full trace contains individual spans with service names, "
        "operations, timing, errors, parent-child relationships and "
        "attributes. In a cascading failure, the deepest failing span is "
        "the likely cause and the spans above it are relaying that failure. "
        "Only a capped subset of error traces has full detail stored, so a "
        "no-data result is common and does not indicate a problem. "
        "Returns a status indicating whether the trace was found, was not "
        "stored, or whether the trace source was unavailable."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "trace_id": {
                "type": "string",
                "description": "The ID of the trace to retrieve.",
            },
        },
        "required": ["trace_id"],
    },
}

get_recent_changes = {
    "name": "get_recent_changes",
    "description": (
        "Find recent deployments, configuration changes, or other recorded "
        "changes for one service within the incident window. "
        "Use this to determine whether a deliberate change may have caused "
        "the incident. Changes can provide causal evidence that logs, "
        "metrics and traces do not reveal, particularly when the failing "
        "service is silent. "
        "An empty result is meaningful evidence rather than a failure: it "
        "means nothing was deliberately changed, which points toward an "
        "infrastructure or dependency failure rather than a deployment. "
        "Returns a status indicating whether the query succeeded, returned "
        "no data, or the change source was unreachable."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": ("The service whose recent changes should be searched."),
            },
        },
        "required": ["service"],
    },
}

ALL_TOOLS = [
    search_logs,
    get_metrics,
    find_traces,
    get_trace_detail,
    get_recent_changes,
]


@dataclass
class SourceBundle:
    logs: LogsSource
    metrics: MetricsSource
    traces: TracesSource
    changelog: ChangelogSource


def execute_tool(
    name: str,
    arguments: dict,
    sources: SourceBundle,
    window_start: datetime,
    window_end: datetime,
    agent: str = "baseline",
) -> Evidence:

    start = window_start
    end = window_end

    if name == "search_logs":
        service = arguments["service"]

        min_severity = (
            Severity(arguments["min_severity"]) if arguments.get("min_severity") else None
        )
        result = sources.logs.query_logs(
            start=start,
            end=end,
            service=service,
            min_severity=min_severity,
        )

        summary = (
            f"{service}: {result.count} log entries, "
            f"status {result.status}, truncated {result.truncated}"
        )

        source_name = "logs"

    elif name == "get_metrics":
        query_name = arguments["query_name"]

        result = sources.metrics.query_metrics(
            query_name=query_name,
            start=start,
            end=end,
        )

        summary = f"{query_name}: {len(result.series)} series, status {result.status}"

        source_name = "metrics"

    elif name == "find_traces":
        service = arguments["service"]

        result = sources.traces.query_trace_summaries(
            service=service,
            start=start,
            end=end,
        )

        error_count = sum(1 for trace_summary in result.summaries if trace_summary.error_count > 0)

        summary = (
            f"{service}: {len(result.summaries)} summaries, "
            f"{error_count} with errors, status {result.status}"
        )

        source_name = "traces"

    elif name == "get_trace_detail":
        trace_id = arguments["trace_id"]

        result = sources.traces.get_trace(trace_id)

        summary = f"{trace_id}: trace detail status {result.status}"

        source_name = "traces"

    elif name == "get_recent_changes":
        service = arguments["service"]

        result = sources.changelog.query_changes(
            start=start,
            end=end,
            service=service,
        )

        change_count = len(result.changes)

        if change_count == 0:
            summary = f"{service}: no changes recorded"
        else:
            summary = f"{service}: {change_count} change(s)"

        source_name = "changelog"

    else:
        return Evidence(
            agent=agent,
            source="tool_executor",
            query={
                "name": name,
                "arguments": arguments,
            },
            status=Status.ERROR,
            summary=f"Tool does not exist: {name}",
            raw=None,
            timestamp=datetime.now(UTC),
        )

    query = {
        **arguments,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }

    return Evidence(
        agent=agent,
        source=source_name,
        query=query,
        status=result.status,
        summary=summary,
        raw=result.model_dump(mode="json"),
        timestamp=datetime.now(UTC),
    )


KEEP_SPAN_ATTRS = {
    "http.status_code",
    "http.response.status_code",
    "rpc.grpc.status_code",
    "otel.status_description",
    "db.system",
    "server.address",
    "server.port",
    "error",
}


def _slim_span(span: dict) -> dict:
    attrs = span.get("attributes", {})
    return {
        **span,
        "attributes": {k: v for k, v in attrs.items() if k in KEEP_SPAN_ATTRS},
    }


def evidence_to_tool_result(
    evidence: Evidence,
    max_items: int = 10,
) -> str:
    raw = evidence.raw or {}

    if evidence.source == "logs":
        logs = raw.get("logs", [])

        slim_logs = [{**log, "message": log.get("message", "")[:400]} for log in logs[:max_items]]

        raw = {**raw, "logs": slim_logs}

        if len(logs) > max_items:
            raw["_truncated_for_model"] = (
                f"Only the first {max_items} of {len(logs)} log entries "
                "are shown, and each message is capped at 400 characters."
            )
    elif evidence.source == "metrics":
        series = raw.get("series", [])

        if len(series) > max_items:
            raw = {
                **raw,
                "series": series[:max_items],
                "_truncated_for_model": (
                    f"Only the first {max_items} of {len(series)} metric series are shown."
                ),
            }

    elif evidence.source == "traces":
        summaries = raw.get("summaries", [])
        if len(summaries) > max_items:
            raw = {
                **raw,
                "summaries": summaries[:max_items],
                "_truncated_for_model": (
                    f"Only the first {max_items} of {len(summaries)} trace summaries are shown."
                ),
            }

        trace = raw.get("trace")
        if trace and trace.get("spans"):
            spans = trace["spans"]
            slim = [_slim_span(s) for s in spans[:max_items]]
            raw = {
                **raw,
                "trace": {**trace, "spans": slim},
            }
            if len(spans) > max_items:
                raw["_truncated_for_model"] = (
                    f"Only the first {max_items} of {len(spans)} spans "
                    "are shown, with attributes reduced to diagnostic fields."
                )

    return (
        f"Summary: {evidence.summary}\n"
        f"Status: {evidence.status}\n"
        f"Data: {json.dumps(raw, indent=2)}"
        f"Evidence ID: {evidence.evidence_id}\n"
    )
