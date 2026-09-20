"""Tests for pure evaluation metric functions (docs/evaluation.md §1,
backend/app/evaluation/metrics.py). Every fixture is hand-crafted with known
expected values -- no LLM/graph calls here, that's covered by
test_evaluation_runner.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.evaluation import metrics
from app.evaluation.benchmark import BenchmarkQuestion, KnownEvidenceItem
from app.schemas.state import (
    AgentRunMeta,
    AlternativeScore,
    Claim,
    ClaimVerification,
    DecisionCriteria,
    DecisionMatrix,
    EvidenceItem,
    ExecutionMetadata,
    FinalReport,
    ResearchPlan,
    ResearchQuestion,
    ResearchRequest,
    ResearchState,
    RetrievedDocument,
    SensitivityResult,
    Source,
)

_NOW = datetime.now(UTC)


def _source(id_: str, source_type: str = "official_docs", publisher: str | None = "Pub") -> Source:
    return Source(
        id=id_,
        title=f"Title {id_}",
        url=f"https://example.com/{id_}",
        publisher=publisher,
        author=None,
        published_at=_NOW,
        retrieved_at=_NOW,
        source_type=source_type,
        credibility_score=0.8,
        content_hash=f"hash-{id_}",
    )


def _request() -> ResearchRequest:
    return ResearchRequest(
        id=uuid4(), question="q?", requested_by="tester", created_at=_NOW
    )


def _execution_metadata(**overrides) -> ExecutionMetadata:
    defaults = dict(
        trace_id="trace-1",
        session_id=uuid4(),
        started_at=_NOW,
        completed_at=_NOW + timedelta(seconds=2),
        status="completed",
        agent_runs=[],
        total_tokens=0,
        verification_cycles_used=1,
    )
    defaults.update(overrides)
    return ExecutionMetadata(**defaults)


def _final_report(**overrides) -> FinalReport:
    defaults = dict(
        executive_summary="summary",
        research_question="q?",
        decision_context="context",
        alternatives=["A", "B"],
        criteria=[],
        key_findings=["finding one", "finding two"],
        evidence=[],
        contradictions=[],
        comparative_analysis=DecisionMatrix(
            criteria=[], scores=[], weighted_totals={}, recommended="A"
        ),
        risk_analysis=[],
        assumptions=[],
        decision_rationale="rationale",
        confidence=0.7,
        limitations=[],
        sources=[_source("s1"), _source("s2")],
        citations={},
    )
    defaults.update(overrides)
    return FinalReport(**defaults)


# ---------------------------------------------------------------------------
# Hallucination rate (the failure scenario spelled out in the task):
# 2 citations, 1 resolvable, 1 hallucinated -> 0.5
# ---------------------------------------------------------------------------


def test_hallucination_rate_half_when_one_of_two_citations_unresolvable():
    report = _final_report(
        sources=[_source("s1")],
        citations={"[1]": "s1", "[2]": "s-does-not-exist"},
    )
    assert metrics.hallucination_rate(report) == 0.5


def test_hallucination_rate_zero_when_all_citations_and_evidence_resolve():
    report = _final_report(
        sources=[_source("s1")],
        citations={"[1]": "s1"},
        evidence=[
            EvidenceItem(
                id="e1", claim_id="c1", evidence_text="text", source_id="s1",
                evidence_type="documentation", strength="strong", confidence=0.9,
            )
        ],
    )
    assert metrics.hallucination_rate(report) == 0.0


def test_hallucination_rate_none_when_no_citations_or_evidence():
    report = _final_report(sources=[], citations={}, evidence=[])
    assert metrics.hallucination_rate(report) is None


# ---------------------------------------------------------------------------
# Source relevance
# ---------------------------------------------------------------------------


def test_source_relevance_means_only_cited_documents():
    request = _request()
    doc_cited = RetrievedDocument(
        source_id="s1", title="t1", url=None, source_type="official_docs",
        retrieved_at=_NOW, relevant_passage="p", claims=[], relevance_score=0.9,
    )
    doc_uncited = RetrievedDocument(
        source_id="s2", title="t2", url=None, source_type="blog",
        retrieved_at=_NOW, relevant_passage="p", claims=[], relevance_score=0.1,
    )
    state = ResearchState(
        request=request,
        retrieved_documents=[doc_cited, doc_uncited],
        final_report=_final_report(citations={"[1]": "s1"}),
        execution_metadata=_execution_metadata(),
    )
    assert metrics.source_relevance(state) == 0.9


def test_source_relevance_none_without_citations():
    state = ResearchState(
        request=_request(),
        final_report=_final_report(citations={}),
        execution_metadata=_execution_metadata(),
    )
    assert metrics.source_relevance(state) is None


# ---------------------------------------------------------------------------
# Source diversity
# ---------------------------------------------------------------------------


def test_source_diversity_counts_types_and_publishers():
    state = ResearchState(
        request=_request(),
        sources=[
            _source("s1", source_type="official_docs", publisher="A"),
            _source("s2", source_type="blog", publisher="B"),
            _source("s3", source_type="blog", publisher="B"),
        ],
        execution_metadata=_execution_metadata(),
    )
    diversity = metrics.source_diversity(state)
    assert diversity["distinct_source_types"] == 2
    assert diversity["distinct_publishers"] == 2
    assert diversity["dominant_type_ratio"] == 2 / 3


def test_source_diversity_empty_sources():
    state = ResearchState(request=_request(), sources=[], execution_metadata=_execution_metadata())
    assert metrics.source_diversity(state) == {
        "distinct_source_types": 0,
        "distinct_publishers": 0,
        "dominant_type_ratio": 0.0,
    }


# ---------------------------------------------------------------------------
# Evidence coverage / evidence-to-claim ratio
# ---------------------------------------------------------------------------


def _plan_with_two_questions() -> ResearchPlan:
    return ResearchPlan(
        objective="obj",
        decision_type="other",
        alternatives=["A", "B"],
        criteria=[],
        research_questions=[
            ResearchQuestion(id="rq1", text="q1", dimension="cost", priority="high"),
            ResearchQuestion(id="rq2", text="q2", dimension="risk", priority="medium"),
        ],
        required_evidence=[],
        constraints=[],
        assumptions=[],
    )


def test_evidence_coverage_half_when_one_of_two_dimensions_covered():
    claim = Claim(id="c1", text="claim text", source_id="s1", research_question_id="rq1")
    evidence = EvidenceItem(
        id="e1", claim_id="c1", evidence_text="text", source_id="s1",
        evidence_type="documentation", strength="strong", confidence=0.8,
    )
    state = ResearchState(
        request=_request(),
        plan=_plan_with_two_questions(),
        claims=[claim],
        evidence=[evidence],
        execution_metadata=_execution_metadata(),
    )
    assert metrics.evidence_coverage(state) == 0.5


def test_evidence_coverage_none_without_plan():
    state = ResearchState(request=_request(), execution_metadata=_execution_metadata())
    assert metrics.evidence_coverage(state) is None


def test_evidence_to_claim_ratio():
    claim = Claim(id="c1", text="claim", source_id="s1", research_question_id="rq1")
    evidence = [
        EvidenceItem(
            id=f"e{i}", claim_id="c1", evidence_text="text", source_id="s1",
            evidence_type="documentation", strength="strong", confidence=0.8,
        )
        for i in range(3)
    ]
    state = ResearchState(
        request=_request(), claims=[claim], evidence=evidence,
        execution_metadata=_execution_metadata(),
    )
    assert metrics.evidence_to_claim_ratio(state) == 3.0


def test_evidence_to_claim_ratio_none_without_claims():
    state = ResearchState(request=_request(), execution_metadata=_execution_metadata())
    assert metrics.evidence_to_claim_ratio(state) is None


# ---------------------------------------------------------------------------
# Citation coverage
# ---------------------------------------------------------------------------


def test_citation_coverage_capped_at_one():
    report = _final_report(key_findings=["f1"], citations={"[1]": "s1", "[2]": "s2"})
    assert metrics.citation_coverage(report) == 1.0


def test_citation_coverage_zero_with_no_citations():
    report = _final_report(key_findings=["f1", "f2"], citations={})
    assert metrics.citation_coverage(report) == 0.0


# ---------------------------------------------------------------------------
# Claim verification accuracy
# ---------------------------------------------------------------------------


def test_claim_verification_accuracy_matches_known_evidence():
    question = BenchmarkQuestion(
        id="q1", question="?", category="engineering",
        known_evidence=[KnownEvidenceItem(text="pgvector adds vector search", expected_status="VERIFIED")],
    )
    claim = Claim(
        id="c1", text="Pgvector adds vector search to Postgres", source_id="s1",
        research_question_id="rq1",
    )
    verification = ClaimVerification(
        claim_id="c1", status="VERIFIED", supporting_sources=["s1"],
        contradicting_sources=[], confidence=0.9, explanation="matches docs",
    )
    state = ResearchState(
        request=_request(), claims=[claim], verified_claims=[verification],
        execution_metadata=_execution_metadata(),
    )
    assert metrics.claim_verification_accuracy(state, question) == 1.0


def test_claim_verification_accuracy_none_without_known_evidence():
    question = BenchmarkQuestion(id="q1", question="?", category="engineering")
    state = ResearchState(request=_request(), execution_metadata=_execution_metadata())
    assert metrics.claim_verification_accuracy(state, question) is None


def test_claim_verification_accuracy_none_when_nothing_matches():
    question = BenchmarkQuestion(
        id="q1", question="?", category="engineering",
        known_evidence=[KnownEvidenceItem(text="completely unrelated fact")],
    )
    claim = Claim(id="c1", text="some other claim entirely", source_id="s1", research_question_id="rq1")
    state = ResearchState(request=_request(), claims=[claim], execution_metadata=_execution_metadata())
    assert metrics.claim_verification_accuracy(state, question) is None


# ---------------------------------------------------------------------------
# Agent quality metrics
# ---------------------------------------------------------------------------


def _agent_run(name: str, *, errors: list[str] | None = None, tool_calls: list[str] | None = None, tokens: int = 10) -> AgentRunMeta:
    return AgentRunMeta(
        agent_name=name, trace_id="t", start_time=_NOW, end_time=_NOW,
        latency_ms=100, tokens=tokens, model="local", tool_calls=tool_calls or [],
        errors=errors or [],
    )


def test_task_completion_rate():
    metadata = _execution_metadata(
        agent_runs=[_agent_run("planner"), _agent_run("researcher", errors=["timeout"])]
    )
    assert metrics.task_completion_rate(metadata) == 0.5


def test_tool_success_rate_only_over_runs_with_tool_calls():
    metadata = _execution_metadata(
        agent_runs=[
            _agent_run("planner"),  # no tool calls -- excluded
            _agent_run("researcher", tool_calls=["search"]),
            _agent_run("fact_checker", tool_calls=["search"], errors=["failed"]),
        ]
    )
    assert metrics.tool_success_rate(metadata) == 0.5


def test_average_iterations_ratio_of_max():
    metadata = _execution_metadata(verification_cycles_used=2)
    assert metrics.average_iterations(metadata, max_cycles=4) == 0.5


def test_failure_recovery_rate_completed_after_agent_error():
    metadata = _execution_metadata(status="completed", agent_runs=[_agent_run("researcher", errors=["retry ok"])])
    assert metrics.failure_recovery_rate(metadata) == 1.0


def test_failure_recovery_rate_none_when_nothing_failed():
    metadata = _execution_metadata(status="completed", agent_runs=[_agent_run("researcher")])
    assert metrics.failure_recovery_rate(metadata) is None


# ---------------------------------------------------------------------------
# Decision quality metrics
# ---------------------------------------------------------------------------


def test_criterion_coverage_all_alternatives_scored():
    criteria = [
        DecisionCriteria(name="cost", description="", weight=0.5, direction="minimize", scoring_method="weighted_score"),
        DecisionCriteria(name="speed", description="", weight=0.5, direction="maximize", scoring_method="weighted_score"),
    ]
    scores = [
        AlternativeScore(alternative="A", criterion="cost", score=1, rationale="r"),
        AlternativeScore(alternative="B", criterion="cost", score=2, rationale="r"),
        AlternativeScore(alternative="A", criterion="speed", score=1, rationale="r"),
        # "speed"/"B" missing -> not fully covered
    ]
    matrix = DecisionMatrix(criteria=criteria, scores=scores, weighted_totals={"A": 1, "B": 1}, recommended="A")
    state = ResearchState(request=_request(), decision_matrix=matrix, execution_metadata=_execution_metadata())
    assert metrics.criterion_coverage(state) == 0.5


def test_sensitivity_flag_rate():
    matrix = DecisionMatrix(
        criteria=[], scores=[], weighted_totals={}, recommended="A",
        sensitivity=[
            SensitivityResult(criterion="cost", weight_delta=0.2, recommendation_changed=True),
            SensitivityResult(criterion="speed", weight_delta=0.2, recommendation_changed=False),
        ],
    )
    state = ResearchState(request=_request(), decision_matrix=matrix, execution_metadata=_execution_metadata())
    assert metrics.sensitivity_flag_rate(state) == 0.5


def test_consistency_requires_multiple_runs():
    assert metrics.consistency(["A"]) is None
    assert metrics.consistency(["A", "A", "B"]) == 2 / 3


# ---------------------------------------------------------------------------
# System metrics
# ---------------------------------------------------------------------------


def test_latency_totals():
    metadata = _execution_metadata(
        started_at=_NOW, completed_at=_NOW + timedelta(seconds=1),
        agent_runs=[_agent_run("planner", tokens=1), _agent_run("planner", tokens=1)],
    )
    result = metrics.latency(metadata)
    assert result["total_ms"] == 1000.0
    assert result["by_agent_ms"]["planner"] == 200.0


def test_token_usage_per_agent():
    metadata = _execution_metadata(
        total_tokens=30,
        agent_runs=[_agent_run("planner", tokens=10), _agent_run("researcher", tokens=20)],
    )
    usage = metrics.token_usage(metadata)
    assert usage["total_tokens"] == 30
    assert usage["planner"] == 10
    assert usage["researcher"] == 20


def test_cost_per_task():
    metadata = _execution_metadata(total_tokens=2000)
    assert metrics.cost_per_task(metadata, cost_per_1k_tokens=0.01) == 0.02


def test_success_rate():
    assert metrics.success_rate(["completed", "completed", "failed"]) == 2 / 3
    assert metrics.success_rate([]) == 0.0
