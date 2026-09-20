"""Redis-backed result + semantic caching (Phase 6, docs/architecture.md §6:
"a Redis-backed semantic cache in front of the Research Agent's
search+retrieval step avoid re-paying for repeated sub-questions").

Lives in `services/`, not `memory/`: `docs/project-structure.md` scopes
`memory/` to the agents' own short/working/long-term memory layers (what an
agent "remembers" about a research run), which is a different concern from
caching expensive deterministic provider calls across *different* runs. This
is closer to `session_repository.py`'s job — infra a service depends on —
than to agent memory, so it sits alongside it.

Two cache shapes on one `CacheService` interface:
  * `get`/`set` — exact-key result cache (e.g. identical
    `ResearchRequest.question` + provider combo within a TTL).
  * `get_semantic`/`set_semantic` — embedding-keyed cache: looks up the
    nearest cached entry by cosine similarity against a threshold rather
    than requiring an exact key match, for the Researcher's search step
    (semantically similar sub-questions across different runs hit the same
    cached retrieval).

`RedisCacheService` uses `redis.asyncio` with a lazy client (constructing it
never opens a connection; only the first call does — same rule every other
provider seam in this codebase follows). `LocalCacheService` is an in-memory
fake so the test suite — and any dev environment without a running Redis —
never needs one.
"""

from __future__ import annotations

import json
import math
import time
import typing
from abc import ABC, abstractmethod
from dataclasses import dataclass

