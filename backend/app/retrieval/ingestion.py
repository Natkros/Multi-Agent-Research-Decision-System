"""Document ingestion pipeline (Phase 5 RAG, brief §8): parse/clean -> chunk
-> embed -> upsert, wired through the `chunking`/`embeddings`/`vector_store`
ABCs so swapping any one implementation (e.g. `InMemoryVectorStore` in tests
-> `QdrantVectorStore` in prod) never touches this module.

`document_id` identity: PostgreSQL remains the system of record for document
metadata (docs/database-schema.md's Qdrant note) — callers pass whatever
`document_id` their `documents` table row already has; this module only owns
turning that document's text into searchable chunks.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.retrieval.chunking import ChunkConfig, chunk_text
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.hybrid_retrieval import KeywordIndex
from app.retrieval.vector_store import ChunkMetadata, DocumentType, VectorRecord, VectorStore


class DocumentMetadata(BaseModel):
    """Everything ingestion needs to know about a document, independent of
    its content — mirrors `ChunkMetadata` minus the per-chunk fields."""

    document_id: str
    source: str
    title: str
    author: str | None = None
    date: datetime | None = None
    section: str | None = None
    document_type: DocumentType = "internal_kb"
    url: str | None = None


def _clean_text(text: str) -> str:
    """Minimal normalization: collapse Windows line endings and strip
    trailing whitespace per line, without altering content."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


class IngestionPipeline:
    """Owns the chunk/embed/upsert path plus registering chunks into the
    `KeywordIndex` used by `hybrid_retrieval.py`, so a single `ingest_document`
    call makes a document searchable both semantically and lexically."""

    def __init__(
        self,
        *,
        embeddings: EmbeddingProvider,
        vector_store: VectorStore,
        keyword_index: KeywordIndex,
        chunk_config: ChunkConfig | None = None,
    ) -> None:
        self._embeddings = embeddings
        self._vector_store = vector_store
        self._keyword_index = keyword_index
        self._chunk_config = chunk_config or ChunkConfig()

    async def ingest_document(self, text: str, metadata: DocumentMetadata) -> list[str]:
        """Parse/clean -> chunk -> embed -> upsert. Returns the ids of the
        chunks written (empty list if `text` had no chunkable content)."""
        cleaned = _clean_text(text)
        chunks = chunk_text(cleaned, self._chunk_config)
        if not chunks:
            return []

        vectors = await self._embeddings.embed([c.text for c in chunks])

        records: list[VectorRecord] = []
        for chunk, vector in zip(chunks, vectors):
            chunk_id = f"{metadata.document_id}::chunk-{chunk.index}"
            records.append(
                VectorRecord(
                    id=chunk_id,
                    text=chunk.text,
                    vector=vector,
                    metadata=ChunkMetadata(
                        document_id=metadata.document_id,
                        chunk_id=chunk_id,
                        source=metadata.source,
                        title=metadata.title,
                        author=metadata.author,
                        date=metadata.date,
                        section=metadata.section,
                        document_type=metadata.document_type,
                        url=metadata.url,
                    ),
                )
            )

        await self._vector_store.upsert(records)
        self._keyword_index.add(records)
        return [r.id for r in records]
