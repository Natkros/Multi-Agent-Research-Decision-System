"""Tests for the vector store abstraction (Phase 5 RAG,
`app/retrieval/vector_store.py`). `InMemoryVectorStore` is the one exercised
directly (no running Qdrant instance in this environment); `QdrantVectorStore`
is checked only for lazy construction."""

from __future__ import annotations

from app.config.settings import Settings
from app.retrieval.vector_store import (
    ChunkMetadata,
    InMemoryVectorStore,
    QdrantVectorStore,
    VectorRecord,
    get_vector_store,
)


def _record(chunk_id: str, vector: list[float], *, document_type: str = "internal_kb", text: str = "") -> VectorRecord:
    return VectorRecord(
        id=chunk_id,
        text=text or f"text for {chunk_id}",
        vector=vector,
        metadata=ChunkMetadata(
            document_id="doc-1",
            chunk_id=chunk_id,
            source="test",
            title="Test Doc",
            document_type=document_type,
        ),
    )


def test_factory_returns_in_memory_by_default() -> None:
    store = get_vector_store(Settings(qdrant_url=None))
    assert isinstance(store, InMemoryVectorStore)


def test_factory_returns_qdrant_when_url_set() -> None:
    store = get_vector_store(Settings(qdrant_url="http://localhost:6333"))
    assert isinstance(store, QdrantVectorStore)


def test_constructing_qdrant_store_never_opens_a_connection() -> None:
    # Lazy-init contract: constructing must not require a running Qdrant.
    QdrantVectorStore(url="http://localhost:6333")


async def test_upsert_and_query_returns_nearest_neighbors_in_order() -> None:
    store = InMemoryVectorStore()
    await store.upsert(
        [
            _record("a", [1.0, 0.0, 0.0]),
            _record("b", [0.9, 0.1, 0.0]),
            _record("c", [0.0, 1.0, 0.0]),
            _record("d", [-1.0, 0.0, 0.0]),
        ]
    )

    results = await store.query([1.0, 0.0, 0.0], top_k=3)

    assert [r.record.id for r in results] == ["a", "b", "c"]
    assert results[0].score > results[1].score > results[2].score
    # Exact match should score (near) 1.0 cosine similarity.
    assert results[0].score > 0.99


async def test_query_respects_top_k() -> None:
    store = InMemoryVectorStore()
    await store.upsert([_record(f"c{i}", [float(i), 0.0]) for i in range(10)])

    results = await store.query([5.0, 0.0], top_k=2)
    assert len(results) == 2


async def test_query_applies_metadata_filters() -> None:
    store = InMemoryVectorStore()
    await store.upsert(
        [
            _record("blog-1", [1.0, 0.0], document_type="blog"),
            _record("kb-1", [1.0, 0.0], document_type="internal_kb"),
        ]
    )

    results = await store.query([1.0, 0.0], top_k=10, filters={"document_type": "internal_kb"})

    assert [r.record.id for r in results] == ["kb-1"]


async def test_upsert_is_idempotent_replace_by_id() -> None:
    store = InMemoryVectorStore()
    await store.upsert([_record("x", [1.0, 0.0], text="first version")])
    await store.upsert([_record("x", [0.0, 1.0], text="second version")])

    results = await store.query([0.0, 1.0], top_k=5)
    assert len(results) == 1
    assert results[0].record.text == "second version"
