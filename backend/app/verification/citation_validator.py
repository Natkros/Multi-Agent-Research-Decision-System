"""Citation validation helper for the Verification Gate (brief §5.13,
docs/risk-register.md R1: "LLM hallucinated citation").

Pure functions, no LLM/IO — cross-checking a `FinalReport`'s citation
markers and evidence source ids against `state.sources` is exactly the kind
of thing state-schema.md says the gate must do in code, not by asking the
model to grade its own homework.
"""

from __future__ import annotations

from app.schemas.state import FinalReport


def unresolved_citations(report: FinalReport) -> list[str]:
    """Citation markers (`report.citations`) whose target source id is not
    in `report.sources`."""
    source_ids = {s.id for s in report.sources}
    return [
        f"citation {marker!r} references unknown source_id {source_id!r}"
        for marker, source_id in report.citations.items()
        if source_id not in source_ids
    ]


def unresolved_evidence_sources(report: FinalReport) -> list[str]:
    """Evidence items whose `source_id` is not in `report.sources` — a
    claim's supporting evidence must trace back to a real retrieved
    source (state-schema.md's traceability invariant)."""
    source_ids = {s.id for s in report.sources}
    return [
        f"evidence {item.id!r} cites unresolved source_id {item.source_id!r}"
        for item in report.evidence
        if item.source_id not in source_ids
    ]


def validate_citations(report: FinalReport) -> list[str]:
    """All citation-related problems, empty if every citation and every
    piece of evidence resolves to a real source."""
    return unresolved_citations(report) + unresolved_evidence_sources(report)
