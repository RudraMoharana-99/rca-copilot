import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from time import perf_counter
from uuid import uuid4

import yaml
from anthropic import Anthropic, AsyncAnthropic
from dotenv import load_dotenv

from eval.scoring import score_verdict
from rca_copilot.agents.adjudicator import MODEL as ADJUDICATOR_MODEL
from rca_copilot.agents.baseline import MODEL as BASELINE_MODEL
from rca_copilot.agents.baseline import run_baseline
from rca_copilot.agents.graph import run_graph
from rca_copilot.agents.investigators import MODEL as INVESTIGATOR_MODEL
from rca_copilot.agents.tools import SourceBundle
from rca_copilot.models import RankedCause, Verdict
from rca_copilot.sources.changelog import SnapshotChangesSource
from rca_copilot.sources.snapshot import (
    SnapshotLogsSource,
    SnapshotMetricsSource,
    SnapshotTracesSource,
)

# Claude Haiku 4.5 standard API pricing, USD per 1M tokens.
INPUT_PRICE = 1.00
OUTPUT_PRICE = 5.00
CACHE_WRITE_PRICE = 1.25
CACHE_READ_PRICE = 0.10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RCA evaluation scenarios")

    parser.add_argument(
        "scenario",
        help="Scenario folder name, for example C1-valkey-cart-down.",
    )

    parser.add_argument(
        "--config",
        choices=["baseline", "multi_agent"],
        default="multi_agent",
        help="RCA configuration to evaluate.",
    )

    parser.add_argument(
        "--n",
        type=int,
        default=3,
        help="Number of repeated runs.",
    )

    return parser.parse_args()


def load_scenario(name: str) -> tuple[Path, dict, datetime, datetime]:
    scenario_dir = Path("scenarios") / name
    scenario_file = scenario_dir / "scenario.yaml"

    if not scenario_file.exists():
        raise FileNotFoundError(f"Scenario not found: {scenario_file}")
    with open(scenario_file, encoding="utf-8") as f:
        scenario = yaml.safe_load(f)

    window_start = scenario["window"]["start"]
    window_end = scenario["window"]["end"]

    return (scenario_dir, scenario, window_start, window_end)


def baseline_to_verdict(state) -> Verdict | None:
    if not state.hypotheses:
        return None
    hypothesis = state.hypotheses[0]

    ranked_cause = RankedCause(
        cause=hypothesis.cause,
        confidence=hypothesis.confidence,
        evidence_ids=hypothesis.evidence_ids,
    )

    return Verdict(
        ranked_causes=[ranked_cause],
        overall_confidence=hypothesis.confidence,
        dissent=None,
        escalate=False,
        escalation_reason=None,
    )


def aggregate_usage(
    run_metas: list[dict],
) -> dict:
    return {
        "input_tokens": sum(meta.get("input_tokens", 0) for meta in run_metas),
        "output_tokens": sum(meta.get("output_tokens", 0) for meta in run_metas),
        "cache_creation_tokens": sum(meta.get("cache_creation_tokens", 0) for meta in run_metas),
        "cache_read_tokens": sum(meta.get("cache_read_tokens", 0) for meta in run_metas),
    }


def calculate_costs(usage: dict) -> float:
    input_cost = usage["input_tokens"] / 1_000_000 * INPUT_PRICE

    output_cost = usage["output_tokens"] / 1_000_000 * OUTPUT_PRICE

    cache_write_cost = usage["cache_creation_tokens"] / 1_000_000 * CACHE_WRITE_PRICE

    cache_read_cost = usage["cache_read_tokens"] / 1_000_000 * CACHE_READ_PRICE
    return input_cost + output_cost + cache_write_cost + cache_read_cost


def verdict_to_text(
    verdict: Verdict | None,
) -> str | None:
    if verdict is None:
        return None

    lines = []

    for index, cause in enumerate(
        verdict.ranked_causes,
        start=1,
    ):
        lines.append(f"{index}. [{cause.confidence:.2f}] {cause.cause}")

    return "\n".join(lines)


def append_record(
    path: Path,
    record: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
    ) as file:
        file.write(json.dumps(record, ensure_ascii=False))
        file.write("\n")


