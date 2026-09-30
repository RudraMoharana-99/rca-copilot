from unittest.mock import Mock

import pytest
from anthropic import (
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from rca_copilot.agents import resilience
from rca_copilot.agents.resilience import (
    CostTracker,
    ProviderAuthError,
    ProviderUnavailableError,
    with_retries,
)


def make_status_error(
    error_type,
    status_code: int,
):
    request = Mock()

    response = Mock()
    response.request = request
    response.status_code = status_code
    response.headers = {}

    return error_type(
        "test error",
        response=response,
        body=None,
    )


@pytest.mark.asyncio
async def test_non_retryable_fails_immediately():
    attempts = 0

    async def call():
        nonlocal attempts
        attempts += 1

        raise make_status_error(
            BadRequestError,
            400,
        )

    with pytest.raises(BadRequestError):
        await with_retries(
            call,
            agent="test",
        )

    assert attempts == 1


@pytest.mark.asyncio
async def test_retryable_retries_then_succeeds(
    monkeypatch,
):
    monkeypatch.setattr(
        resilience,
        "BASE_DELAY",
        0.001,
    )

    attempts = 0

    async def call():
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            raise make_status_error(
                RateLimitError,
                429,
            )

        return "success"

    result = await with_retries(
        call,
        agent="test",
    )

    assert result == "success"
    assert attempts == 2


@pytest.mark.asyncio
async def test_exhausted_retries_raise_provider_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(
        resilience,
        "BASE_DELAY",
        0.001,
    )

    attempts = 0
    request = Mock()

    async def call():
        nonlocal attempts
        attempts += 1

        raise APITimeoutError(request)

    with pytest.raises(ProviderUnavailableError):
        await with_retries(
            call,
            agent="test",
        )

    assert attempts == resilience.MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_auth_error_raises_provider_auth_error():
    attempts = 0

    async def call():
        nonlocal attempts
        attempts += 1

        raise make_status_error(
            AuthenticationError,
            401,
        )

    with pytest.raises(ProviderAuthError):
        await with_retries(
            call,
            agent="test",
        )

    assert attempts == 1


def test_cost_tracker_exceeds_at_boundary(
    monkeypatch,
):
    monkeypatch.setattr(
        resilience,
        "MAX_TOKENS_PER_RUN",
        10,
    )

    tracker = CostTracker()

    tracker.add(
        input_tokens=7,
        output_tokens=2,
    )

    assert tracker.total_tokens == 9
    assert not tracker.exceeded()

    tracker.add(
        input_tokens=1,
        output_tokens=0,
    )

    assert tracker.total_tokens == 10
    assert tracker.exceeded()
