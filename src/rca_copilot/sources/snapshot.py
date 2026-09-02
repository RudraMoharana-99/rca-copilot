import json
from datetime import datetime
from pathlib import Path

from .base import (
    LogQueryResult,
    LogsSource,
    MetricsQueryResult,
    MetricsSource,
    Severity,
    Status,
    Trace,
    TraceDetailResult,
    TraceQueryResult,
    TracesSource,
    TraceSummary,
)


class SnapshotMetricsSource(MetricsSource):
    def __init__(self, snapshot_dir: Path):
        with open(snapshot_dir / "metrics.json", encoding="utf-8") as f:
            self.metrics_data = json.load(f)

    def query_metrics(self, query_name: str, start: datetime, end: datetime) -> MetricsQueryResult:
        if query_name not in self.metrics_data:
            return MetricsQueryResult(status=Status.NO_DATA)
        return MetricsQueryResult.model_validate(self.metrics_data[query_name])


class SnapshotLogsSource(LogsSource):
    def __init__(self, snapshot_dir: Path):
        with open(snapshot_dir / "logs.json", encoding="utf-8") as f:
            self.logs_data = json.load(f)

    def query_logs(
        self,
        start: datetime,
        end: datetime,
        service: str | None = None,
        min_severity=None,
        limit=100,
    ) -> LogQueryResult:

        if service not in self.logs_data:
            return LogQueryResult(status=Status.NO_DATA)

        if min_severity is None or min_severity in (
            Severity.TRACE,
            Severity.DEBUG,
            Severity.INFO,
        ):
            key = "sample"
        else:
            key = "errors"

        return LogQueryResult.model_validate(self.logs_data[service][key])


class SnapshotTracesSource(TracesSource):
    def __init__(self, snapshot_dir: Path):
        with open(snapshot_dir / "traces.json", encoding="utf-8") as f:
            self.traces_data = json.load(f)

    def query_trace_summaries(
        self,
        service: str | None,
        start: datetime,
        end: datetime,
        limit: int = 20,
    ) -> TraceQueryResult:
        raw_summaries = self.traces_data.get("summaries", [])

        if not raw_summaries:
            return TraceQueryResult(status=Status.NO_DATA)

        summaries = [TraceSummary.model_validate(item) for item in raw_summaries]

        return TraceQueryResult(
            status=Status.SUCCESS,
            summaries=summaries,
        )

    def get_trace(self, trace_id: str) -> TraceDetailResult:
        for item in self.traces_data.get("full_traces", []):
            if item.get("trace_id") == trace_id:
                return TraceDetailResult(
                    status=Status.SUCCESS,
                    trace=Trace.model_validate(item),
                )

        return TraceDetailResult(status=Status.NO_DATA)
