import argparse
import json
from pathlib import Path
from statistics import fmean


def load_records(path: Path) -> list[dict]:
    records = []

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            records.append(json.loads(line))

    return records


def summarize(records: list[dict]) -> dict:
    total_runs = len(records)

    error_records = [record for record in records if record.get("error") is not None]

    valid_records = [record for record in records if record.get("error") is None]

    valid_runs = len(valid_records)
    errors = len(error_records)

    if total_runs == 0:
        return {
            "runs": 0,
            "valid_runs": 0,
            "correct": 0,
            "accuracy": None,
            "errors": 0,
            "mean_confidence": None,
            "mean_elapsed": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_cost": 0.0,
            "mean_cost": None,
        }

    correct = sum(1 for record in valid_records if record.get("correct") is True)

    confidences = [
        record["top_confidence"]
        for record in valid_records
        if record.get("top_confidence") is not None
    ]

    elapsed = [
        record["elapsed_seconds"]
        for record in valid_records
        if record.get("elapsed_seconds") is not None
    ]

    total_cost = sum(record.get("cost_usd", 0.0) for record in valid_records)

    return {
        "runs": total_runs,
        "valid_runs": valid_runs,
        "correct": correct,
        "accuracy": (correct / valid_runs if valid_runs > 0 else None),
        "errors": errors,
        "mean_confidence": (fmean(confidences) if confidences else None),
        "mean_elapsed": (fmean(elapsed) if elapsed else None),
        "input_tokens": sum(record.get("input_tokens", 0) for record in valid_records),
        "output_tokens": sum(record.get("output_tokens", 0) for record in valid_records),
        "total_cost": total_cost,
        "mean_cost": (total_cost / valid_runs if valid_runs > 0 else None),
    }


def discover_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []

    for value in paths:
        path = Path(value)

        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))

        elif path.is_file() and path.suffix == ".jsonl":
            files.append(path)

        else:
            raise FileNotFoundError(f"JSONL file or directory not found: {path}")

    return files


def summarize_file(path: Path) -> dict:
    records = load_records(path)

    if not records:
        return {
            "scenario": path.stem,
            "config": "unknown",
            **summarize(records),
        }

    summary = summarize(records)

    return {
        "scenario": records[0].get(
            "scenario",
            path.stem,
        ),
        "config": records[0].get(
            "config",
            "unknown",
        ),
        **summary,
    }


def print_comparison_table(
    summaries: list[dict],
) -> None:
    print()

    print(
        "| Scenario | Config | Runs | Valid | Correct | "
        "Accuracy | Errors | Mean confidence | "
        "Mean latency | Mean cost/run | Total cost |"
    )

    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    for item in summaries:
        confidence = (
            f"{item['mean_confidence']:.3f}" if item["mean_confidence"] is not None else "n/a"
        )

        latency = f"{item['mean_elapsed']:.1f}s" if item["mean_elapsed"] is not None else "n/a"

        mean_cost = f"${item['mean_cost']:.4f}" if item["mean_cost"] is not None else "n/a"

        accuracy = f"{item['accuracy']:.1%}" if item["accuracy"] is not None else "n/a"

        correct = f"{item['correct']}/{item['valid_runs']}" if item["valid_runs"] > 0 else "0/0"

        print(
            f"| {item['scenario']} "
            f"| {item['config']} "
            f"| {item['runs']} "
            f"| {item['valid_runs']} "
            f"| {correct} "
            f"| {accuracy} "
            f"| {item['errors']} "
            f"| {confidence} "
            f"| {latency} "
            f"| {mean_cost} "
            f"| ${item['total_cost']:.4f} |"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Summarize RCA evaluation JSONL files or all JSONL files in a directory.")
    )

    parser.add_argument(
        "paths",
        nargs="+",
        help=("One or more JSONL files or directories containing evaluation run files."),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    files = discover_files(args.paths)

    if not files:
        raise SystemExit("No JSONL evaluation files found.")

    summaries = [summarize_file(path) for path in files]

    print_comparison_table(summaries)


if __name__ == "__main__":
    main()