async def main() -> None:
    args = parse_args()

    if args.n < 1:
        raise SystemExit("--n must be atleast 1")

    load_dotenv()

    (scenario_dir, scenario, window_start, window_end) = load_scenario(args.scenario)

    expected_component = scenario["expected_component"]
    # Keep the alert identical across configurations.
    alert = scenario.get(
        "alert",
        {
            "message": "elevated error rate detected",
        },
    )

    sources = SourceBundle(
        logs=SnapshotLogsSource(scenario_dir),
        metrics=SnapshotMetricsSource(scenario_dir),
        traces=SnapshotTracesSource(scenario_dir),
        changelog=SnapshotChangesSource("scenarios/_changelog_master.json"),
    )
    api_key = os.environ["ANTHROPIC_API_KEY"]

    if args.config == "baseline":
        client = Anthropic(api_key=api_key)
        model = BASELINE_MODEL
    else:
        client = AsyncAnthropic(api_key=api_key)
        model = f"investigator={INVESTIGATOR_MODEL};adjudicator={ADJUDICATOR_MODEL}"

    output_path = Path("runs") / f"{args.scenario}_{args.config}.jsonl"
    records: list[dict] = []

    print(f"Scenario: {args.scenario}")
    print(f"Config:   {args.config}")
    print(f"Runs:     {args.n}")
    print(f"Output:   {output_path}")
    print()

    for number in range(1, args.n + 1):
        started = perf_counter()
        verdict = None

        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }
        error = None

        try:
            if args.config == "multi_agent":
                state = await run_graph(
                    alert=alert,
                    window_start=window_start,
                    window_end=window_end,
                    sources=sources,
                    client=client,
                )
                verdict = state["verdict"]
                usage = aggregate_usage(state["run_metas"])

            else:
                state = run_baseline(
                    alert=alert,
                    window_start=window_start,
                    window_end=window_end,
                    sources=sources,
                    client=client,
                )
                verdict = baseline_to_verdict(state)
                usage = aggregate_usage([state.run_meta])
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        elapsed_seconds = perf_counter() - started
        score = score_verdict(verdict=verdict, expected_component=expected_component)
        cost_usd = calculate_costs(usage=usage)

        record = {
            "run_id": uuid4().hex[:8],
            "scenario": args.scenario,
            "config": args.config,
            "model": model,
            "timestamp": datetime.now(UTC).isoformat(),
            **score,
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cache_creation_tokens": usage["cache_creation_tokens"],
            "cache_read_tokens": usage["cache_read_tokens"],
            "elapsed_seconds": (elapsed_seconds),
            "cost_usd": cost_usd,
            "verdict_text": (verdict_to_text(verdict)),
            # Keeping the structured form too makes
            # future re-scoring easier.
            "verdict": (verdict.model_dump(mode="json") if verdict is not None else None),
            "error": error,
        }

        # Persist immediately.
        append_record(output_path, record)

        records.append(record)
        status = "PASS" if record["correct"] else "FAIL"

        print(
            f"[{number}/{args.n}] "
            f"{status} "
            f"rank={record['rank_position']} "
            f"time={elapsed_seconds:.1f}s "
            f"cost=${cost_usd:.4f}"
        )
        if error:
            print(f"    error={error}")

    print_summary(records)


def print_summary(records: list[dict]) -> None:
    total_runs = len(records)

    correct_count = sum(1 for record in records if record["correct"])

    errors = sum(1 for record in records if record["error"] is not None)

    confidences = [
        record["top_confidence"] for record in records if record["top_confidence"] is not None
    ]
    elapsed_values = [record["elapsed_seconds"] for record in records]
    total_input = sum(record["input_tokens"] for record in records)
    total_output = sum(record["output_tokens"] for record in records)

    total_cache_created = sum(record["cache_creation_tokens"] for record in records)

    total_cache_read = sum(record["cache_read_tokens"] for record in records)

    total_cost = sum(record["cost_usd"] for record in records)

    accuracy = correct_count / total_runs if total_runs else 0

    mean_confidence = fmean(confidences) if confidences else None

    mean_elapsed = fmean(elapsed_values) if elapsed_values else 0

    print()
    print("=" * 60)
    print("Evaluation summary")
    print("=" * 60)
    print(f"Correct:          {correct_count}/{total_runs} ({accuracy:.1%})")
    print(f"Errors:           {errors}/{total_runs}")

    if mean_confidence is None:
        print("Mean confidence:  n/a")
    else:
        print(f"Mean confidence:  {mean_confidence:.3f}")

    print(f"Mean elapsed:     {mean_elapsed:.1f}s")

    print(f"Input tokens:     {total_input:,}")

    print(f"Output tokens:    {total_output:,}")

    print(f"Cache created:    {total_cache_created:,}")

    print(f"Cache read:       {total_cache_read:,}")

    print(f"Estimated cost:   ${total_cost:.4f}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
