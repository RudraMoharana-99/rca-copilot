from datetime import UTC, datetime

import httpx

from .base import (
    DataPoint,
    MetricsQueryResult,
    MetricsSource,
    Series,
    Status,
)

QUERY_PROMQL = {
    "call_rate_by_service": ("sum by (service_name) (rate(traces_span_metrics_calls_total[5m]))"),
    "error_rate_by_service": (
        "sum by (service_name) "
        "(rate(traces_span_metrics_calls_total{"
        'status_code="STATUS_CODE_ERROR"}[5m]))'
    ),
    "latency_p95_by_service": (
        "histogram_quantile(0.95, "
        "sum by (service_name, le) "
        "(rate(traces_span_metrics_duration_milliseconds_bucket[5m])))"
    ),
    "container_memory_ratio": "container_memory_percent_ratio",
    "container_cpu": "container_cpu_utilization_ratio",
}

class PrometheusMetricsSource(MetricsSource):
    def __init__(self, base_url: str = "http://localhost:9090"):
        self.base_url = base_url.rstrip("/")

    def query_metrics(
        self,
        query_name: str,
        start: datetime,
        end: datetime,
    ) -> MetricsQueryResult:

        query = QUERY_PROMQL.get(query_name)

        if query is None:
            return MetricsQueryResult(status=Status.ERROR)

        params = {
            "query": query,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": "15s",
        }

        try:
            response = httpx.get(
                f"{self.base_url}/api/v1/query_range",
                params=params,
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()

        except httpx.HTTPError:
            return MetricsQueryResult(status=Status.ERROR)

        if payload.get("status") == "error":
            return MetricsQueryResult(status=Status.ERROR)

        results = payload.get("data", {}).get("result", [])

        if not results:
            return MetricsQueryResult(status=Status.NO_DATA)

        series = []

        for item in results:
            points = [
                DataPoint(
                    timestamp=datetime.fromtimestamp(
                        point[0],
                        tz=UTC,
                    ),
                    value=point[1],
                )
                for point in item["values"]
            ]

            series.append(
                Series(
                    labels=item.get("metric", {}),
                    points=points,
                )
            )

        return MetricsQueryResult(
            status=Status.SUCCESS,
            series=series,
        )
