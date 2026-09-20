"""Quantitative metric functions (docs/evaluation.md §1).

Every function here is pure: it reads a `ResearchState`/`FinalReport`/
`ExecutionMetadata` (plus, where relevant, a benchmark question's expected
fields) and returns a number or `None` when the metric isn't computable for
that input (e.g. claim-verification accuracy with no `known_evidence`, or
sensitivity with no sensitivity runs). No LLM/network calls happen in this
module — metrics measure what the graph already produced, they never
re-derive it.

`None` (not 0.0) means "not applicable to this question", so aggregation in
`runner.py` can skip it rather than silently dragging an average down.
"""

from __future__ import annotations

from app.evaluation.benchmark import BenchmarkQuestion
from app.schemas.state import ExecutionMetadata, FinalReport, ResearchState
from app.verification.citation_validator import validate_citations

# ---------------------------------------------------------------------------
# Research quality
# ---------------------------------------------------------------------------


def source_relevance(state: ResearchState) -> float | None:
    """Mean `relevance_score` of retrieved documents actually cited in the
    final report (docs/evaluation.md §1 "Source relevance")."""
    report = state.final_report
    if report is None or not report.citations:
        return None
    cited_source_ids = set(report.citations.values())
    scores = [
        doc.relevance_score
        for doc in state.retrieved_documents
        if doc.source_id in cited_source_ids
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def source_diversity(state: ResearchState) -> dict[str, float | int]:
    """Distinct `source_type`/publisher counts, plus a dominance ratio for
    the single most common source type (docs/evaluation.md §1 "Source
    diversity")."""
    sources = state.sources
    if not sources:
        return {"distinct_source_types": 0, "distinct_publishers": 0, "dominant_type_ratio": 0.0}
    type_counts: dict[str, int] = {}
    for s in sources:
        type_counts[s.source_type] = type_counts.get(s.source_type, 0) + 1
    publishers = {s.publisher for s in sources if s.publisher}
    dominant_count = max(type_counts.values())
    return {
        "distinct_source_types": len(type_counts),
        "distinct_publishers": len(publishers),
        "dominant_type_ratio": dominant_count / len(sources),
    }


def evidence_coverage(state: ResearchState) -> float | None:
    """Fraction of `plan.research_questions` with >= 1 linked `EvidenceItem`
    (via `Claim.research_question_id`) (docs/evaluation.md §1)."""
    if state.plan is None or not state.plan.research_questions:
        return None
    claim_to_rq = {c.id: c.research_question_id for c in state.claims}
    covered_rqs = {
        claim_to_rq[e.claim_id] for e in state.evidence if e.claim_id in claim_to_rq
    }
    total = len(state.plan.research_questions)
    covered = sum(1 for q in state.plan.research_questions if q.id in covered_rqs)
    return covered / total


def citation_coverage(report: FinalReport | None) -> float | None:
    """Approximates "fraction of factual sentences with a resolvable
    citation" by fraction of `key_findings` covered by at least one citation
    marker (docs/evaluation.md §1 "Citation coverage"). The report doesn't
    carry per-sentence citation spans, so `key_findings` (one factual
    statement each) is the finest granularity available without adding new
    schema fields."""
    if report is None or not report.key_findings:
        return None
    if not report.citations:
        return 0.0
    return min(1.0, len(report.citations) / len(report.key_findings))


def claim_verification_accuracy(
    state: ResearchState, question: BenchmarkQuestion
) -> float | None:
    """Fraction of `known_evidence` items whose matched claim's
    `ClaimVerification.status` equals the expected label (docs/evaluation.md
    §1 "Claim verification accuracy"). Matching is case-insensitive substring
    of `known_evidence[i].text` against `Claim.text`. Returns `None` when the
    question has no `known_evidence` or none of it matches an extracted
    claim -- there is no ground truth to score against."""
    if not question.known_evidence:
        return None
    verification_by_claim = {v.claim_id: v.status for v in state.verified_claims}
    matched = 0
    correct = 0
    for known in question.known_evidence:
        needle = known.text.lower()
        match = next((c for c in state.claims if needle in c.text.lower()), None)
        if match is None:
            continue
        matched += 1
        status = verification_by_claim.get(match.id)
        if status == known.expected_status:
            correct += 1
    if matched == 0:
        return None
    return correct / matched


# ---------------------------------------------------------------------------
# Agent quality
# ---------------------------------------------------------------------------


def task_completion_rate(execution_metadata: ExecutionMetadata) -> float | None:
    """Fraction of agent runs that returned without recording an error
    (docs/evaluation.md §1 "Task completion rate"). An entry only ever
    appears in `agent_runs` once its node returned a schema-valid output, so
    `errors` empty is the signal a run completed cleanly rather than via a
    retry/fallback path."""
    runs = execution_metadata.agent_runs
    if not runs:
        return None
    clean = sum(1 for r in runs if not r.errors)
    return clean / len(runs)


def tool_success_rate(execution_metadata: ExecutionMetadata) -> float | None:
    """Fraction of agent runs that made >=1 tool call and recorded no error
    (docs/evaluation.md §1 "Tool success rate"). `AgentRunMeta` doesn't carry
    per-tool-call outcomes, so this is a per-run proxy: a run that called
    tools and finished error-free is treated as its tool calls having
    succeeded."""
    tool_runs = [r for r in execution_metadata.agent_runs if r.tool_calls]
    if not tool_runs:
        return None
    return sum(1 for r in tool_runs if not r.errors) / len(tool_runs)


def hallucination_rate(report: FinalReport | None) -> float | None:
    """Fraction of citation markers that don't resolve to a real `Source` or
    whose evidence doesn't trace back to a real source (docs/evaluation.md
    §1 "Hallucination rate"), reusing the Phase 8 citation validator rather
    than re-implementing the check."""
    if report is None:
        return None
    total = len(report.citations) + len(report.evidence)
    if total == 0:
        return None
    unresolved = validate_citations(report)
    return len(unresolved) / total


def average_iterations(execution_metadata: ExecutionMetadata, *, max_cycles: int) -> float:
    """Verification cycles actually used for this run vs. the configured max
    (docs/evaluation.md §1 "Average iterations" -- computed per-run here,
    averaged across runs by the harness)."""
    if max_cycles <= 0:
        return 0.0
    return execution_metadata.verification_cycles_used / max_cycles


def failure_recovery_rate(execution_metadata: ExecutionMetadata) -> float | None:
    """Whether this run recovered from an in-flight agent error rather than
    propagating to a hard failure (docs/evaluation.md §1 "Failure recovery
    rate"). `None` when nothing failed during the run -- there was nothing to
    recover from."""
    any_agent_error = any(r.errors for r in execution_metadata.agent_runs)
    if not any_agent_error and execution_metadata.status != "failed":
        return None
    return 1.0 if execution_metadata.status == "completed" else 0.0


# ---------------------------------------------------------------------------
# Decision quality
# ---------------------------------------------------------------------------


def criterion_coverage(state: ResearchState) -> float | None:
    """Fraction of planner-identified criteria that receive a score for
    every alternative -- no silently-dropped criteria (docs/evaluation.md §1
    "Criterion coverage")."""
    matrix = state.decision_matrix
    if matrix is None or not matrix.criteria or not matrix.scores:
        return None
    alternatives = {s.alternative for s in matrix.scores}
    if not alternatives:
        return None
    scored_pairs = {(s.criterion, s.alternative) for s in matrix.scores}
    fully_covered = sum(
        1
        for criterion in matrix.criteria
        if all((criterion.name, alt) in scored_pairs for alt in alternatives)
    )
    return fully_covered / len(matrix.criteria)


def consistency(rankings: list[str | None]) -> float | None:
    """Fraction of re-runs (same question, temperature 0) that agree with the
    first run's recommended alternative (docs/evaluation.md §1
    "Consistency"). Requires re-running the question multiple times, which a
    single-pass harness run does not do by default -- callers pass a
    single-element list (or skip the metric entirely) unless they've
    explicitly re-run the question, matching evaluation.md's note that this
    metric is optional/skippable in a single-pass run."""
    if len(rankings) < 2:
        return None
    baseline = rankings[0]
    return sum(1 for r in rankings if r == baseline) / len(rankings)


def sensitivity_flag_rate(state: ResearchState) -> float | None:
    """Fraction of sensitivity checks where the recommendation flips under a
    plausible weight change (docs/evaluation.md §1 "Sensitivity"). `None`
    when no sensitivity checks ran at all."""
    matrix = state.decision_matrix
    if matrix is None or not matrix.sensitivity:
        return None
    flipped = sum(1 for s in matrix.sensitivity if s.recommendation_changed)
    return flipped / len(matrix.sensitivity)


def evidence_to_claim_ratio(state: ResearchState) -> float | None:
    """Mean `EvidenceItem` count per `Claim` (docs/evaluation.md §1
    "Evidence-to-claim ratio")."""
    if not state.claims:
        return None
    return len(state.evidence) / len(state.claims)


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


def latency(execution_metadata: ExecutionMetadata) -> dict[str, float | dict[str, float]]:
    """End-to-end wall clock plus per-agent breakdown, in milliseconds
    (docs/evaluation.md §1 "Latency")."""
    total_ms = 0.0
    if execution_metadata.completed_at is not None:
        total_ms = (
            execution_metadata.completed_at - execution_metadata.started_at
        ).total_seconds() * 1000
    per_agent: dict[str, float] = {}
    for run in execution_metadata.agent_runs:
        per_agent[run.agent_name] = per_agent.get(run.agent_name, 0.0) + run.latency_ms
    return {"total_ms": total_ms, "by_agent_ms": per_agent}


def token_usage(execution_metadata: ExecutionMetadata) -> dict[str, int]:
    """Total tokens plus a per-agent breakdown (docs/evaluation.md §1 "Token
    usage"). Tokens aren't tagged with a model tier on `AgentRunMeta`, so the
    breakdown is per-agent (each agent is pinned to one tier in
    `orchestration/graph.py`), which is an equally useful proxy."""
    per_agent: dict[str, int] = {}
    for run in execution_metadata.agent_runs:
        per_agent[run.agent_name] = per_agent.get(run.agent_name, 0) + run.tokens
    return {"total_tokens": execution_metadata.total_tokens, **per_agent}


def cost_per_task(execution_metadata: ExecutionMetadata, *, cost_per_1k_tokens: float = 0.01) -> float:
    """Token-based cost estimate for one research run (docs/evaluation.md §1
    "Cost per research task"). `cost_per_1k_tokens` is a caller-supplied
    blended rate -- this module has no pricing table, it just does the
    arithmetic against whatever rate the caller believes reflects its
    provider mix."""
    return (execution_metadata.total_tokens / 1000.0) * cost_per_1k_tokens


def success_rate(statuses: list[str]) -> float:
    """Fraction of research runs reaching `completed` without hitting the
    verification-cycle ceiling as a hard failure or crashing (docs/
    evaluation.md §1 "Success rate")."""
    if not statuses:
        return 0.0
    return sum(1 for s in statuses if s == "completed") / len(statuses)
