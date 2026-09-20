"""Tests for the embedding provider abstraction (Phase 5 RAG,
`app/retrieval/embeddings.py`). Real `sentence-transformers` tests are
skipped if the package/model isn't available in this environment — the
`LocalEmbeddingProvider` tests are the ones the suite actually depends on."""

from __future__ import annotations

from app.config.settings import Settings
from app.retrieval.embeddings import (
    LocalEmbeddingProvider,
    SentenceTransformersProvider,
    get_embedding_provider,
)

try:
    import sentence_transformers  # noqa: F401

    _HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    _HAS_SENTENCE_TRANSFORMERS = False

import pytest


def test_constructing_providers_never_requires_a_model_load() -> None:
    """Lazy-init contract: importing this module / constructing a provider
    must never touch the network or load a model."""
    LocalEmbeddingProvider()
    SentenceTransformersProvider(model_name="not-a-real-model")


def test_factory_returns_local_by_default() -> None:
    provider = get_embedding_provider(Settings(embedding_provider="local"))
    assert isinstance(provider, LocalEmbeddingProvider)


def test_factory_returns_sentence_transformers() -> None:
    provider = get_embedding_provider(Settings(embedding_provider="sentence-transformers"))
    assert isinstance(provider, SentenceTransformersProvider)


async def test_local_provider_returns_fixed_dimension_vectors() -> None:
    provider = LocalEmbeddingProvider(dimension=384)
    vectors = await provider.embed(["hello world", "vector databases", ""])
    assert len(vectors) == 3
    assert all(len(v) == 384 for v in vectors)


async def test_local_provider_is_deterministic() -> None:
    provider = LocalEmbeddingProvider(dimension=32)
    v1 = await provider.embed_one("the same text")
    v2 = await provider.embed_one("the same text")
    assert v1 == v2


async def test_local_provider_distinct_texts_produce_distinct_vectors() -> None:
    provider = LocalEmbeddingProvider(dimension=32)
    v1 = await provider.embed_one("alpha")
    v2 = await provider.embed_one("beta")
    assert v1 != v2


async def test_local_provider_vectors_are_unit_normalized() -> None:
    import math

    provider = LocalEmbeddingProvider(dimension=64)
    vector = await provider.embed_one("normalize me")
    norm = math.sqrt(sum(x * x for x in vector))
    assert abs(norm - 1.0) < 1e-9


@pytest.mark.skipif(
    not _HAS_SENTENCE_TRANSFORMERS, reason="sentence-transformers not installed"
)
async def test_sentence_transformers_provider_real_model_fixed_dimension() -> None:
    """Only runs if the real model is installed/cached; otherwise skipped so
    the suite never depends on a network download."""
    provider = SentenceTransformersProvider(model_name="all-MiniLM-L6-v2", dimension=384)
    try:
        vectors = await provider.embed(["hello world", "vector databases"])
    except Exception as exc:  # noqa: BLE001 - model not cached/no network
        pytest.skip(f"sentence-transformers model unavailable: {exc}")
    assert len(vectors) == 2
    assert all(len(v) == 384 for v in vectors)
