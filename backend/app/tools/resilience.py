"""Retry + circuit-breaker helpers for real external calls (brief §26:
timeout, rate limits, provider unavailable; docs/architecture.md §7's
bounded-retry rule for invalid LLM JSON reuses the same "never infinite"
principle).

Only wraps providers that hit a real network service (`OpenAIProvider`,
`AnthropicProvider`, `TavilyProvider`, `SentenceTransformersProvider`,
`QdrantVectorStore`). The `Local*`/in-memory fakes never call this — they
must stay fast and deterministic so the test suite doesn't need a running
Redis/Qdrant/network to pass.

Built on `tenacity` (already a transitive dependency via langchain-core, now
declared directly — see `pyproject.toml`) rather than a hand-rolled loop, per
the brief's "fine to use tenacity instead of hand-rolling" allowance. Every
retry loop is hard-capped by `max_attempts`; there is no infinite-retry path
anywhere in this module.
"""

from __future__ import annotations

import time
import typing
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeVar

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

if typing.TYPE_CHECKING:
    from app.config.settings import Settings

T = TypeVar("T")


@dataclass(frozen=True)
class ResilienceConfig:
    """Bundles the `with_retry`/`CircuitBreaker` knobs so every real
    provider's `__init__` takes one config object (config, never hardcoded
    in agent/provider code — same rule `Settings.source_scoring_weights()`
    etc. already follow) instead of five separate constructor params."""

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    circuit_failure_threshold: int = 5
    circuit_reset_seconds: float = 30.0

    @classmethod
    def from_settings(cls, settings: Settings) -> ResilienceConfig:
        return cls(
            max_attempts=settings.resilience_max_attempts,
            base_delay=settings.resilience_base_delay_seconds,
            max_delay=settings.resilience_max_delay_seconds,
            circuit_failure_threshold=settings.resilience_circuit_failure_threshold,
            circuit_reset_seconds=settings.resilience_circuit_reset_seconds,
        )

    def new_breaker(self) -> CircuitBreaker:
        return CircuitBreaker(
            failure_threshold=self.circuit_failure_threshold,
            reset_timeout_seconds=self.circuit_reset_seconds,
        )


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised instead of attempting a call while a breaker is open."""


@dataclass
class CircuitBreaker:
    """Per-provider-instance circuit breaker (construct one per provider
    object, not shared globally — see each provider's `__init__`).

    `failure_threshold` consecutive failures opens the circuit; after
    `reset_timeout_seconds` the next call is let through in the half-open
    state, and a single success or failure decides whether it closes again
    or reopens.
    """

    failure_threshold: int = 5
    reset_timeout_seconds: float = 30.0
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False, repr=False)
    _consecutive_failures: int = field(default=0, init=False, repr=False)
    _opened_at: float | None = field(default=None, init=False, repr=False)

    @property
    def state(self) -> CircuitState:
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self.reset_timeout_seconds:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def before_call(self) -> None:
        if self.state is CircuitState.OPEN:
            raise CircuitOpenError(
                f"circuit breaker open ({self._consecutive_failures} consecutive failures); "
                "call rejected without hitting the provider"
            )

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._state is CircuitState.HALF_OPEN or self._consecutive_failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    breaker: CircuitBreaker | None = None,
) -> T:
    """Run `fn()`, retrying on `retry_on` exceptions with exponential
    backoff + jitter, hard-capped at `max_attempts` (never infinite). If
    `breaker` is given: its state is checked once up front (an open breaker
    fails fast, consuming none of the retry budget), and each attempt
    records success/failure so repeated failures across separate
    `with_retry` calls eventually open it.

    Tests pass tiny `base_delay`/`max_delay` to keep this fast without
    mocking time.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if breaker is not None:
        breaker.before_call()

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_random_exponential(multiplier=base_delay, max=max_delay),
        retry=retry_if_exception_type(retry_on),
        reraise=True,
    ):
        with attempt:
            try:
                result = await fn()
            except Exception:
                if breaker is not None:
                    breaker.record_failure()
                raise
            if breaker is not None:
                breaker.record_success()
            return result

    # Unreachable: AsyncRetrying either returns via the `with` block above or
    # re-raises (reraise=True) once `max_attempts` is exhausted.
    raise RuntimeError("with_retry exhausted without a result or a re-raised exception")
