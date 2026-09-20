"""Per-user token-bucket rate limiting (Phase 8, brief §14/§27,
docs/api.md "Auth & rate limiting": "Rate limits enforced per user at the
API layer (Redis token bucket); research creation is the expensive endpoint
and gets the tightest limit.").

Reuses `RedisCacheService`'s lazy `redis.asyncio` client (via
`RedisCacheService.get_client()`) rather than adding a second Redis
dependency, matching `CacheService`'s existing
Redis-backend-with-in-memory-fallback pattern exactly: `InMemoryRateLimiter`
is what tests and any dev environment without Redis actually run against.
"""

from __future__ import annotations

import asyncio
import time
import typing
from abc import ABC, abstractmethod

if typing.TYPE_CHECKING:
    from app.services.cache_service import CacheService


class RateLimiter(ABC):
    name: str = "abstract"

    @abstractmethod
    async def allow(self, key: str, *, capacity: int, refill_per_second: float) -> bool:
        """Try to take one token from `key`'s bucket. Returns True if the
        request may proceed, False if the bucket is exhausted."""
        raise NotImplementedError


class InMemoryRateLimiter(RateLimiter):
    """In-memory token bucket, one per process. Used whenever no Redis is
    configured (offline dev/tests), same fallback role `LocalCacheService`
    plays for `CacheService`. Accepts an injectable clock so unit tests can
    exercise refill without real sleeps."""

    name = "local"

    def __init__(self, clock: typing.Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_refill_ts)
        self._lock = asyncio.Lock()

    async def allow(self, key: str, *, capacity: int, refill_per_second: float) -> bool:
        async with self._lock:
            now = self._clock()
            tokens, last_ts = self._buckets.get(key, (float(capacity), now))
            elapsed = max(0.0, now - last_ts)
            tokens = min(float(capacity), tokens + elapsed * refill_per_second)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True


# Atomic Redis-side token bucket: read-refill-decrement-write all happen in
# one EVAL so concurrent requests from the same user can't race each other
# into both reading the same starting token count (the failure mode a naive
# GET-then-SET implementation would have).
_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_second = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * refill_per_second)

local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, 3600)
return allowed
"""


class RedisRateLimiter(RateLimiter):
    """Real Redis-backed token bucket via a Lua script for atomicity."""

    name = "redis"

    def __init__(self, client: typing.Any) -> None:
        self._client = client

    async def allow(self, key: str, *, capacity: int, refill_per_second: float) -> bool:
        result = await self._client.eval(
            _TOKEN_BUCKET_LUA, 1, f"ratelimit:{key}", capacity, refill_per_second, time.time()
        )
        return bool(int(result))


def get_rate_limiter(cache: CacheService) -> RateLimiter:
    """Factory mirroring `get_cache_service`'s shape: reuse the Redis client
    already backing `cache` when one exists, otherwise fall back to an
    in-memory limiter (offline dev/tests)."""
    from app.services.cache_service import RedisCacheService

    if isinstance(cache, RedisCacheService):
        return RedisRateLimiter(cache.get_client())
    return InMemoryRateLimiter()
