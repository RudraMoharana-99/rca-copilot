from pathlib import Path

from rca_copilot.sources.base import Severity, Status
from rca_copilot.sources.snapshot import (
    SnapshotLogsSource,
    SnapshotMetricsSource,
    SnapshotTracesSource,
)

SCENARIO = Path("scenarios/C1-valkey-cart-down")


def test_metrics_success():
    source = SnapshotMetricsSource(SCENARIO)
    result = source.query_metrics("error_rate_by_service", None, None)

    assert result.status == Status.SUCCESS
    assert len(result.series) == 9


def test_metrics_unknown_query():
    source = SnapshotMetricsSource(SCENARIO)
    result = source.query_metrics("nonsense", None, None)

    assert result.status == Status.NO_DATA


def test_logs_errors():
    source = SnapshotLogsSource(SCENARIO)
    result = source.query_logs(
        None,
        None,
        service="cart",
        min_severity=Severity.WARN,
    )

    assert result.status == Status.SUCCESS
    assert result.count == 4


def test_logs_sample():
    source = SnapshotLogsSource(SCENARIO)
    result = source.query_logs(
        None,
        None,
        service="cart",
    )

    assert result.status == Status.SUCCESS
    assert result.count == 200


def test_logs_unknown_service():
    source = SnapshotLogsSource(SCENARIO)
    result = source.query_logs(
        None,
        None,
        service="nope",
    )

    assert result.status == Status.NO_DATA


def test_traces_summaries():
    source = SnapshotTracesSource(SCENARIO)
    result = source.query_trace_summaries(None, None, None)

    assert result.status == Status.SUCCESS
    assert len(result.summaries) == 61


def test_traces_missing_id():
    source = SnapshotTracesSource(SCENARIO)
    result = source.get_trace("nonexistent")

    assert result.status == Status.NO_DATA
