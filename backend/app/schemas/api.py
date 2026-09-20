"""Request/response models for the public API (docs/api.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.state import (
    Claim,
    ClaimVerification,
    DecisionMatrix,
    EvidenceItem,
    ExecutionMetadata,
    FinalReport,
    Source,
)

# Ordered pipeline stages (docs/architecture.md §3-4, orchestration/graph.py).
# Used to compute a human-readable `stage`/`progress` for the status endpoint
# and to drive the Agent Trace UI / stage indicator on the frontend without
# duplicating this ordering there.
PIPELINE_STAGES: list[str] = [
    "research_planner",
    "researcher",
    "source_evaluator",
    "evidence_analyst",
    "fact_checker",
    "contradiction_detector",
    "debate",
    "assumption_analyst",
    "decision_analyst",
    "risk_analyst",
    "final_synthesizer",
    "verification_gate",
]


class ResearchCreateRequest(BaseModel):
    question: str
    constraints: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    criteria: list[str] = Field(default_factory=list)
    mode: Literal["auto", "assisted", "manual"] = "auto"


class ResearchCreateResponse(BaseModel):
    research_id: UUID
    status: Literal["pending"] = "pending"


class ResearchProgress(BaseModel):
    completed_stages: int
    total_stages: int


class ResearchStatusResponse(BaseModel):
    research_id: UUID
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    error: str | None = None
    report: FinalReport | None = None
    # Phase 7 additions: cheap to derive from `execution_metadata.agent_runs`
    # (already persisted), needed by the Active Research page to render a
    # stage indicator without SSE.
    stage: str | None = None
    progress: ResearchProgress | None = None
    question: str | None = None
    created_at: datetime | None = None


class ResearchListItem(BaseModel):
    """One row for the Dashboard's research-session list. Deliberately a
    summary, not the full `ResearchState` — the list endpoint stays cheap
    even with many sessions."""

    research_id: UUID
    question: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    mode: Literal["auto", "assisted", "manual"]
    created_at: datetime
    completed_at: datetime | None = None
    stage: str | None = None
    confidence: float | None = None
    num_sources: int = 0
    num_risks: int = 0


class ResearchListResponse(BaseModel):
    items: list[ResearchListItem]


class SourcesResponse(BaseModel):
    sources: list[Source]


class ClaimWithVerification(BaseModel):
    claim: Claim
    verification: ClaimVerification | None = None


class ClaimsResponse(BaseModel):
    claims: list[ClaimWithVerification]


class EvidenceResponse(BaseModel):
    evidence: list[EvidenceItem]


class DecisionResponse(BaseModel):
    decision_matrix: DecisionMatrix


class TraceResponse(BaseModel):
    execution_metadata: ExecutionMetadata
    stages: list[str] = Field(default_factory=lambda: list(PIPELINE_STAGES))


class ErrorDetail(BaseModel):
    code: str
    message: str
    trace_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
