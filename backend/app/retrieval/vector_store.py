"""Vector store abstraction (Phase 5 RAG, brief §8, docs/database-schema.md's
Qdrant note): `VectorStore` is the seam ingestion/retrieval code talks to.
`QdrantVectorStore` is the real backend — Qdrant holds embeddings for document
chunks only, PostgreSQL remains the system of record, so Qdrant can always be
rebuilt from PostgreSQL + `ingestion.py`. `InMemoryVectorStore` is a cosine-
similarity fake for tests/offline dev with no running Qdrant instance,
matching the Local*/fake pattern every other provider seam in this codebase
uses. Client construction is lazy: building `QdrantVectorStore` never opens a
connection, only the first `upsert`/`query` call does.
"""

from __future__ import annotations

import math
import typing
import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel

from app.tools.resilience import ResilienceConfig, with_retry

if typing.TYPE_CHECKING:
    from app.config.settings import Settings

DocumentType = typing.Literal[
    "official_docs", "paper", "government", "standard", "vendor_docs",
    "blog", "forum", "news", "internal_kb",
]


class ChunkMetadata(BaseModel):
    """Payload stored alongside each vector, per the deliverable spec:
    document_id, source, title, author, date, section, document_type, url,
    chunk_id."""

    document_id: str
    chunk_id: str
    source: str
    title: str
    author: str | None = None
    date: datetime | None = None
    section: str | None = None
    document_type: DocumentType = "internal_kb"
    url: str | None = None


class VectorRecord(BaseModel):
    """One embedded chunk, ready to upsert."""

    id: str  # == metadata.chunk_id; the point id a vector store keys on
    text: str
    vector: list[float]
    metadata: ChunkMetadata


class VectorSearchResult(BaseModel):
    record: VectorRecord
    score: float  # cosine similarity, higher is better


class VectorStore(ABC):
    name: str = "abstract"

    @abstractmethod
    async def upsert(self, records: list[VectorRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def query(
        self,
        vector: list[float],
        top_k: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[VectorSearchResult]:
        """`filters` matches `ChunkMetadata` field name -> exact value."""
        raise NotImplementedError


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryVectorStore(VectorStore):
    """Cosine similarity over a python list — no running Qdrant needed.
    Offline dev/test fake, same role `LocalSearchProvider` plays for web
    search."""

    name = "in_memory"

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}

    async def upsert(self, records: list[VectorRecord]) -> None:
        for record in records:
            self._records[record.id] = record

    async def query(
        self,
        vector: list[float],
        top_k: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[VectorSearchResult]:
        candidates = list(self._records.values())
        if filters:
            candidates = [
                r
                for r in candidates
                if all(getattr(r.metadata, key, None) == value for key, value in filters.items())
            ]
        scored = [
            VectorSearchResult(record=r, score=_cosine_similarity(vector, r.vector))
            for r in candidates
        ]
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]


class QdrantVectorStore(VectorStore):
    """Real Qdrant-backed store. Payload filters map directly onto Qdrant's
    `Filter`/`FieldCondition`/`MatchValue`, giving per-document-type/date
    filtering alongside vector search (docs/architecture.md §5 rationale for
    choosing Qdrant over a bare pgvector column)."""

    name = "qdrant"

    def __init__(
        self,
        url: str,
        *,
        collection_name: str = "document_chunks",
        dimension: int = 384,
        api_key: str | None = None,
        resilience: ResilienceConfig | None = None,
    ) -> None:
        self._url = url
        self._collection_name = collection_name
        self._dimension = dimension
        self._api_key = api_key
        self._client: typing.Any | None = None
        self._resilience = resilience or ResilienceConfig()
        self._breaker = self._resilience.new_breaker()

    def _get_client(self) -> typing.Any:
        if self._client is None:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._client = QdrantClient(url=self._url, api_key=self._api_key)
            existing = {c.name for c in self._client.get_collections().collections}
            if self._collection_name not in existing:
                self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=VectorParams(size=self._dimension, distance=Distance.COSINE),
                )
        return self._client

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        # Qdrant point ids must be an unsigned int or a UUID; chunk ids are
        # arbitrary strings, so derive a stable UUID5 and keep the real
        # chunk_id in the payload for round-tripping.
        return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))

    async def upsert(self, records: list[VectorRecord]) -> None:
        import asyncio

        from qdrant_client.models import PointStruct

        client = self._get_client()
        points = [
            PointStruct(
                id=self._point_id(r.id),
                vector=r.vector,
                payload={"text": r.text, **r.metadata.model_dump(mode="json")},
            )
            for r in records
        ]
        loop = asyncio.get_event_loop()

        async def _call() -> None:
            await loop.run_in_executor(
                None, lambda: client.upsert(collection_name=self._collection_name, points=points)
            )

        await with_retry(
            _call,
            max_attempts=self._resilience.max_attempts,
            base_delay=self._resilience.base_delay,
            max_delay=self._resilience.max_delay,
            breaker=self._breaker,
        )

    async def query(
        self,
        vector: list[float],
        top_k: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[VectorSearchResult]:
        import asyncio

        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = self._get_client()
        query_filter = None
        if filters:
            query_filter = Filter(
                must=[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in filters.items()]
            )

        loop = asyncio.get_event_loop()

        async def _call() -> typing.Any:
            return await loop.run_in_executor(
                None,
                lambda: client.search(
                    collection_name=self._collection_name,
                    query_vector=vector,
                    limit=top_k,
                    query_filter=query_filter,
                ),
            )

        hits = await with_retry(
            _call,
            max_attempts=self._resilience.max_attempts,
            base_delay=self._resilience.base_delay,
            max_delay=self._resilience.max_delay,
            breaker=self._breaker,
        )

        results: list[VectorSearchResult] = []
        for hit in hits:
            payload = dict(hit.payload or {})
            text = payload.pop("text", "")
            metadata = ChunkMetadata.model_validate(payload)
            results.append(
                VectorSearchResult(
                    record=VectorRecord(id=metadata.chunk_id, text=text, vector=[], metadata=metadata),
                    score=hit.score,
                )
            )
        return results


def get_vector_store(settings: Settings) -> VectorStore:
    """Factory selecting the configured backend, matching
    `get_llm_provider`/`get_search_provider`/`get_embedding_provider`'s shape."""
    if settings.qdrant_url:
        return QdrantVectorStore(
            url=settings.qdrant_url,
            collection_name=settings.qdrant_collection,
            dimension=settings.embedding_dimension,
            api_key=settings.qdrant_api_key,
            resilience=ResilienceConfig.from_settings(settings),
        )
    return InMemoryVectorStore()
