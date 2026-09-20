"""Tests for reranking (Phase 5 RAG, `app/retrieval/reranking.py`). The
`CrossEncoderReranker` test is skipped if the model/package isn't available;
`LexicalRecencyReranker` is the reranker the suite actually depends on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config.settings import Settings
from app.retrieval.hybrid_retrieval import HybridResult
from app.retrieval.reranking import (
    CrossEncoderReranker,
    LexicalRecencyReranker,
    get_reranker,
)
from app.retrieval.vector_store import ChunkMetadata, VectorRecord

try:
    import sentence_transformers  # noqa: F401

    _HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    _HAS_SENTENCE_TRANSFORMERS = False

import pytest


def _hybrid_result(chunk_id: str, text: str, *, combined_score: float, date=None) -> HybridResult:
    return HybridResult(
        record=VectorRecord(
            id=chunk_id,
            text=text,
            vector=[],
            metadata=ChunkMetadata(
                document_id="doc", chunk_id=chunk_id, source="test", title="t", date=date
            ),
        ),
        semantic_score=combined_score,
        keyword_score=combined_score,
        combined_score=combined_score,
    )


def test_factory_returns_lexical_recency_by_default() -> None:
    reranker = get_reranker(Settings(reranker="lexical_recency"))
    assert isinstance(reranker, LexicalRecencyReranker)


def test_factory_returns_cross_encoder() -> None:
    reranker = get_reranker(Settings(reranker="cross_encoder"))
    assert isinstance(reranker, CrossEncoderReranker)


def test_constructing_cross_encoder_never_loads_a_model() -> None:
    CrossEncoderReranker(model_name="not-a-real-model")


async def test_lexical_reranker_reorders_by_actual_relevance_not_input_order() -> None:
    """Craft a case where the hybrid merge's combined_score ranking is
    "wrong" (a higher-scored chunk is actually less relevant to the query
    text) so a real reorder is observable, not just a pass-through."""
    reranker = LexicalRecencyReranker(recency_weight=0.0)

    # Deliberately mis-ranked by combined_score: "off_topic" scores highest
    # from the hybrid merge but shares zero query terms.
    results = [
        _hybrid_result("off_topic", "The weather today is sunny and warm.", combined_score=0.9),
        _hybrid_result(
            "on_topic", "Qdrant supports hybrid vector and keyword retrieval.", combined_score=0.1
        ),
    ]

    reranked = await reranker.rerank("qdrant vector retrieval", results)

    assert [r.record.id for r in reranked] == ["on_topic", "off_topic"]


async def test_lexical_reranker_recency_breaks_ties() -> None:
    now = datetime.now(UTC)
    reranker = LexicalRecencyReranker(recency_weight=0.5)

    results = [
        _hybrid_result(
            "old", "database performance benchmark", combined_score=0.5, date=now - timedelta(days=900)
        ),
        _hybrid_result(
            "new", "database performance benchmark", combined_score=0.5, date=now - timedelta(days=1)
        ),
    ]

    reranked = await reranker.rerank("database performance benchmark", results)

    assert [r.record.id for r in reranked] == ["new", "old"]


async def test_lexical_reranker_respects_top_k() -> None:
    reranker = LexicalRecencyReranker()
    results = [_hybrid_result(f"c{i}", f"text number {i}", combined_score=0.0) for i in range(5)]
    reranked = await reranker.rerank("text", results, top_k=2)
    assert len(reranked) == 2


@pytest.mark.skipif(not _HAS_SENTENCE_TRANSFORMERS, reason="sentence-transformers not installed")
async def test_cross_encoder_reranker_real_model_reorders() -> None:
    reranker = CrossEncoderReranker()
    results = [
        _hybrid_result("off_topic", "Bananas are a good source of potassium.", combined_score=0.9),
        _hybrid_result(
            "on_topic",
            "Qdrant is a vector database purpose-built for hybrid retrieval with payload filters.",
            combined_score=0.1,
        ),
    ]
    try:
        reranked = await reranker.rerank("What vector database supports hybrid retrieval?", results)
    except Exception as exc:  # noqa: BLE001 - model not cached/no network
        pytest.skip(f"cross-encoder model unavailable: {exc}")

    assert reranked[0].record.id == "on_topic"
