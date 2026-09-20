"""Verification Gate tests (Phase 3, brief §5.13).

`gate.run_gate` is pure/deterministic (no LLM calls), so these are direct
unit tests of the check logic, plus one graph-level integration test that
proves the 3-cycle cap actually terminates a run rather than looping
forever.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.config.settings import get_settings
from app.orchestration.graph import run_research_graph
from app.schemas.state import (
    ClaimVerification,
    Conflict,
    DecisionMatrix,
    EvidenceItem,
    FinalReport,
    ResearchRequest,
    Source,
)
from app.tools.llm_provider import LocalProvider
from app.tools.search_provider import LocalSearchProvider
from app.verification import citation_validator, gate


def _base_report(**overrides) -> FinalReport:
    now = datetime.now(UTC)
    source = Source(
        id="src-1", title="t1", url=None, publisher="Acme", author=None,
        published_at=now, retrieved_at=now, source_type="vendor_docs",
        credibility_score=0.8, content_hash="h1",
    )
    evidence = EvidenceItem(
        id="ev-1", claim_id="claim-1", evidence_text="X costs $10/mo",
        source_id="src-1", evidence_type="documentation", strength="strong",
        confidence=0.9, limitations=None,
    )
    defaults = dict(
        executive_summary="Summary", research_question="Q", decision_context="ctx",
        alternatives=["A", "B"], criteria=[], key_findings=["X costs $10/mo"],
        evidence=[evidence], contradictions=[],
        comparative_analysis=DecisionMatrix(
            criteria=[], scores=[], weighted_totals={"A": 1.0, "B": 0.5}, recommended="A",
        ),
        risk_analysis=[], assumptions=[], decision_rationale="A is cheaper.",
        confidence=0.85, limitations=[], sources=[source], citations={"[S1]": "src-1"},
    )
    defaults.update(overrides)
    return FinalReport(**defaults)


def test_gate_passes_a_clean_report() -> None:
    report = _base_report()
    verified = [
        ClaimVerification(
            claim_id="claim-1", status="VERIFIED", supporting_sources=["src-1"],
            contradicting_sources=[], confidence=0.9, explanation="corroborated",
        )
    ]
    result = gate.run_gate(
        gate.VerificationGateInput(
            report=report, contradictions=[], verified_claims=verified, cycle=1
        )
    )
    assert result.passed is True
    assert result.failed_checks == []
    assert result.routed_to is None


def test_gate_fails_and_routes_to_synthesizer_on_unresolvable_citation() -> None:
    report = _base_report(citations={"[S1]": "src-1", "[S2]": "src-does-not-exist"})
    result = gate.run_gate(
        gate.VerificationGateInput(report=report, contradictions=[], verified_claims=[], cycle=1)
    )
    assert result.passed is False
    assert any("citation" in check for check in result.failed_checks)
    assert result.routed_to == "final_synthesizer"

    # citation_validator agrees in isolation too.
    assert citation_validator.unresolved_citations(report)
    assert not citation_validator.unresolved_citations(_base_report())


def test_gate_fails_and_routes_to_fact_checker_on_unsupported_claim() -> None:
    report = _base_report()
    verified = [
        ClaimVerification(
            claim_id="claim-1", status="UNSUPPORTED", supporting_sources=[],
            contradicting_sources=[], confidence=0.2,
            explanation="no corroborating source found",
        )
    ]
    result = gate.run_gate(
        gate.VerificationGateInput(
            report=report, contradictions=[], verified_claims=verified, cycle=1
        )
    )
    assert result.passed is False
    assert result.routed_to == "fact_checker"
    assert any("unsupported major claim" in check for check in result.failed_checks)


def test_gate_fails_on_unaddressed_contradiction() -> None:
    report = _base_report()
    conflict = Conflict(
        id="c1", claim_a_id="claim-1", claim_b_id="claim-2", conflict_type="genuine",
        explanation="direct disagreement", resolution_status="unresolved",
    )
    result = gate.run_gate(
        gate.VerificationGateInput(
            report=report, contradictions=[conflict], verified_claims=[], cycle=1
        )
    )
    assert result.passed is False
    assert any("contradiction" in check for check in result.failed_checks)


def test_gate_fails_on_low_confidence_without_limitations() -> None:
    report = _base_report(confidence=0.3, limitations=[])
    result = gate.run_gate(
        gate.VerificationGateInput(report=report, contradictions=[], verified_claims=[], cycle=1)
    )
    assert result.passed is False
    assert any("confidence" in check for check in result.failed_checks)

    # Same low confidence, but uncertainty is actually surfaced -> passes.
    honest_report = _base_report(confidence=0.3, limitations=["Only one source found."])
    honest_result = gate.run_gate(
        gate.VerificationGateInput(
            report=honest_report, contradictions=[], verified_claims=[], cycle=1
        )
    )
    assert honest_result.passed is True


def test_apply_cap_reached_limitations_surfaces_every_unresolved_issue() -> None:
    report = _base_report(limitations=["Pre-existing note."])
    capped = gate.apply_cap_reached_limitations(report, ["citation: bad marker"])
    assert "Pre-existing note." in capped.limitations
    assert any("citation: bad marker" in item for item in capped.limitations)
    # Idempotent: applying again with the same issue doesn't duplicate it.
    capped_again = gate.apply_cap_reached_limitations(capped, ["citation: bad marker"])
    assert len(capped_again.limitations) == len(capped.limitations)


async def test_verification_cycle_cap_terminates_instead_of_looping_forever() -> None:
    """`LocalProvider`'s Fact Checker defaults every claim to UNSUPPORTED
    (no verdict returned), and its synthesized report has confidence 0.0
    with no limitations — a report that can never pass the gate. This
    proves the hard cap in `app/orchestration/graph.py` actually stops the
    run at 3 cycles rather than recursing until LangGraph's recursion
    limit kills it."""
    settings = get_settings()
    request = ResearchRequest(
        id=uuid4(),
        question="Should we build or buy a vector database?",
        alternatives_hint=["Build in-house", "Managed Qdrant"],
        criteria_hint=["cost"],
        requested_by="test-user",
        created_at=datetime.now(UTC),
    )

    state = await run_research_graph(
        request, llm=LocalProvider(), search=LocalSearchProvider(), settings=settings
    )

    assert state.execution_metadata.verification_cycles_used == settings.verification_max_cycles
    assert len(state.verification_results) == settings.verification_max_cycles
    assert all(not r.passed for r in state.verification_results)
    # It still ships a report rather than leaving `final_report` empty.
    assert state.final_report is not None
    assert any(
        "Unresolved after" in item for item in state.final_report.limitations
    )
