import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from rca_copilot.sources.base import LogsSource, Severity, Status
from rca_copilot.sources.changelog import SnapshotChangesSource
from rca_copilot.sources.logs import OpenSearchLogSource
from rca_copilot.sources.metrics import (
    QUERY_PROMQL,
    PrometheusMetricsSource,
)
from rca_copilot.sources.traces import JaegerTraceSource

# ===================================================================
# =========================Constant Block============================
# ===================================================================
LOG_SERVICES = [
    "frontend-proxy",
    "frontend",
    "cart",
    "checkout",
    "payment",
    "currency",
    "recommendation",
    "ad",
    "shipping",
    "quote",
    "email",
    "product-catalog",
]

LOG_LIMIT_PER_SERVICE = 500
LOG_SAMPLE_LIMIT = 200
TRACE_SERVICES = [
    "frontend",
    "frontend-proxy",
    "checkout",
    "cart",
]

MAX_FULL_TRACES = 20
CHANGELOG_MASTER = "scenarios/_changelog_master.json"


class CaptureConfig(BaseModel):
    prometheus_url: str
    jaeger_url: str
    opensearch_url: str


def load_config() -> CaptureConfig:
    load_dotenv()
    return CaptureConfig(
        prometheus_url=os.environ["PROMETHEUS_URL"],
        jaeger_url=os.environ["JAEGER_URL"],
        opensearch_url=os.environ["OPENSEARCH_URL"],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument("name")
    parser.add_argument("break_time")

    return parser.parse_args()


def compute_window(
    break_time: datetime,
) -> tuple[datetime, datetime]:
    window_start = break_time - timedelta(minutes=5)
    window_end = break_time + timedelta(minutes=10)

    return window_start, window_end


def capture_metrics(
    source: PrometheusMetricsSource,
    start: datetime,
    end: datetime,
    output_dir: Path,
) -> None:

    metrics_data = {}

    for query_name in QUERY_PROMQL.keys():
        result = source.query_metrics(
            query_name=query_name,
            start=start,
            end=end,
        )

        metrics_data[query_name] = result.model_dump(mode="json")

        print(f"Metrics: {query_name} | status={result.status} | series={len(result.series)}")

    with open(
        output_dir / "metrics.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            metrics_data,
            f,
            indent=2,
        )


def capture_logs(
    source: LogsSource,
    start: datetime,
    end: datetime,
    output_dir: Path,
) -> None:

    logs_data = {}

    for svc in LOG_SERVICES:
        imp_result = source.query_logs(
            service=svc,
            start=start,
            end=end,
            min_severity=Severity.WARN,
            limit=LOG_LIMIT_PER_SERVICE,
        )

        sample_result = source.query_logs(
            service=svc,
            start=start,
            end=end,
            limit=LOG_SAMPLE_LIMIT,
        )

        logs_data[svc] = {
            "errors": imp_result.model_dump(mode="json"),
            "sample": sample_result.model_dump(mode="json"),
        }

        print(
            f"Logs: {svc} | "
            f"errors={imp_result.status} "
            f"count={imp_result.count} "
            f"truncated={imp_result.truncated} | "
            f"sample={sample_result.status} "
            f"count={sample_result.count} "
            f"truncated={sample_result.truncated}"
        )

    with open(output_dir / "logs.json", "w", encoding="utf-8") as f:
        json.dump(logs_data, f, indent=2)


def capture_traces(
    source: JaegerTraceSource,
    start: datetime,
    end: datetime,
    output_dir: Path,
) -> None:

    summaries = {}

    for service in TRACE_SERVICES:
        result = source.query_trace_summaries(
            service=service,
            start=start,
            end=end,
        )

        print(f"Traces: {service} | status={result.status} | summaries={len(result.summaries)}")

        if result.status == Status.SUCCESS:
            for summary in result.summaries:
                summaries[summary.trace_id] = summary
    unique_summaries = list(summaries.values())
    error_summaries = [summary for summary in unique_summaries if summary.error_count > 0]

    selected_summaries = error_summaries[:MAX_FULL_TRACES]

    full_traces = []

    for summary in selected_summaries:
        result = source.get_trace(summary.trace_id)

        if result.status == Status.SUCCESS and result.trace is not None:
            full_traces.append(result.trace.model_dump(mode="json"))

    traces_data = {
        "summaries": [summary.model_dump(mode="json") for summary in unique_summaries],
        "full_traces": full_traces,
    }

    with open(
        output_dir / "traces.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            traces_data,
            f,
            indent=2,
        )

    print(f"Trace summary count: {len(unique_summaries)}")

    print(f"Error traces: {len(error_summaries)}")

    print(f"Full traces captured: {len(full_traces)}")


def capture_changes(
    source: SnapshotChangesSource,
    start: datetime,
    end: datetime,
    output_dir: Path,
) -> None:

    result = source.query_changes(
        start=start,
        end=end,
    )

    changes_data = result.model_dump(mode="json")

    with open(
        output_dir / "changelog.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            changes_data,
            f,
            indent=2,
        )

    print(f"Changelog: status={result.status} count={len(result.changes)}")


def main() -> None:
    config = load_config()
    args = parse_args()

    break_time = datetime.fromisoformat(args.break_time.replace("Z", "+00:00"))
    start, end = compute_window(break_time)

    output_dir = Path("scenarios") / args.name
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics_source = PrometheusMetricsSource(base_url=config.prometheus_url)
    capture_metrics(metrics_source, start, end, output_dir)

    # Logs
    logs_source = OpenSearchLogSource(base_url=config.opensearch_url)

    capture_logs(
        logs_source,
        start,
        end,
        output_dir,
    )

    traces_source = JaegerTraceSource(base_url=config.jaeger_url)

    capture_traces(
        traces_source,
        start,
        end,
        output_dir,
    )

    changelog_source = SnapshotChangesSource(file_path=CHANGELOG_MASTER)

    capture_changes(
        changelog_source,
        start,
        end,
        output_dir,
    )


if __name__ == "__main__":
    main()
