from __future__ import annotations

import asyncio

import pytest

from app.tools.resilience import CircuitBreaker, CircuitOpenError, CircuitState, with_retry


class _FlakyFailure(RuntimeError):
    pass


def _make_flaky(fail_times: int):
    """Returns an async callable that fails `fail_times` times, then
    succeeds, and tracks how many times it was actually called."""
    calls = {"count": 0}

    async def flaky() -> str:
        calls["count"] += 1
        if calls["count"] <= fail_times:
            raise _FlakyFailure(f"attempt {calls['count']} failed")
        return "ok"

    return flaky, calls


async def test_with_retry_succeeds_after_transient_failures() -> None:
    flaky, calls = _make_flaky(fail_times=2)

    result = await with_retry(flaky, max_attempts=5, base_delay=0.001, max_delay=0.002)

    assert result == "ok"
    assert calls["count"] == 3  # 2 failures + 1 success


async def test_with_retry_gives_up_after_max_attempts() -> None:
    flaky, calls = _make_flaky(fail_times=10)  # always fails within the attempt budget

    with pytest.raises(_FlakyFailure):
        await with_retry(flaky, max_attempts=4, base_delay=0.001, max_delay=0.002)

    # Never exceeds the hard cap — no infinite retry loop.
    assert calls["count"] == 4


async def test_with_retry_rejects_nonpositive_max_attempts() -> None:
    async def noop() -> None:
        return None

    with pytest.raises(ValueError):
        await with_retry(noop, max_attempts=0)


async def test_with_retry_only_retries_matching_exception_types() -> None:
    async def raises_type_error() -> None:
        raise TypeError("not retryable here")

    with pytest.raises(TypeError):
        await with_retry(
            raises_type_error,
            max_attempts=5,
            base_delay=0.001,
            max_delay=0.002,
            retry_on=(_FlakyFailure,),
        )


async def test_circuit_breaker_opens_after_failure_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=60)
    assert breaker.state is CircuitState.CLOSED

    for _ in range(3):
        breaker.record_failure()

    assert breaker.state is CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.before_call()


async def test_circuit_breaker_half_opens_after_cooldown() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.02)
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN

    await asyncio.sleep(0.03)
    assert breaker.state is CircuitState.HALF_OPEN


async def test_circuit_breaker_closes_on_success_after_half_open() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.01)
    breaker.record_failure()
    await asyncio.sleep(0.02)
    assert breaker.state is CircuitState.HALF_OPEN

    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED


async def test_circuit_breaker_reopens_on_failure_during_half_open() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.01)
    breaker.record_failure()
    await asyncio.sleep(0.02)
    assert breaker.state is CircuitState.HALF_OPEN  # side effect: flips internal state

    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN


async def test_with_retry_wires_up_breaker_success_and_failure() -> None:
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_seconds=60)
    flaky, _ = _make_flaky(fail_times=0)

    await with_retry(flaky, max_attempts=2, base_delay=0.001, max_delay=0.002, breaker=breaker)
    assert breaker.state is CircuitState.CLOSED

    async def always_fails() -> None:
        raise _FlakyFailure("boom")

    for _ in range(2):
        with pytest.raises(_FlakyFailure):
            await with_retry(
                always_fails, max_attempts=1, base_delay=0.001, max_delay=0.002, breaker=breaker
            )

    assert breaker.state is CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        await with_retry(always_fails, max_attempts=1, breaker=breaker)
