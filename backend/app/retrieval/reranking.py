"""Reranking (Phase 5 RAG, brief §8): the last step before hybrid results are
handed to a caller as context, so lexical/semantic merge noise (e.g. a
generic high-embedding-similarity chunk that doesn't actually answer the
query) gets pushed down.

Two implementations, both real reordering — neither just calls the vector
store again:

- `LexicalRecencyReranker` (default): deterministic, no second model —
  query/chunk token-overlap (a real lexical signal `hybrid_retrieval`'s BM25
  pass also uses, but recomputed here against the *query* specifically,
  since BM25 there was corpus-relative) plus a small recency boost from
  `ChunkMetadata.date`. Zero extra latency/memory, good enough to
  meaningfully reorder a hybrid merge.
- `CrossEncoderReranker` (optional, brief-compliant alternative): a real
  `sentence-transformers` cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`)
  that jointly scores (query, chunk) pairs — strictly more accurate than any
  lexical heuristic, at the cost of a second model load/download and
  materially more latency per query. Lazy-init like every other provider
  here; only pay that cost if `RERANKER=cross_encoder` is actually
  configured.

Tradeoff is documented rather than defaulting to the heavier model: this repo's
design goal every phase has been "works fully offline with no keys and no
network calls unless a real provider is explicitly configured" — the lexical
reranker keeps that true for the default config, the cross-encoder is opt-in.
"""

from __future__ import annotations

import re
import typing
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from app.retrieval.hybrid_retrieval import HybridResult

if typing.TYPE_CHECKING:
    from app.config.settings import Settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_RECENCY_HALF_LIFE_DAYS = 365.0


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class Reranker(ABC):
    name: str = "abstract"

    @abstractmethod
    async def rerank(
        self, query: str, results: list[HybridResult], top_k: int | None = None
    ) -> list[HybridResult]:
        """Return `results` reordered (and optionally truncated to `top_k`)
        by relevance to `query`."""
        raise NotImplementedError


class LexicalRecencyReranker(Reranker):
    name = "lexical_recency"

    def __init__(self, recency_weight: float = 0.1) -> None:
        self._recency_weight = recency_weight

    def _score(self, query_tokens: set[str], result: HybridResult) -> float:
        chunk_tokens = _tokenize(result.record.text)
        overlap = len(query_tokens & chunk_tokens) / len(query_tokens) if query_tokens else 0.0

        recency = 0.0
        date = result.record.metadata.date
        if date is not None:
            now = datetime.now(UTC)
            compare_date = date if date.tzinfo else date.replace(tzinfo=UTC)
            age_days = max(0.0, (now - compare_date).total_seconds() / 86400.0)
            recency = 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)

        # Lexical overlap dominates (it's the actual relevance signal);
        # recency only tie-breaks between similarly-relevant chunks.
        return (1.0 - self._recency_weight) * overlap + self._recency_weight * recency

    async def rerank(
        self, query: str, results: list[HybridResult], top_k: int | None = None
    ) -> list[HybridResult]:
        query_tokens = _tokenize(query)
        scored = sorted(
            results, key=lambda r: self._score(query_tokens, r), reverse=True
        )
        return scored[:top_k] if top_k is not None else scored


class CrossEncoderReranker(Reranker):
    """Real cross-encoder rerank. Lazy-loaded: constructing this class never
    downloads or loads a model, only the first `rerank()` call does."""

    name = "cross_encoder"

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        self._model_name = model_name
        self._model: typing.Any | None = None

    def _get_model(self) -> typing.Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name)
        return self._model

    async def rerank(
        self, query: str, results: list[HybridResult], top_k: int | None = None
    ) -> list[HybridResult]:
        import asyncio

        if not results:
            return []
        model = self._get_model()
        pairs = [(query, r.record.text) for r in results]
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(None, lambda: model.predict(pairs))
        ranked = [r for _, r in sorted(zip(scores, results), key=lambda p: p[0], reverse=True)]
        return ranked[:top_k] if top_k is not None else ranked


def get_reranker(settings: Settings) -> Reranker:
    """Factory, matching every other provider seam's shape."""
    if settings.reranker == "cross_encoder":
        return CrossEncoderReranker(model_name=settings.reranker_model)
    return LexicalRecencyReranker(recency_weight=settings.reranker_recency_weight)
