"""Hybrid (semantic + keyword) retrieval (Phase 5 RAG, brief §8: avoid the
"naive top-k embeddings only" pattern). `KeywordIndex` is a real, lightweight
BM25 implementation over ingested chunk text — pure-python, no external
search engine — so lexical matches (exact identifiers, acronyms, version
numbers) aren't lost to a purely semantic search that only ranks by meaning.
`hybrid_search` runs both retrieval paths, min-max normalizes each ranking,
merges/dedupes by chunk id with a weighted sum, and returns one ranked list —
callers (`reranking.py`) then reorder that merged list, they never call the
vector store twice to fake "hybrid" behavior.
"""

from __future__ import annotations

import math
import re
import typing
from collections import Counter, defaultdict

from pydantic import BaseModel

from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.vector_store import VectorRecord, VectorStore, get_vector_store
from app.services.cache_service import CacheService

if typing.TYPE_CHECKING:
    from app.config.settings import Settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# BM25 hyperparameters (Robertson/Sparck-Jones defaults).
_BM25_K1 = 1.5
_BM25_B = 0.75


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class KeywordSearchResult(BaseModel):
    record: VectorRecord
    score: float


class KeywordIndex:
    """Minimal in-process BM25 index over ingested chunk text."""

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}
        self._term_freqs: dict[str, Counter[str]] = {}
        self._doc_lengths: dict[str, int] = {}
        self._doc_freq: Counter[str] = Counter()

    def add(self, records: list[VectorRecord]) -> None:
        for record in records:
            if record.id in self._records:
                self._remove(record.id)
            tokens = _tokenize(record.text)
            self._records[record.id] = record
            self._term_freqs[record.id] = Counter(tokens)
            self._doc_lengths[record.id] = len(tokens)
            for term in set(tokens):
                self._doc_freq[term] += 1

    def _remove(self, chunk_id: str) -> None:
        old_terms = self._term_freqs.pop(chunk_id, None)
        self._doc_lengths.pop(chunk_id, None)
        self._records.pop(chunk_id, None)
        if old_terms:
            for term in old_terms:
                self._doc_freq[term] -= 1
                if self._doc_freq[term] <= 0:
                    del self._doc_freq[term]

    @property
    def _avg_doc_length(self) -> float:
        if not self._doc_lengths:
            return 0.0
        return sum(self._doc_lengths.values()) / len(self._doc_lengths)

    def search(self, query: str, top_k: int = 10) -> list[KeywordSearchResult]:
        query_terms = _tokenize(query)
        if not query_terms or not self._records:
            return []

        n_docs = len(self._records)
        avg_len = self._avg_doc_length
        scores: dict[str, float] = defaultdict(float)

        for term in query_terms:
            doc_freq = self._doc_freq.get(term, 0)
            if doc_freq == 0:
                continue
            idf = math.log(1 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))
            for chunk_id, term_freq in self._term_freqs.items():
                freq = term_freq.get(term, 0)
                if freq == 0:
                    continue
                doc_len = self._doc_lengths[chunk_id]
                denom = freq + _BM25_K1 * (1 - _BM25_B + _BM25_B * doc_len / (avg_len or 1))
                scores[chunk_id] += idf * (freq * (_BM25_K1 + 1)) / denom

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return [
            KeywordSearchResult(record=self._records[chunk_id], score=score)
            for chunk_id, score in ranked
        ]


class HybridResult(BaseModel):
    record: VectorRecord
    semantic_score: float
    keyword_score: float
    combined_score: float


