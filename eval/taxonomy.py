import json
from collections import Counter, defaultdict
from pathlib import Path

from rca_copilot.agents.baseline import SERVICES

FAILURE_CLASSES = (
    "correct",
    "outranked",
    "absent",
    "no_verdict",
    "error",
)


def normalize_component(text: str) -> str:
    """Normalize component names consistently with the scorer."""
    return text.lower().replace("-", " ").replace("_", " ")


def classify_run(record: dict) -> str:
    """
    Classify one evaluation run.

    Order matters:
    - crashed runs are errors
    - completed runs without causes are no_verdict
    - correct means expected component ranked first
    - outranked means expected component exists below rank 1
    - absent means expected component was not ranked
    """
    if record.get("error") is not None:
        return "error"

    if record.get("num_causes", 0) == 0:
        return "no_verdict"

    if record.get("correct") is True:
        return "correct"

    if record.get("rank_position") is not None:
        return "outranked"

    return "absent"


def blamed_component(
    record: dict,
    services: list[str],
) -> str | None:
    """
    Return the service blamed in the top-ranked cause.

    If several known services appear, choose the one appearing
    earliest in the cause text. If two overlap at the same position,
    prefer the longer service name.
    """
    verdict = record.get("verdict")

    if not verdict:
        return None

    ranked_causes = verdict.get(
        "ranked_causes",
        [],
    )

    if not ranked_causes:
        return None

    top_cause = ranked_causes[0].get(
        "cause",
        "",
    )

    if not top_cause:
        return None

    normalized_cause = normalize_component(top_cause)

    matches: list[tuple[int, int, str]] = []

    for service in services:
        normalized_service = normalize_component(service)

        position = normalized_cause.find(normalized_service)

        if position == -1:
            continue

        matches.append(
            (
                position,
                -len(normalized_service),
                service,
            )
        )

    if not matches:
        return None

    matches.sort()

    return matches[0][2]


def load_records(
    path: Path,
) -> list[dict]:
    """Load JSONL evaluation records from one file."""
    records: list[dict] = []

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        for line_number, line in enumerate(
            file,
            start=1,
        ):
            line = line.strip()

            if not line:
                continue

            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} at line {line_number}") from exc

    return records


def discover_run_files(
    runs_dir: Path,
) -> list[Path]:
    """Return all JSONL evaluation files under runs/."""
    if not runs_dir.exists():
        raise FileNotFoundError(f"Runs directory does not exist: {runs_dir}")

    if not runs_dir.is_dir():
        raise NotADirectoryError(f"Expected directory: {runs_dir}")

    return sorted(runs_dir.glob("*.jsonl"))


def build_taxonomy(
    records: list[dict],
) -> tuple[
    dict[tuple[str, str], Counter],
    dict[str, Counter],
]:
    """
    Build:
    1. failure class counts by scenario + config
    2. blamed-component counts by config for failures only
    """
    classes_by_group: dict[
        tuple[str, str],
        Counter,
    ] = defaultdict(Counter)

    blamed_by_config: dict[
        str,
        Counter,
    ] = defaultdict(Counter)

    for record in records:
        scenario = record.get(
            "scenario",
            "unknown",
        )

        config = record.get(
            "config",
            "unknown",
        )

        classification = classify_run(record)

        classes_by_group[(scenario, config)][classification] += 1

        if classification in {
            "outranked",
            "absent",
        }:
            component = blamed_component(
                record,
                SERVICES,
            )

            blamed_by_config[config][component or "unknown"] += 1

    return (
        classes_by_group,
        blamed_by_config,
    )


def print_failure_table(
    classes_by_group: dict[
        tuple[str, str],
        Counter,
    ],
) -> None:
    print()
    print("## Failure taxonomy")
    print()

    print("| Scenario | Config | Runs | Correct | Outranked | Absent | No verdict | Error |")

    print("|---|---|---:|---:|---:|---:|---:|---:|")

    for scenario, config in sorted(classes_by_group):
        counts = classes_by_group[(scenario, config)]

        total = sum(counts[class_name] for class_name in FAILURE_CLASSES)

        print(
            f"| {scenario} "
            f"| {config} "
            f"| {total} "
            f"| {counts['correct']} "
            f"| {counts['outranked']} "
            f"| {counts['absent']} "
            f"| {counts['no_verdict']} "
            f"| {counts['error']} |"
        )


def print_blamed_component_table(
    blamed_by_config: dict[
        str,
        Counter,
    ],
) -> None:
    print()
    print("## Components blamed in failed runs")
    print()

    if not blamed_by_config:
        print("No outranked or absent failures found.")
        return

    configs = sorted(blamed_by_config)

    components = sorted({component for counts in blamed_by_config.values() for component in counts})

    header = "| Blamed component | " + " | ".join(configs) + " |"

    separator = "|---|" + "---:|" * len(configs)

    print(header)
    print(separator)

    for component in components:
        values = " | ".join(str(blamed_by_config[config][component]) for config in configs)

        print(f"| {component} | {values} |")


def print_run_details(
    records: list[dict],
) -> None:
    """
    Print individual failure classifications.

    Useful for manually checking a sample of classifications.
    """
    print()
    print("## Failed run details")
    print()

    print("| Run ID | Scenario | Config | Class | Rank | Blamed component |")

    print("|---|---|---|---|---:|---|")

    for record in records:
        classification = classify_run(record)

        if classification == "correct":
            continue

        component = None

        if classification in {
            "outranked",
            "absent",
        }:
            component = blamed_component(
                record,
                SERVICES,
            )

        rank = record.get("rank_position")

        rank_text = str(rank) if rank is not None else "-"

        print(
            f"| {record.get('run_id', 'unknown')} "
            f"| {record.get('scenario', 'unknown')} "
            f"| {record.get('config', 'unknown')} "
            f"| {classification} "
            f"| {rank_text} "
            f"| {component or '-'} |"
        )


def main() -> None:
    runs_dir = Path("runs")

    run_files = discover_run_files(runs_dir)

    if not run_files:
        raise SystemExit("No JSONL evaluation files found in runs/")

    records: list[dict] = []

    for path in run_files:
        records.extend(load_records(path))

    print(f"Files read: {len(run_files)}")

    print(f"Runs classified: {len(records)}")

    classes_by_group, blamed_by_config = build_taxonomy(records)

    print_failure_table(classes_by_group)

    print_blamed_component_table(blamed_by_config)

    print_run_details(records)


if __name__ == "__main__":
    main()
