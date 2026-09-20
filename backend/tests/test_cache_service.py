from __future__ import annotations

import asyncio

from app.services.cache_service import LocalCacheService


async def test_local_cache_miss_then_hit() -> None:
    cache = LocalCacheService()
    assert await cache.get("ns", "k1") is None

    await cache.set("ns", "k1", {"answer": 42}, ttl_seconds=60)
    assert await cache.get("ns", "k1") == {"answer": 42}


async def test_local_cache_respects_namespace() -> None:
    cache = LocalCacheService()
    await cache.set("ns-a", "same-key", {"v": "a"}, ttl_seconds=60)
    await cache.set("ns-b", "same-key", {"v": "b"}, ttl_seconds=60)

    assert await cache.get("ns-a", "same-key") == {"v": "a"}
    assert await cache.get("ns-b", "same-key") == {"v": "b"}


async def test_local_cache_expires_after_ttl() -> None:
    cache = LocalCacheService()
    await cache.set("ns", "k1", {"answer": 42}, ttl_seconds=0)
    # A zero/near-zero TTL should already be expired on the very next check.
    await asyncio.sleep(0.01)
    assert await cache.get("ns", "k1") is None


async def test_semantic_cache_hits_above_threshold() -> None:
    cache = LocalCacheService()
    vector = [1.0, 0.0, 0.0]
    await cache.set_semantic("kb", vector, {"result": "cached"}, ttl_seconds=60)

    # Near-identical vector (small perturbation) should still match at a
    # reasonable threshold.
    near_duplicate = [0.99, 0.05, 0.0]
    hit = await cache.get_semantic("kb", near_duplicate, threshold=0.9)
    assert hit == {"result": "cached"}


async def test_semantic_cache_misses_below_threshold() -> None:
    cache = LocalCacheService()
    await cache.set_semantic("kb", [1.0, 0.0, 0.0], {"result": "cached"}, ttl_seconds=60)

    orthogonal = [0.0, 1.0, 0.0]
    miss = await cache.get_semantic("kb", orthogonal, threshold=0.9)
    assert miss is None


async def test_semantic_cache_expires_after_ttl() -> None:
    cache = LocalCacheService()
    await cache.set_semantic("kb", [1.0, 0.0, 0.0], {"result": "cached"}, ttl_seconds=0)
    await asyncio.sleep(0.01)
    assert await cache.get_semantic("kb", [1.0, 0.0, 0.0], threshold=0.5) is None


async def test_semantic_cache_empty_namespace_is_a_miss() -> None:
    cache = LocalCacheService()
    assert await cache.get_semantic("never-populated", [1.0, 0.0], threshold=0.1) is None