def _min_max_normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    values = list(scores.values())
    lo, hi = min(values), max(values)
    if hi == lo:
        return {k: (1.0 if hi > 0 else 0.0) for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


async def hybrid_search(
    query: str,
    *,
    vector_store: VectorStore,
    embeddings: EmbeddingProvider,
    keyword_index: KeywordIndex,
    top_k: int = 10,
    fetch_k: int = 20,
    alpha: float = 0.5,
    filters: dict[str, str] | None = None,
) -> list[HybridResult]:
    """`alpha` weights semantic vs. keyword score in the merge (0 = pure
    keyword, 1 = pure semantic)."""
    query_vector = await embeddings.embed_one(query)
    semantic_hits = await vector_store.query(query_vector, top_k=fetch_k, filters=filters)
    keyword_hits = keyword_index.search(query, top_k=fetch_k)

    semantic_raw = {hit.record.id: hit.score for hit in semantic_hits}
    keyword_raw = {hit.record.id: hit.score for hit in keyword_hits}
    semantic_norm = _min_max_normalize(semantic_raw)
    keyword_norm = _min_max_normalize(keyword_raw)

    records: dict[str, VectorRecord] = {}
    for hit in semantic_hits:
        records[hit.record.id] = hit.record
    for kw_hit in keyword_hits:
        records.setdefault(kw_hit.record.id, kw_hit.record)

    merged: list[HybridResult] = []
    for chunk_id, record in records.items():
        sem = semantic_norm.get(chunk_id, 0.0)
        kw = keyword_norm.get(chunk_id, 0.0)
        merged.append(
            HybridResult(
                record=record,
                semantic_score=semantic_raw.get(chunk_id, 0.0),
                keyword_score=keyword_raw.get(chunk_id, 0.0),
                combined_score=alpha * sem + (1 - alpha) * kw,
            )
        )

    merged.sort(key=lambda r: r.combined_score, reverse=True)
    return merged[:top_k]


class HybridRetriever:
    """Facade bundling the pieces a caller (e.g. the Researcher agent's
    internal-KB tool) needs: search, then rerank.

    Phase 6 (docs/architecture.md §6): when `cache` is given, `search()`
    embeds the query once and checks the semantic cache before doing any
    real retrieval work — a cache hit skips the vector-store query, the BM25
    scan, and the merge entirely. Optional so every earlier phase's
    `get_hybrid_retriever(settings)` call (no cache wired) keeps working
    unchanged.
    """

    def __init__(
        self,
        *,
        vector_store: VectorStore,
        embeddings: EmbeddingProvider,
        keyword_index: KeywordIndex,
        alpha: float = 0.5,
        cache: CacheService | None = None,
        cache_ttl_seconds: int = 3600,
        cache_similarity_threshold: float = 0.92,
    ) -> None:
        self.vector_store = vector_store
        self.embeddings = embeddings
        self.keyword_index = keyword_index
        self.alpha = alpha
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_similarity_threshold = cache_similarity_threshold

    async def search(
        self, query: str, *, top_k: int = 10, fetch_k: int = 20, filters: dict[str, str] | None = None
    ) -> list[HybridResult]:
        if self.cache is None or filters:
            # Filtered queries aren't cached: a cache hit keyed only on the
            # query embedding could return results that don't satisfy a
            # *different* filter set for a semantically-similar query.
            return await self._search_uncached(query, top_k=top_k, fetch_k=fetch_k, filters=filters)

        query_vector = await self.embeddings.embed_one(query)
        namespace = f"hybrid_search:top{top_k}:fetch{fetch_k}"
        cached = await self.cache.get_semantic(namespace, query_vector, self.cache_similarity_threshold)
        if cached is not None:
            return [HybridResult.model_validate(item) for item in cached["results"]]

        results = await self._search_uncached(query, top_k=top_k, fetch_k=fetch_k, filters=None)
        await self.cache.set_semantic(
            namespace,
            query_vector,
            {"results": [r.model_dump(mode="json") for r in results]},
            self.cache_ttl_seconds,
        )
        return results

    async def _search_uncached(
        self, query: str, *, top_k: int, fetch_k: int, filters: dict[str, str] | None
    ) -> list[HybridResult]:
        return await hybrid_search(
            query,
            vector_store=self.vector_store,
            embeddings=self.embeddings,
            keyword_index=self.keyword_index,
            top_k=top_k,
            fetch_k=fetch_k,
            alpha=self.alpha,
            filters=filters,
        )


def get_hybrid_retriever(settings: Settings, cache: CacheService | None = None) -> HybridRetriever:
    """Factory wiring the embedding provider + vector store + a fresh
    `KeywordIndex` into one `HybridRetriever`, matching every other provider
    seam's `get_*` shape. One instance is meant to live for the process
    (`app.state`, see `app/main.py`) so its `KeywordIndex` — and the
    `InMemoryVectorStore` fallback when `QDRANT_URL` is unset — actually
    accumulate ingested documents across requests instead of resetting.
    `cache` is optional (Phase 6 semantic cache); omitted, retrieval behaves
    exactly as every earlier phase left it."""
    return HybridRetriever(
        vector_store=get_vector_store(settings),
        embeddings=get_embedding_provider(settings),
        keyword_index=KeywordIndex(),
        alpha=settings.hybrid_retrieval_alpha,
        cache=cache,
        cache_ttl_seconds=settings.cache_semantic_ttl_seconds,
        cache_similarity_threshold=settings.cache_semantic_similarity_threshold,
    )