if typing.TYPE_CHECKING:
    from app.config.settings import Settings


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class CacheService(ABC):
    name: str = "abstract"

    @abstractmethod
    async def get(self, namespace: str, key: str) -> dict | None:
        """Exact-key lookup. `None` on miss or expiry."""
        raise NotImplementedError

    @abstractmethod
    async def set(self, namespace: str, key: str, value: dict, ttl_seconds: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_semantic(
        self, namespace: str, vector: list[float], threshold: float
    ) -> dict | None:
        """Nearest cached entry in `namespace` by cosine similarity, if any
        entry clears `threshold`. `None` on miss/expiry/no entries."""
        raise NotImplementedError

    @abstractmethod
    async def set_semantic(
        self, namespace: str, vector: list[float], value: dict, ttl_seconds: int
    ) -> None:
        raise NotImplementedError


@dataclass
class _Entry:
    value: dict
    expires_at: float


@dataclass
class _SemanticEntry:
    vector: list[float]
    value: dict
    expires_at: float


class LocalCacheService(CacheService):
    """In-memory fake: no network, deterministic, used by default in tests
    and any dev environment with `REDIS_URL` unset. Semantic lookup is a
    linear scan — fine at the scale a single process's test/dev cache holds,
    and the same brute-force approach `RedisCacheService` uses (Redis itself
    has no built-in vector index, see its docstring)."""

    name = "local"

    def __init__(self) -> None:
        self._exact: dict[str, _Entry] = {}
        self._semantic: dict[str, list[_SemanticEntry]] = {}

    async def get(self, namespace: str, key: str) -> dict | None:
        entry = self._exact.get(f"{namespace}:{key}")
        if entry is None or entry.expires_at < time.monotonic():
            return None
        return entry.value

    async def set(self, namespace: str, key: str, value: dict, ttl_seconds: int) -> None:
        self._exact[f"{namespace}:{key}"] = _Entry(
            value=value, expires_at=time.monotonic() + ttl_seconds
        )

    async def get_semantic(
        self, namespace: str, vector: list[float], threshold: float
    ) -> dict | None:
        now = time.monotonic()
        entries = [e for e in self._semantic.get(namespace, []) if e.expires_at >= now]
        self._semantic[namespace] = entries
        best: _SemanticEntry | None = None
        best_score = -1.0
        for entry in entries:
            score = _cosine_similarity(vector, entry.vector)
            if score > best_score:
                best, best_score = entry, score
        if best is not None and best_score >= threshold:
            return best.value
        return None

    async def set_semantic(
        self, namespace: str, vector: list[float], value: dict, ttl_seconds: int
    ) -> None:
        self._semantic.setdefault(namespace, []).append(
            _SemanticEntry(vector=vector, value=value, expires_at=time.monotonic() + ttl_seconds)
        )


class RedisCacheService(CacheService):
    """Real Redis-backed cache. The exact-key cache uses `SETEX`/`GET`
    directly. The semantic cache stores `{vector, value}` JSON blobs in a
    per-namespace Redis list (`RPUSH`, capped at `_SEMANTIC_MAX_ENTRIES`) and
    does the cosine-similarity comparison client-side after `LRANGE` —
    Redis has no built-in vector index without the RediSearch module, and
    pulling that in would be exactly the extra infra weight this MVP is
    avoiding (docs/architecture.md §5's "keep infra footprint small"
    rationale for Redis in the first place); a documented limitation, not an
    oversight, and fine at the per-namespace entry counts an MVP semantic
    cache actually holds."""

    name = "redis"
    _SEMANTIC_MAX_ENTRIES = 500

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: typing.Any | None = None

    def _get_client(self) -> typing.Any:
        if self._client is None:
            import redis.asyncio as redis

            self._client = redis.from_url(self._url, decode_responses=True)
        return self._client

    def get_client(self) -> typing.Any:
        """Public accessor so other Redis-backed seams (Phase 8's
        `app/security/rate_limit.py`) can reuse this instance's lazy client
        instead of opening a second Redis connection pool for the same
        `REDIS_URL`."""
        return self._get_client()

    async def get(self, namespace: str, key: str) -> dict | None:
        client = self._get_client()
        raw = await client.get(f"{namespace}:{key}")
        return json.loads(raw) if raw is not None else None

    async def set(self, namespace: str, key: str, value: dict, ttl_seconds: int) -> None:
        client = self._get_client()
        await client.set(f"{namespace}:{key}", json.dumps(value), ex=max(1, ttl_seconds))

    async def get_semantic(
        self, namespace: str, vector: list[float], threshold: float
    ) -> dict | None:
        client = self._get_client()
        list_key = f"semcache:{namespace}"
        now = time.time()
        raw_entries = await client.lrange(list_key, 0, -1)

        best_value: dict | None = None
        best_score = -1.0
        stale_count = 0
        for raw in raw_entries:
            entry = json.loads(raw)
            if entry["expires_at"] < now:
                stale_count += 1
                continue
            score = _cosine_similarity(vector, entry["vector"])
            if score > best_score:
                best_score, best_value = score, entry["value"]

        if stale_count:
            # Opportunistic cleanup, not required for correctness (expired
            # entries are simply skipped above): keeps the list from growing
            # unbounded when nothing ever re-reads a given namespace.
            await self._prune_expired(client, list_key, raw_entries, now)

        if best_value is not None and best_score >= threshold:
            return best_value
        return None

    async def set_semantic(
        self, namespace: str, vector: list[float], value: dict, ttl_seconds: int
    ) -> None:
        client = self._get_client()
        list_key = f"semcache:{namespace}"
        entry = json.dumps({"vector": vector, "value": value, "expires_at": time.time() + ttl_seconds})
        await client.rpush(list_key, entry)
        # Hard cap: never let one namespace's semantic cache grow without
        # bound (brief's "never allow infinite" rule applies to unbounded
        # growth too, not just retry loops).
        await client.ltrim(list_key, -self._SEMANTIC_MAX_ENTRIES, -1)

    async def _prune_expired(
        self, client: typing.Any, list_key: str, raw_entries: list[str], now: float
    ) -> None:
        fresh = [
            raw for raw in raw_entries if json.loads(raw)["expires_at"] >= now
        ]
        if len(fresh) == len(raw_entries):
            return
        async with client.pipeline(transaction=True) as pipe:
            pipe.delete(list_key)
            if fresh:
                pipe.rpush(list_key, *fresh)
            await pipe.execute()


def get_cache_service(settings: Settings) -> CacheService:
    """Factory selecting the configured backend, matching every other
    `get_*` provider seam's shape."""
    if settings.redis_url:
        return RedisCacheService(url=settings.redis_url)
    return LocalCacheService()
