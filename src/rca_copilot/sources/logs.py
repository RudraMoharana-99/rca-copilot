from datetime import datetime

import httpx

from .base import (
    LogEntry,
    LogQueryResult,
    LogsSource,
    Severity,
    Status,
)


def severity_from_number(number: int) -> Severity:
    if 1 <= number <= 4:
        return Severity.TRACE
    elif 5 <= number <= 8:
        return Severity.DEBUG
    elif 9 <= number <= 12:
        return Severity.INFO
    elif 13 <= number <= 16:
        return Severity.WARN
    elif 17 <= number <= 20:
        return Severity.ERROR
    else:
        return Severity.FATAL


MIN_SEVERITY_NUMBER = {
    Severity.TRACE: 1,
    Severity.DEBUG: 5,
    Severity.INFO: 9,
    Severity.WARN: 13,
    Severity.ERROR: 17,
    Severity.FATAL: 21,
}


class OpenSearchLogSource(LogsSource):
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def query_logs(
        self,
        start: datetime,
        end: datetime,
        service: str | None = None,
        min_severity: Severity | None = None,
        limit: int = 100,
    ) -> LogQueryResult:

        start_iso = start.isoformat()
        end_iso = end.isoformat()

        filters = [
            {
                "range": {
                    "@timestamp": {
                        "gte": start_iso,
                        "lte": end_iso,
                    }
                }
            }
        ]

        if service is not None:
            filters.append({"term": {"resource.service.name.keyword": service}})

        if min_severity is not None:
            filters.append(
                {"range": {"severity.number": {"gte": MIN_SEVERITY_NUMBER[min_severity]}}}
            )

        body = {
            "size": limit,
            "sort": [{"@timestamp": "asc"}],
            "query": {"bool": {"filter": filters}},
        }

        try:
            response = httpx.post(
                f"{self.base_url}/otel-logs-*/_search",
                json=body,
                timeout=30.0,
            )
            response.raise_for_status()
            payload = response.json()

        except httpx.HTTPError:
            return LogQueryResult(status=Status.ERROR)

        hits = payload["hits"]["hits"]

        if not hits:
            return LogQueryResult(
                status=Status.NO_DATA,
            )

        total = payload["hits"]["total"]["value"]

        logs = []

        for hit in hits:
            src = hit["_source"]

            severity_number = src.get("severity", {}).get("number", 9)

            logs.append(
                LogEntry(
                    timestamp=src["@timestamp"],
                    service=src.get("resource", {}).get("service.name", "unknown"),
                    severity_number=severity_number,
                    severity=severity_from_number(severity_number),
                    message=src.get("body", ""),
                )
            )

        truncated = len(hits) < total

        return LogQueryResult(
            status=Status.SUCCESS,
            logs=logs,
            count=len(logs),
            truncated=truncated,
        )
