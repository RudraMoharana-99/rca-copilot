from datetime import UTC, datetime
from pathlib import Path

from rca_copilot.agents.tools import (
    SourceBundle,
    evidence_to_tool_result,
    execute_tool,
)
from rca_copilot.sources.changelog import SnapshotChangesSource
from rca_copilot.sources.snapshot import (
    SnapshotLogsSource,
    SnapshotMetricsSource,
    SnapshotTracesSource,
)

scenario = Path("scenarios/C1-valkey-cart-down")

sources = SourceBundle(
    logs=SnapshotLogsSource(scenario),
    metrics=SnapshotMetricsSource(scenario),
    traces=SnapshotTracesSource(scenario),
    changelog=SnapshotChangesSource("scenarios/_changelog_master.json"),
)

WINDOW_START = datetime(2026, 9, 3, 6, 59, 19, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 3, 7, 14, 19, tzinfo=UTC)

ev = execute_tool(
    "search_logs",
    {"service": "cart", "min_severity": "ERROR"},
    sources,
    window_start=WINDOW_START,
    window_end=WINDOW_END,
)

print(ev.summary)
print()
print(evidence_to_tool_result(ev))
for name, args in [
    ("get_metrics", {"query_name": "error_rate_by_service"}),
    ("find_traces", {"service": "frontend"}),
    ("get_recent_changes", {"service": "cart"}),
    ("nonsense_tool", {}),
]:
    ev = execute_tool(name, args, sources, window_start=WINDOW_START, window_end=WINDOW_END)
    print(ev.summary)
ev = execute_tool("find_traces", {"service": "frontend"}, sources, window_start=WINDOW_START, window_end=WINDOW_END)
print("_truncated_for_model" in evidence_to_tool_result(ev))
