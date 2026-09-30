import asyncio
import os
import random
import time
from collections.abc import Awaitable, Callable

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from opentelemetry.trace import Status, StatusCode

from rca_copilot.telemetry.tracing import tracer

MAX_ATTEMPTS = 3
BASE_DELAY = 1.0

# =================================================================
# Cost configuration
# =================================================================

MAX_TOKENS_PER_RUN = int(
    os.getenv(
        "MAX_TOKENS_PER_RUN",
        "400000",
    )
)

MAX_COST_PER_HOUR_USD = float(
    os.getenv(
        "MAX_COST_PER_HOUR_USD",
        "2.0",
    )
)

INPUT_COST_PER_MILLION_USD = float(
    os.getenv(
        "INPUT_COST_PER_MILLION_USD",
        "1.0",
    )
)

OUTPUT_COST_PER_MILLION_USD = float(
    os.getenv(
        "OUTPUT_COST_PER_MILLION_USD",
        "5.0",
    )
)

_hourly_costs: list[tuple[float, float]] = []


class ProviderUnavailableError(RuntimeError):
    """The LLM provider remained unavailable after retries."""

    def __init__(self, message: str, last_error: Exception) -> None:
        super().__init__(message)
        self.last_error = last_error


class ProviderAuthError(RuntimeError):
    """The LLM provider rejected configured credentials or permissions."""

    def __init__(self, message: str, last_error: Exception) -> None:
        super().__init__(message)
        self.last_error = last_error


def is_retryable(exc: Exception) -> bool:
    if isinstance(
        exc,
        (
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
        ),
    ):
        return True

    if isinstance(exc, APIStatusError):
        return exc.status_code >= 500

    return False


async def with_retries[T](
    call: Callable[[], Awaitable[T]],
    agent: str,
) -> T:
    for attempt_index in range(MAX_ATTEMPTS):
        attempt = attempt_index + 1
        delay: float | None = None

        with tracer.start_as_current_span("llm.attempt") as span:
            span.set_attribute("agent", agent)
            span.set_attribute("attempt", attempt)

            try:
                result = await call()

            except Exception as exc:
                retryable = is_retryable(exc)

                span.set_attribute("retryable", retryable)
                span.set_attribute("exception.type", type(exc).__name__)
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))

                if isinstance(
                    exc,
                    (
                        AuthenticationError,
                        PermissionDeniedError,
                    ),
                ):
                    raise ProviderAuthError(
                        "LLM provider rejected credentials or permissions",
                        exc,
                    ) from exc

                if not retryable:
                    raise

                if attempt == MAX_ATTEMPTS:
                    raise ProviderUnavailableError(
                        f"LLM provider unavailable after {MAX_ATTEMPTS} attempts",
                        exc,
                    ) from exc

                delay = BASE_DELAY * (2**attempt_index) * (0.5 + random.random())

                span.set_attribute("retry_delay_seconds", delay)

            else:
                span.set_attribute("retryable", False)
                span.set_attribute("outcome", "success")
                return result

        if delay is None:
            raise RuntimeError("Retryable failure reached backoff without a delay")

        await asyncio.sleep(delay)

    # Defensive guard. Normal control flow cannot reach this point.
    raise RuntimeError("Retry loop exited unexpectedly")


# =================================================================
# Per-run token ceiling
# =================================================================


class CostTracker:
    """
    Track token consumption for one RCA run.

    The per-run ceiling currently uses total token count rather than USD,
    keeping the runaway-agent protection independent of model pricing.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0

    def add(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def exceeded(self) -> bool:
        return self.total_tokens >= MAX_TOKENS_PER_RUN


# =================================================================
# Cost estimation
# =================================================================


def estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
) -> float:
    """
    Estimate base LLM cost from input and output token counts.

    Prompt-cache creation/read pricing is not included yet. The agents
    already capture those token counts and can add them when the cost
    accounting is wired into the agent loops.
    """
    input_cost = (input_tokens / 1_000_000) * INPUT_COST_PER_MILLION_USD

    output_cost = (output_tokens / 1_000_000) * OUTPUT_COST_PER_MILLION_USD

    return input_cost + output_cost


# =================================================================
# Hourly cost ceiling
# =================================================================


def _prune_hourly_costs() -> None:
    """Remove cost entries older than the rolling one-hour window."""
    cutoff = time.time() - 3600

    while _hourly_costs and _hourly_costs[0][0] < cutoff:
        _hourly_costs.pop(0)


def record_hourly_cost(
    usd: float,
) -> None:
    """Record completed LLM spend in the rolling hourly window."""
    _prune_hourly_costs()

    _hourly_costs.append(
        (
            time.time(),
            usd,
        )
    )


def hourly_cost_exceeded() -> bool:
    """Return whether the rolling hourly spend reached its ceiling."""
    _prune_hourly_costs()

    total = sum(cost for _, cost in _hourly_costs)

    return total >= MAX_COST_PER_HOUR_USD


# =================================================================
# Operational kill switch
# =================================================================


def is_disabled() -> bool:
    """
    Return whether RCA diagnosis has been administratively disabled.

    RCA_DISABLED=true prevents new model-backed diagnoses without
    requiring an application rebuild.
    """
    return (
        os.getenv(
            "RCA_DISABLED",
            "",
        ).lower()
        == "true"
    )
