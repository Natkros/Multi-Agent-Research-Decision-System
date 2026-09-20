"""Tests for the evaluation harness (backend/app/evaluation/runner.py).

Runs a small (3-question) subset of the benchmark through the real graph via
`LocalProvider`/`LocalSearchProvider` so it stays fast/offline -- the full
20+ question benchmark is reserved for the CLI script's manual/CI-optional
run (scripts/evaluate_system.py), matching the task's instruction not to run
the full benchmark through the real graph in this test.
"""

from __future__ import annotations

from app.config.settings import get_settings
from app.evaluation.benchmark import BENCHMARK
from app.evaluation.runner import EvaluationReport, run_benchmark
from app.tools.llm_provider import LocalProvider
from app.tools.search_provider import LocalSearchProvider


async def test_run_benchmark_small_subset_produces_complete_report():
    questions = BENCHMARK[:3]
    # Same settings tweak the canonical E2E test (Phase 8) uses: LocalProvider
    # never proposes its own risks, so the "thin evidence" fallback needs a
    # high threshold to guarantee a non-empty risk list under this offline
    # provider.
    settings = get_settings().model_copy(update={"risk_thin_evidence_threshold": 10})

    report = await run_benchmark(
        questions, llm=LocalProvider(), search=LocalSearchProvider(), settings=settings
    )

    assert isinstance(report, EvaluationReport)
    assert report.num_questions == 3
    assert len(report.results) == 3
    assert report.provider == "local"
    assert report.search_provider == "local"

    for question, result in zip(questions, report.results):
        assert result.question_id == question.id
        assert result.category == question.category
        assert result.status == "completed", result.error
        # Every applicable metric key is present (value may be None if not
        # applicable to this question -- see metrics.py docstrings).
        assert "source_relevance" in result.metrics
        assert "evidence_coverage" in result.metrics
        assert "hallucination_rate" in result.metrics
        assert "task_completion_rate" in result.metrics
        assert "criterion_coverage" in result.metrics
        assert "latency" in result.metrics
        assert result.metrics["latency"]["total_ms"] >= 0
        assert "token_usage" in result.metrics
        assert result.metrics["evidence_coverage"] is not None

    aggregate = report.aggregate
    assert aggregate["success_rate"] == 1.0
    assert aggregate["num_completed"] == 3
    assert aggregate["num_failed"] == 0
    assert aggregate["total_tokens"] >= 0
    # mean_evidence_coverage is computable for every LocalProvider run
    assert aggregate["mean_evidence_coverage"] is not None


async def test_run_benchmark_defaults_to_local_providers_and_full_benchmark():
    settings = get_settings().model_copy(update={"risk_thin_evidence_threshold": 10})
    report = await run_benchmark(BENCHMARK[:1], settings=settings)
    assert report.provider == "local"
    assert report.search_provider == "local"
    assert report.results[0].status == "completed"


async def test_run_benchmark_records_per_question_failure_without_aborting():
    class _BrokenProvider(LocalProvider):
        async def complete(self, **kwargs):  # noqa: ANN003 - matches LLMProvider signature
            raise RuntimeError("boom")

    settings = get_settings().model_copy(update={"risk_thin_evidence_threshold": 10})
    report = await run_benchmark(
        BENCHMARK[:2], llm=_BrokenProvider(), search=LocalSearchProvider(), settings=settings
    )
    assert len(report.results) == 2
    assert all(r.status == "failed" for r in report.results)
    assert all(r.error for r in report.results)
    assert report.aggregate["success_rate"] == 0.0
