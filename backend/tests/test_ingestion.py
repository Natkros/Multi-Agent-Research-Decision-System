"""End-to-end tests for the ingestion pipeline (Phase 5 RAG,
`app/retrieval/ingestion.py`): text in -> chunks searchable out, fully
offline via `LocalEmbeddingProvider`/`InMemoryVectorStore`."""

from __future__ import annotations

from app.retrieval.chunking import ChunkConfig
from app.retrieval.embeddings import LocalEmbeddingProvider
from app.retrieval.hybrid_retrieval import KeywordIndex, hybrid_search
from app.retrieval.ingestion import DocumentMetadata, IngestionPipeline
from app.retrieval.vector_store import InMemoryVectorStore


def _pipeline(chunk_size: int = 200, chunk_overlap: int = 40) -> tuple[IngestionPipeline, InMemoryVectorStore, LocalEmbeddingProvider, KeywordIndex]:
    embeddings = LocalEmbeddingProvider(dimension=32)
    vector_store = InMemoryVectorStore()
    keyword_index = KeywordIndex()
    pipeline = IngestionPipeline(
        embeddings=embeddings,
        vector_store=vector_store,
        keyword_index=keyword_index,
        chunk_config=ChunkConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap),
    )
    return pipeline, vector_store, embeddings, keyword_index


async def test_ingest_document_returns_chunk_ids_and_upserts_them() -> None:
    pipeline, vector_store, _, _ = _pipeline()
    text = (
        "Qdrant is a vector database built for high-dimensional similarity "
        "search. It supports payload filtering alongside vector search, "
        "which lets you combine semantic and metadata constraints in one "
        "query. PostgreSQL remains the system of record for structured "
        "data; Qdrant only ever holds embeddings for document chunks."
    )
    metadata = DocumentMetadata(
        document_id="doc-1", source="test-source", title="Qdrant Overview", document_type="internal_kb"
    )

    chunk_ids = await pipeline.ingest_document(text, metadata)

    assert chunk_ids
    assert all(cid.startswith("doc-1::chunk-") for cid in chunk_ids)

    # Every chunk id is actually retrievable from the vector store with the
    # right metadata attached.
    for chunk_id in chunk_ids:
        results = await vector_store.query([0.0] * 32, top_k=100)
        matching = [r for r in results if r.record.id == chunk_id]
        assert len(matching) == 1
        assert matching[0].record.metadata.document_id == "doc-1"
        assert matching[0].record.metadata.source == "test-source"
        assert matching[0].record.metadata.document_type == "internal_kb"


async def test_ingest_empty_text_produces_no_chunks() -> None:
    pipeline, _, _, _ = _pipeline()
    chunk_ids = await pipeline.ingest_document("   \n  ", DocumentMetadata(document_id="doc-empty", source="s", title="t"))
    assert chunk_ids == []


async def test_ingested_text_is_searchable_via_hybrid_search() -> None:
    pipeline, vector_store, embeddings, keyword_index = _pipeline(chunk_size=500, chunk_overlap=50)
    text = (
        "Our internal knowledge base documents the vendor evaluation "
        "process for choosing a managed vector database provider. The "
        "recommended provider must support hybrid retrieval and payload "
        "filtering out of the box."
    )
    await pipeline.ingest_document(
        text, DocumentMetadata(document_id="kb-doc", source="internal", title="Vendor Evaluation")
    )

    results = await hybrid_search(
        "vendor evaluation process for vector database provider",
        vector_store=vector_store,
        embeddings=embeddings,
        keyword_index=keyword_index,
        top_k=5,
    )

    assert results
    assert results[0].record.metadata.document_id == "kb-doc"


async def test_ingest_multiple_documents_keeps_them_separately_addressable() -> None:
    pipeline, vector_store, _, keyword_index = _pipeline(chunk_size=500, chunk_overlap=50)
    await pipeline.ingest_document(
        "First document about Kubernetes deployment strategies.",
        DocumentMetadata(document_id="doc-a", source="s", title="A"),
    )
    await pipeline.ingest_document(
        "Second document about relational database indexing.",
        DocumentMetadata(document_id="doc-b", source="s", title="B"),
    )

    results = keyword_index.search("kubernetes deployment", top_k=5)
    assert results
    assert all(r.record.metadata.document_id == "doc-a" for r in results)
