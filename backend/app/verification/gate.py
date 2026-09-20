"""Verification Gate (docs/architecture.md §3/§4, brief §5.13).

Reads: draft_report, ResearchState (sources/contradictions/verified_claims).
Writes: verification_results. Tools: citation-validator helper only. Max:
3 cycles, 30s/cycle (wall-clock timeout is Phase 6). Model tier: small/router
— this module makes no LLM calls at all; every check below is deterministic
code, which is the point (a report shouldn't get to grade its own homework).

Four checks, all from the brief:
1. Every citation marker / evidence source id resolves to `state.sources`
   (`citation_validator`, docs/risk-register.md R1).
2. No "major" unsupported claim: any claim the Fact Checker marked
   UNSUPPORTED or CONTRADICTED must be acknowledged somewhere in the
   report's `limitations`, not silently synthesized over.
3. Every contradiction has a `resolution_status` other than fully
   unaddressed (`"unresolved"`) — or is itself listed in `limitations`.
4. Uncertainty is represented: if overall confidence is not high, the
   report must actually say so in `limitations` rather than reporting a
   single clean number with no caveats.

On failure, `VerificationResult.routed_to` says where the retry goes:
`fact_checker` if the failure is about unverified/unsupported claims (that
agent is the one that can actually re-verify them), `final_synthesizer`
for every other failure category (citations/contradictions/uncertainty are
all things the synthesizer controls when assembling the report). The
3-cycle cap is enforced by the *caller* (`app/orchestration/graph.py`)
checking `cycle >= MAX_VERIFICATION_CYCLES` in code — this module only
ever reports what failed, it never loops itself.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.state import ClaimVerification, Conflict, FinalReport, VerificationResult
from app.verification.citation_validator import validate_citations

MAX_VERIFICATION_CYCLES = 3  # hard cap; also read from Settings.verification_max_cycles

_UNSUPPORTED_STATUSES = {"UNSUPPORTED", "CONTRADICTED"}


class VerificationGateInput(BaseModel):
    """Narrowed, read-only view of the state fields the gate needs."""

    report: FinalReport
    contradictions: list[Conflict]
    verified_claims: list[ClaimVerification]
    cycle: int  # 1-based: which cycle this check run is


def _unsupported_claim_failures(
    report: FinalReport, verified_claims: list[ClaimVerification]
) -> list[str]:
    limitations_text = " ".join(report.limitations).lower()
    failures = []
    for verification in verified_claims:
        if verification.status not in _UNSUPPORTED_STATUSES:
            continue
        acknowledged = (
            verification.claim_id.lower() in limitations_text
            or verification.explanation.lower() in limitations_text
        )
        if not acknowledged:
            failures.append(
                f"unsupported major claim {verification.claim_id!r} "
                f"(status={verification.status}) not reflected in limitations"
            )
    return failures


def _unaddressed_contradiction_failures(contradictions: list[Conflict]) -> list[str]:
    return [
        f"contradiction {c.id!r} is unresolved"
        for c in contradictions
        if c.resolution_status == "unresolved"
    ]


def _uncertainty_failures(report: FinalReport) -> list[str]:
    if not (0.0 <= report.confidence <= 1.0):
        return ["report confidence is out of the valid 0-1 range"]
    if report.confidence < 0.7 and not report.limitations:
        return [
            "report confidence is low "
            f"({report.confidence:.2f}) but limitations is empty — uncertainty "
            "must be represented on the report, not just implied by the score"
        ]
    return []


def run_gate(input: VerificationGateInput) -> VerificationResult:
    citation_failures = [f"citation: {msg}" for msg in validate_citations(input.report)]
    claim_failures = [
        f"claim: {msg}"
        for msg in _unsupported_claim_failures(input.report, input.verified_claims)
    ]
    contradiction_failures = [
        f"contradiction: {msg}"
        for msg in _unaddressed_contradiction_failures(input.contradictions)
    ]
    uncertainty_failures = [
        f"confidence: {msg}" for msg in _uncertainty_failures(input.report)
    ]

    failed_checks = (
        citation_failures + claim_failures + contradiction_failures + uncertainty_failures
    )
    passed = not failed_checks

    routed_to: str | None = None
    if not passed:
        # Unsupported/unverified claims are the Fact Checker's to fix;
        # every other failure category is something the Final Synthesizer
        # controls when it assembles the report.
        routed_to = "fact_checker" if claim_failures else "final_synthesizer"

    return VerificationResult(
        cycle=input.cycle, passed=passed, failed_checks=failed_checks, routed_to=routed_to
    )


def apply_cap_reached_limitations(
    report: FinalReport, unresolved_failed_checks: list[str]
) -> FinalReport:
    """Called only when the 3-cycle cap is hit without a passing gate: ship
    the report anyway, but make every unresolved issue visible under
    `limitations` instead of silently dropping them (brief §5.13)."""
    existing = set(report.limitations)
    additions = [
        formatted
        for issue in unresolved_failed_checks
        if (
            formatted := (
                f"Unresolved after {MAX_VERIFICATION_CYCLES} verification cycles: {issue}"
            )
        )
        not in existing
    ]
    if not additions:
        return report
    return report.model_copy(update={"limitations": [*report.limitations, *additions]})
