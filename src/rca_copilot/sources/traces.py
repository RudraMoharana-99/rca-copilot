from datetime import UTC, datetime

import httpx

from .base import (
    Span,
    Status,
    Trace,
    TraceDetailResult,
    TraceQueryResult,
    TracesSource,
    TraceSummary,
)


def flatten_attributes(attributes: list[dict]) -> dict[str, str | int | float | bool]:
    result = {}

    for attribute in attributes:
        key = attribute["key"]
        value = attribute["value"]

        if not value:
            continue

        value_type = next(iter(value))

        if value_type == "arrayValue":
            continue

        raw = value[value_type]
        if value_type == "intValue":
            result[key] = int(raw)
        else:
            result[key] = raw

    return result


def nano_to_datetime(value: str) -> datetime:

    seconds = int(value) / 1e9
    return datetime.fromtimestamp(seconds, tz=UTC)


def is_error_span(span: dict, attributes: dict) -> bool:
    status_code = span.get("status", {}).get("code")

    return status_code == 2 or attributes.get("error") == "true"


class JaegerTraceSource(TracesSource):
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def get_trace(self, trace_id: str) -> TraceDetailResult:
        url = f"{self.base_url}/traces/{trace_id}"

        try:
            response = httpx.get(
                url=url,
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            return TraceDetailResult(status=Status.ERROR)

        spans = []

        for rs in payload["result"]["resourceSpans"]:
            resource_attrs = flatten_attributes(rs["resource"]["attributes"])
            service = resource_attrs["service.name"]

            for ss in rs.get("scopeSpans", []):
                for raw in ss.get("spans", []):
                    attrs = flatten_attributes(raw.get("attributes", []))
                    spans.append(
                        Span(
                            span_id=raw["spanId"],
                            parent_span_id=raw.get("parentSpanId"),
                            service_name=service,
                            operation_name=raw["name"],
                            start_time=nano_to_datetime(raw["startTimeUnixNano"]),
                            end_time=nano_to_datetime(raw["endTimeUnixNano"]),
                            is_error=is_error_span(raw, attrs),
                            attributes=attrs,
                        )
                    )
        if not spans:
            return TraceDetailResult(status=Status.NO_DATA)
        else:
            return TraceDetailResult(
                status=Status.SUCCESS, trace=Trace(trace_id=trace_id, spans=spans)
            )

    def query_trace_summaries(
        self, service: str, start: datetime, end: datetime, limit: int = 20
    ) -> TraceQueryResult:

        params = {
            "query.serviceName": service,
            "query.startTimeMin": start.isoformat(),
            "query.startTimeMax": end.isoformat(),
            "query.searchDepth": limit,
        }

        try:
            response = httpx.get(f"{self.base_url}/trace-summaries", params=params, timeout=10.0)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            return TraceQueryResult(status=Status.ERROR)
        summaries = payload.get("summaries", [])
        if not summaries:
            return TraceQueryResult(status=Status.NO_DATA)

        result = []

        for item in summaries:
            result.append(
                TraceSummary(
                    trace_id=item["traceId"],
                    root_service=item.get("rootServiceName"),
                    span_count=item["spanCount"],
                    error_count=item.get("errorSpanCount", 0),
                    start_time=nano_to_datetime(item["minStartTimeUnixNano"]),
                    end_time=nano_to_datetime(item["maxEndTimeUnixNano"]),
                )
            )
        return TraceQueryResult(status=Status.SUCCESS, summaries=result)


if __name__ == "__main__":
    convert = nano_to_datetime("1788264524769628855")
    print(convert)
    # error span
    print(is_error_span({"status": {"code": 2}}, {"error": "true"}))  # True

    # healthy span
    print(is_error_span({"status": {}}, {"http.status_code": "200"}))  # False

    # status code 1 = OK, not error
    print(is_error_span({"status": {"code": 1}}, {}))  # False

    from datetime import datetime, timedelta

    s = JaegerTraceSource("http://localhost:63126/jaeger/ui/api/v3")
    end = datetime.now(UTC)
    start = end - timedelta(hours=1)
    r = s.query_trace_summaries("frontend", start, end)
    print(r.status, len(r.summaries))

    d = s.get_trace(r.summaries[0].trace_id)
    print(d.status, len(d.trace.spans))

    roots = [x for x in d.trace.spans if x.parent_span_id is None]
    print("roots:", len(roots))

    errors = [x for x in d.trace.spans if x.is_error]
    print("errors:", [(x.service_name, x.operation_name) for x in errors])

    big = max(r.summaries, key=lambda x: x.span_count)
    d = s.get_trace(big.trace_id)
    print(d.status, len(d.trace.spans))
    roots = [x for x in d.trace.spans if x.parent_span_id is None]
    print("roots:", len(roots))
