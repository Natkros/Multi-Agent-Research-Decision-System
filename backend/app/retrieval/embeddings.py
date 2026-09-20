"""Embedding provider abstraction (Phase 5 RAG), mirroring `llm_provider.py`
and `search_provider.py`: `EmbeddingProvider` is the seam agent/pipeline code
talks to, and constructing a concrete provider never triggers a model
download or network call — only the first `embed()` does (lazy init).

`SentenceTransformersProvider` is the real, offline-capable default (brief
§8: local embeddings, no API key required, matching every other phase's
"works fully offline" design goal). `LocalEmbeddingProvider` is a
deterministic hash-based fake for tests/dev that don't want to load any ML
model at all — same role `LocalProvider`/`LocalSearchProvider` play for the
LLM/search seams.
"""

from __future__ import annotations

import hashlib
import math
import random
import typing
from abc import ABC, abstractmethod

from app.tools.resilience import ResilienceConfig, with_retry

if typing.TYPE_CHECKING:
    from app.config.settings import Settings

DEFAULT_SENTENCE_TRANSFORMERS_MODEL = "all-MiniLM-L6-v2"
DEFAULT_DIMENSION = 384


class EmbeddingProvider(ABC):
    name: str = "abstract"
    dimension: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, returning one fixed-length vector per
        input text, same order in as out."""
        raise NotImplementedError

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed([text])
        return vectors[0]


class SentenceTransformersProvider(EmbeddingProvider):
    """Local, offline sentence-transformers model. The model is loaded lazily
    on first `embed()` call, so importing this module or constructing this
    class never requires a download — matches the lazy-init pattern every
    other provider in this codebase follows."""

    name = "sentence-transformers"

    def __init__(
        self,
        model_name: str = DEFAULT_SENTENCE_TRANSFORMERS_MODEL,
        dimension: int = DEFAULT_DIMENSION,
        resilience: ResilienceConfig | None = None,
    ) -> None:
        self._model_name = model_name
        self.dimension = dimension
        self._model: typing.Any | None = None
        self._resilience = resilience or ResilienceConfig()
        self._breaker = self._resilience.new_breaker()

    def _get_model(self) -> typing.Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        if not texts:
            return []
        model = self._get_model()
        loop = asyncio.get_event_loop()

        async def _call() -> typing.Any:
            # sentence-transformers' `.encode()` is sync/CPU-bound; run it
            # off the event loop so it doesn't block other coroutines
            # mid-request.
            return await loop.run_in_executor(
                None, lambda: model.encode(list(texts), convert_to_numpy=True)
            )

        vectors = await with_retry(
            _call,
            max_attempts=self._resilience.max_attempts,
            base_delay=self._resilience.base_delay,
            max_delay=self._resilience.max_delay,
            breaker=self._breaker,
        )
        return [[float(x) for x in vector] for vector in vectors]


class LocalEmbeddingProvider(EmbeddingProvider):
    """Deterministic offline fake: same text always maps to the same unit
    vector (via a SHA-256-seeded PRNG), no model download, no network call.
    Distinct texts land at (with overwhelming probability, at this
    dimensionality) near-orthogonal random vectors rather than semantically
    meaningful ones — good enough for exercising the chunk/embed/store/query
    pipeline end to end in tests without pulling a real model."""

    name = "local"

    def __init__(self, dimension: int = DEFAULT_DIMENSION) -> None:
        self.dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_vector(text) for text in texts]

    def _hash_vector(self, text: str) -> list[float]:
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
        rng = random.Random(seed)
        raw = [rng.uniform(-1.0, 1.0) for _ in range(self.dimension)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Factory selecting the configured provider, matching
    `get_llm_provider`/`get_search_provider`'s shape."""
    if settings.embedding_provider == "sentence-transformers":
        return SentenceTransformersProvider(
            model_name=settings.embedding_model,
            dimension=settings.embedding_dimension,
            resilience=ResilienceConfig.from_settings(settings),
        )
    return LocalEmbeddingProvider(dimension=settings.embedding_dimension)
