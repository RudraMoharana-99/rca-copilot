import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from rca_copilot.sources.base import LogsSource, Severity
from rca_copilot.sources.logs import OpenSearchLogSource
from rca_copilot.sources.metrics import (
    QUERY_PROMQL,
    PrometheusMetricsSource,
)

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


if __name__ == "__main__":
    main()
