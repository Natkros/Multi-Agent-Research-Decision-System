"""Evaluation harness (docs/evaluation.md §4, brief §24-25).

`run_benchmark` runs each `BenchmarkQuestion` through the existing Phase 2
entrypoint (`run_research_graph`) and computes every applicable metric from
`metrics.py`, aggregating the per-question results into an
`EvaluationReport`. Defaults to `LocalProvider`/`LocalSearchProvider` so the
whole harness runs offline (no API keys, no live Postgres/Redis/Qdrant --
`run_research_graph` already degrades to in-memory fakes when those aren't
configured), but accepts any `LLMProvider`/`SearchProvider` for a real run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config.settings import Settings, get_settings
from app.evaluation import metrics
from app.evaluation.benchmark import BENCHMARK, BenchmarkQuestion
from app.orchestration.graph import run_research_graph
from app.retrieval.hybrid_retrieval import HybridRetriever
from app.schemas.state import ResearchRequest
from app.tools.llm_provider import LLMProvider, LocalProvider
from app.tools.search_provider import LocalSearchProvider, SearchProvider


class QuestionResult(BaseModel):
    question_id: str
    category: str
    question: str
    status: str  # "completed" | "failed" -- mirrors ExecutionMetadata.status's terminal states
    error: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    generated_at: datetime
    provider: str
    search_provider: str
    num_questions: int
    results: list[QuestionResult]
    aggregate: dict[str, Any] = Field(default_factory=dict)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _compute_question_metrics(state, question: BenchmarkQuestion, settings: Settings) -> dict[str, Any]:
    """All applicable metrics for one completed run. Every value is `None`
    when the metric doesn't apply to this question/run (see metrics.py
    docstrings) so aggregation can skip it cleanly."""
    execution_metadata = state.execution_metadata
    return {
        "source_relevance": metrics.source_relevance(state),
        "source_diversity": metrics.source_diversity(state),
        "evidence_coverage": metrics.evidence_coverage(state),
        "citation_coverage": metrics.citation_coverage(state.final_report),
        "claim_verification_accuracy": metrics.claim_verification_accuracy(state, question),
        "task_completion_rate": metrics.task_completion_rate(execution_metadata),
        "tool_success_rate": metrics.tool_success_rate(execution_metadata),
        "hallucination_rate": metrics.hallucination_rate(state.final_report),
        "average_iterations": metrics.average_iterations(
            execution_metadata, max_cycles=settings.verification_max_cycles
        ),
        "failure_recovery_rate": metrics.failure_recovery_rate(execution_metadata),
        "criterion_coverage": metrics.criterion_coverage(state),
        "sensitivity_flag_rate": metrics.sensitivity_flag_rate(state),
        "evidence_to_claim_ratio": metrics.evidence_to_claim_ratio(state),
        "latency": metrics.latency(execution_metadata),
        "token_usage": metrics.token_usage(execution_metadata),
        "cost_per_task": metrics.cost_per_task(execution_metadata),
    }


def _aggregate(results: list[QuestionResult]) -> dict[str, Any]:
    statuses = [r.status for r in results]
    numeric_metric_names = [
        "source_relevance",
        "evidence_coverage",
        "citation_coverage",
        "claim_verification_accuracy",
        "task_completion_rate",
        "tool_success_rate",
        "hallucination_rate",
        "average_iterations",
        "failure_recovery_rate",
        "criterion_coverage",
        "sensitivity_flag_rate",
        "evidence_to_claim_ratio",
        "cost_per_task",
    ]
    aggregate: dict[str, Any] = {"success_rate": metrics.success_rate(statuses)}
    for name in numeric_metric_names:
        values = [
            r.metrics[name]
            for r in results
            if r.status == "completed" and isinstance(r.metrics.get(name), (int, float))
        ]
        aggregate[f"mean_{name}"] = _mean(values)
    total_tokens = sum(
        r.metrics["token_usage"]["total_tokens"]
        for r in results
        if r.status == "completed" and isinstance(r.metrics.get("token_usage"), dict)
    )
    total_latency_ms = sum(
        r.metrics["latency"]["total_ms"]
        for r in results
        if r.status == "completed" and isinstance(r.metrics.get("latency"), dict)
    )
    aggregate["total_tokens"] = total_tokens
    aggregate["total_latency_ms"] = total_latency_ms
    aggregate["num_completed"] = sum(1 for s in statuses if s == "completed")
    aggregate["num_failed"] = sum(1 for s in statuses if s == "failed")
    return aggregate


async def run_benchmark(
    questions: list[BenchmarkQuestion] | None = None,
    *,
    llm: LLMProvider | None = None,
    search: SearchProvider | None = None,
    settings: Settings | None = None,
    kb: HybridRetriever | None = None,
) -> EvaluationReport:
    """Run each benchmark question through `run_research_graph` and return an
    `EvaluationReport`. A per-question exception is caught and recorded as a
    failed `QuestionResult` rather than aborting the whole run, so one bad
    question never blocks the report for the rest of the benchmark."""
    questions = questions if questions is not None else BENCHMARK
    settings = settings or get_settings()
    llm = llm or LocalProvider()
    search = search or LocalSearchProvider()

    results: list[QuestionResult] = []
    for question in questions:
        request = ResearchRequest(
            id=uuid4(),
            question=question.question,
            constraints=question.constraints,
            alternatives_hint=question.expected_alternatives,
            criteria_hint=question.evaluation_criteria,
            requested_by="evaluation-harness",
            created_at=datetime.now(UTC),
        )
        try:
            state = await run_research_graph(request, llm=llm, search=search, settings=settings, kb=kb)
        except Exception as exc:  # noqa: BLE001 - one bad question must not abort the run
            results.append(
                QuestionResult(
                    question_id=question.id,
                    category=question.category,
                    question=question.question,
                    status="failed",
                    error=str(exc),
                )
            )
            continue

        status = "completed" if state.execution_metadata.status == "completed" else "failed"
        results.append(
            QuestionResult(
                question_id=question.id,
                category=question.category,
                question=question.question,
                status=status,
                error=None if status == "completed" else state.execution_metadata.status,
                metrics=_compute_question_metrics(state, question, settings),
            )
        )

    return EvaluationReport(
        generated_at=datetime.now(UTC),
        provider=llm.name,
        search_provider=search.name,
        num_questions=len(questions),
        results=results,
        aggregate=_aggregate(results),
    )
