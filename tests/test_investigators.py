import os
from datetime import UTC, datetime
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from rca_copilot.agents.investigators import run_metrics_analyst
from rca_copilot.agents.tools import SourceBundle
from rca_copilot.sources.changelog import SnapshotChangesSource
from rca_copilot.sources.snapshot import (
    SnapshotLogsSource,
    SnapshotMetricsSource,
    SnapshotTracesSource,
)

if __name__ == "__main__":
    load_dotenv()

    scenario = Path("scenarios/C1-valkey-cart-down")

    sources = SourceBundle(
        logs=SnapshotLogsSource(scenario),
        metrics=SnapshotMetricsSource(scenario),
        traces=SnapshotTracesSource(scenario),
        changelog=SnapshotChangesSource("scenarios/_changelog_master.json"),
    )

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    evidence, hypotheses, run_meta = run_metrics_analyst(
        alert={
            "service": "cart",
            "message": "elevated error rate on cart",
        },
        window_start=datetime(2026, 9, 3, 6, 59, 19, tzinfo=UTC),
        window_end=datetime(2026, 9, 3, 7, 14, 19, tzinfo=UTC),
        sources=sources,
        client=client,
    )

    print(f"Evidence gathered: {len(evidence)}")

    for item in evidence:
        print(f"  {item.evidence_id} {item.source}: {item.summary}")

    print()

    print(f"Hypotheses submitted: {len(hypotheses)}")

    for hypothesis in hypotheses:
        print(f"  Cause: {hypothesis.cause}")
        print(f"  Confidence: {hypothesis.confidence}")
        print(f"  Cites: {hypothesis.evidence_ids}")
        print()

    print(f"Run metadata: {run_meta}")
