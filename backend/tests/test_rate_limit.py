"""Unit tests for the Phase 8 token-bucket rate limiter
(`app/security/rate_limit.py`). Uses `InMemoryRateLimiter` with an
injectable clock so refill can be exercised without real sleeps."""

from __future__ import annotations

from app.security.rate_limit import InMemoryRateLimiter


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def test_allows_up_to_capacity_then_blocks() -> None:
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)

    for _ in range(3):
        assert await limiter.allow("user-1", capacity=3, refill_per_second=0.0) is True

    assert await limiter.allow("user-1", capacity=3, refill_per_second=0.0) is False


async def test_bucket_refills_over_time() -> None:
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)

    for _ in range(2):
        assert await limiter.allow("user-1", capacity=2, refill_per_second=1.0) is True
    assert await limiter.allow("user-1", capacity=2, refill_per_second=1.0) is False

    clock.advance(1.0)  # one token refilled
    assert await limiter.allow("user-1", capacity=2, refill_per_second=1.0) is True
    assert await limiter.allow("user-1", capacity=2, refill_per_second=1.0) is False


async def test_bucket_never_exceeds_capacity_after_long_idle() -> None:
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)
    await limiter.allow("user-1", capacity=2, refill_per_second=1.0)  # tokens: 1

    clock.advance(1000.0)  # far more than enough to overfill if uncapped
    assert await limiter.allow("user-1", capacity=2, refill_per_second=1.0) is True
    assert await limiter.allow("user-1", capacity=2, refill_per_second=1.0) is True
    assert await limiter.allow("user-1", capacity=2, refill_per_second=1.0) is False


async def test_buckets_are_independent_per_key() -> None:
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)

    assert await limiter.allow("user-a", capacity=1, refill_per_second=0.0) is True
    assert await limiter.allow("user-a", capacity=1, refill_per_second=0.0) is False
    # A different key's bucket is untouched by user-a's exhaustion.
    assert await limiter.allow("user-b", capacity=1, refill_per_second=0.0) is True
