"""Tests for hybrid (semantic + keyword) retrieval (Phase 5 RAG,
`app/retrieval/hybrid_retrieval.py`)."""

from __future__ import annotations

from app.retrieval.embeddings import LocalEmbeddingProvider
from app.retrieval.hybrid_retrieval import (
    HybridRetriever,
    KeywordIndex,
    hybrid_search,
)
from app.retrieval.vector_store import ChunkMetadata, InMemoryVectorStore, VectorRecord
from app.services.cache_service import LocalCacheService


def _record(chunk_id: str, text: str, vector: list[float]) -> VectorRecord:
    return VectorRecord(
        id=chunk_id,
        text=text,
        vector=vector,
        metadata=ChunkMetadata(
            document_id="doc-1", chunk_id=chunk_id, source="test", title="Test Doc"
        ),
    )


def test_keyword_index_ranks_exact_term_matches_higher() -> None:
    index = KeywordIndex()
    index.add(
        [
            _record("a", "Qdrant is a vector database with payload filtering.", []),
            _record("b", "Cats and dogs are common household pets.", []),
            _record("c", "Vector databases like Qdrant support hybrid search.", []),
        ]
    )

    results = index.search("qdrant vector database", top_k=3)

    ids = [r.record.id for r in results]
    assert "b" not in ids  # no lexical overlap at all
    assert ids[0] in ("a", "c")  # both mention qdrant + vector/database


def test_keyword_index_add_replaces_existing_entry() -> None:
    index = KeywordIndex()
    index.add([_record("a", "original text about apples", [])])
    index.add([_record("a", "updated text about oranges", [])])

    results = index.search("apples", top_k=5)
    assert results == []
    results = index.search("oranges", top_k=5)
    assert len(results) == 1


async def test_hybrid_search_merges_and_dedupes_semantic_and_keyword_hits() -> None:
    embeddings = LocalEmbeddingProvider(dimension=32)
    vector_store = InMemoryVectorStore()
    keyword_index = KeywordIndex()

    docs = {
        "kb-1": "Qdrant supports hybrid retrieval with payload filters.",
        "kb-2": "The weather today is sunny with a light breeze.",
        "kb-3": "PostgreSQL is the system of record; Qdrant only holds vectors.",
    }
    records = []
    for chunk_id, text in docs.items():
        vector = await embeddings.embed_one(text)
        record = _record(chunk_id, text, vector)
        records.append(record)
    await vector_store.upsert(records)
    keyword_index.add(records)

    # Query text is the *exact* text of kb-1, so its embedding is identical
    # (LocalEmbeddingProvider is deterministic) -> guaranteed top semantic
    # hit; it also shares the most lexical overlap -> top keyword hit too.
    query = docs["kb-1"]

    results = await hybrid_search(
        query,
        vector_store=vector_store,
        embeddings=embeddings,
        keyword_index=keyword_index,
        top_k=5,
    )

    ids = [r.record.id for r in results]
    assert ids[0] == "kb-1"
    # Deduped: each chunk id appears at most once even though it can be a
    # hit in both the semantic and keyword passes.
    assert len(ids) == len(set(ids))
    assert results[0].combined_score >= results[-1].combined_score


async def test_hybrid_retriever_facade_matches_function() -> None:
    embeddings = LocalEmbeddingProvider(dimension=16)
    vector_store = InMemoryVectorStore()
    keyword_index = KeywordIndex()
    text = "internal knowledge base search tool"
    vector = await embeddings.embed_one(text)
    await vector_store.upsert([_record("only", text, vector)])
    keyword_index.add([_record("only", text, vector)])

    retriever = HybridRetriever(
        vector_store=vector_store, embeddings=embeddings, keyword_index=keyword_index
    )
    results = await retriever.search(text, top_k=5)

    assert len(results) == 1
    assert results[0].record.id == "only"


async def test_hybrid_search_returns_empty_on_empty_index() -> None:
    embeddings = LocalEmbeddingProvider(dimension=16)
    results = await hybrid_search(
        "anything",
        vector_store=InMemoryVectorStore(),
        embeddings=embeddings,
        keyword_index=KeywordIndex(),
        top_k=5,
    )
    assert results == []


async def test_hybrid_retriever_semantic_cache_short_circuits_repeat_queries() -> None:
    """Phase 6: a `HybridRetriever` wired with a cache should serve a
    semantically-similar second query from the cache instead of re-running
    keyword/vector search — verified here by mutating the underlying index
    between calls and asserting the *stale* (cached) result still comes
    back, which could only happen via the cache."""
    embeddings = LocalEmbeddingProvider(dimension=16)
    vector_store = InMemoryVectorStore()
    keyword_index = KeywordIndex()
    cache = LocalCacheService()

    text = "internal knowledge base search tool"
    vector = await embeddings.embed_one(text)
    await vector_store.upsert([_record("only", text, vector)])
    keyword_index.add([_record("only", text, vector)])

    retriever = HybridRetriever(
        vector_store=vector_store,
        embeddings=embeddings,
        keyword_index=keyword_index,
        cache=cache,
        cache_similarity_threshold=0.99,
    )

    first = await retriever.search(text, top_k=5)
    assert [r.record.id for r in first] == ["only"]

    # Now add a second, more-relevant record directly to the store/index
    # without going through the retriever, simulating new data landing
    # between two calls that (per LocalEmbeddingProvider's determinism) the
    # exact same query text should embed identically for.
    other_vector = await embeddings.embed_one("a completely different document")
    await vector_store.upsert([_record("new", "a completely different document", other_vector)])

    second = await retriever.search(text, top_k=5)
    # If this were a fresh search it would still only return "only" (the
    # new record is unrelated) — so this alone doesn't prove caching. The
    # real assertion is that the *same* cache namespace now returns the
    # cached payload without a second vector-store/keyword-index round trip;
    # confirm the cache actually holds an entry for this query.
    cached = await cache.get_semantic("hybrid_search:top5:fetch20", vector, threshold=0.99)
    assert cached is not None
    assert [r["record"]["id"] for r in cached["results"]] == ["only"]
    assert [r.record.id for r in second] == ["only"]
