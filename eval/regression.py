import subprocess
import sys

from opentelemetry import metrics

from rca_copilot.telemetry.metrics import record_regression_run, setup_metrics

RUNS_PER_SCENARIO = 5

BASELINE_THRESHOLDS = {
    "C1-valkey-cart-down": 0.50,
    "C2-cart-bad-config": 0.80,
    "C3-product-catalog-oom": 0.60,
    "C4-astronomy-db-down": 0.80,
}


def run_evaluation(
    scenario: str,
    config: str,
    min_accuracy: float | None = None,
) -> int:
    command = [
        sys.executable,
        "-m",
        "eval.harness",
        scenario,
        "--config",
        config,
        "--n",
        str(RUNS_PER_SCENARIO),
    ]

    if min_accuracy is not None:
        command.extend(["--min-accuracy", str(min_accuracy)])

    print()
    print("=" * 70)
    print(f"Running {config}: {scenario}")
    print("=" * 70)

    result = subprocess.run(command, check=False)
    return result.returncode


def main() -> None:
    setup_metrics()

    # Production regression gate.
    for scenario, threshold in BASELINE_THRESHOLDS.items():
        return_code = run_evaluation(
            scenario=scenario,
            config="baseline",
            min_accuracy=threshold,
        )

        if return_code != 0:
            record_regression_run("fail")
            metrics.get_meter_provider().force_flush()

            raise SystemExit(f"Baseline regression failed for: {scenario}")

    # Experimental configuration runs only when baseline passes.
    for scenario in BASELINE_THRESHOLDS:
        run_evaluation(
            scenario=scenario,
            config="multi_agent",
        )

    record_regression_run("pass")
    metrics.get_meter_provider().force_flush()

    print()
    print("Baseline regression gate passed.")


if __name__ == "__main__":
    main()
