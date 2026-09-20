"""Shared typed state, implementing docs/state-schema.md verbatim.

All inter-agent communication flows through `ResearchState`. No agent
receives or returns a bare dict. These are the Phase 0 schema contracts,
made concrete here so Phase 1's single-agent flow (and later phases'
LangGraph nodes) build against a stable, validated shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    id: UUID
    question: str
    constraints: list[str] = Field(default_factory=list)
    alternatives_hint: list[str] = Field(default_factory=list)
    criteria_hint: list[str] = Field(default_factory=list)
    mode: Literal["auto", "assisted", "manual"] = "auto"
    requested_by: str
    created_at: datetime


class DecisionCriteria(BaseModel):
    name: str
    description: str
    weight: float
    direction: Literal["maximize", "minimize"]
    scoring_method: Literal["weighted_score", "threshold", "cost_benefit"]


class ResearchQuestion(BaseModel):
    id: str
    text: str
    dimension: str
    priority: Literal["high", "medium", "low"]


class ResearchPlan(BaseModel):
    objective: str
    decision_type: Literal[
        "technology_selection", "architecture", "vendor", "build_vs_buy",
        "strategic", "other",
    ]
    alternatives: list[str]
    criteria: list[DecisionCriteria]
    research_questions: list[ResearchQuestion]
    required_evidence: list[str]
    constraints: list[str]
    assumptions: list[str]


class RetrievedDocument(BaseModel):
    source_id: str
    title: str
    url: str | None
    source_type: Literal[
        "official_docs", "paper", "government", "standard", "vendor_docs",
        "blog", "forum", "news", "internal_kb",
    ]
    retrieved_at: datetime
    relevant_passage: str
    claims: list[str]
    relevance_score: float


class Source(BaseModel):
    id: str
    title: str
    url: str | None
    publisher: str | None
    author: str | None
    published_at: datetime | None
    retrieved_at: datetime
    source_type: str
    credibility_score: float
    content_hash: str


class Claim(BaseModel):
    id: str
    text: str
    source_id: str
    research_question_id: str


class ClaimVerification(BaseModel):
    claim_id: str
    status: Literal[
        "VERIFIED", "PARTIALLY_VERIFIED", "CONTRADICTED", "UNSUPPORTED",
        "OUTDATED",
    ]
    supporting_sources: list[str]
    contradicting_sources: list[str]
    confidence: float
    explanation: str


class EvidenceItem(BaseModel):
    id: str
    claim_id: str
    evidence_text: str
    source_id: str
    evidence_type: Literal[
        "quantitative", "qualitative", "benchmark", "documentation",
        "expert_analysis", "empirical_observation", "policy_regulatory",
        "user_provided",
    ]
    strength: Literal["strong", "moderate", "weak"]
    confidence: float
    limitations: str | None = None


class Conflict(BaseModel):
    id: str
    claim_a_id: str
    claim_b_id: str
    conflict_type: Literal[
        "genuine", "context_mismatch", "version_mismatch", "temporal",
        "workload_mismatch", "environment_mismatch",
    ]
    explanation: str
    resolution_status: Literal[
        "unresolved", "resolved_context", "resolved_favor_a",
        "resolved_favor_b", "irreconcilable",
    ]


class Assumption(BaseModel):
    id: str
    text: str
    origin: Literal["user_provided", "evidence_backed", "inferred", "hypothetical"]
    affects: list[str] = Field(default_factory=list)


class Risk(BaseModel):
    id: str
    category: Literal[
        "technical", "financial", "security", "operational", "regulatory",
        "vendor", "scalability", "execution", "unknown",
    ]
    description: str
    probability: Literal["low", "medium", "high"]
    impact: Literal["low", "medium", "high"]
    severity: float
    mitigation: str
    evidence_ids: list[str] = Field(default_factory=list)


class AlternativeScore(BaseModel):
    alternative: str
    criterion: str
    score: float
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)


class SensitivityResult(BaseModel):
    criterion: str
    weight_delta: float
    recommendation_changed: bool
    new_recommended: str | None = None


class DecisionMatrix(BaseModel):
    criteria: list[DecisionCriteria]
    scores: list[AlternativeScore]
    weighted_totals: dict[str, float]
    recommended: str
    sensitivity: list[SensitivityResult] = Field(default_factory=list)


class DebateNote(BaseModel):
    """One entry from the Advocate/Critic pass (Phase 4, brief §5.6).

    `role` marks which pass produced it. A critic note attacks a specific
    advocate note via `target_note_id` where possible, and must always carry
    a non-empty `rationale` — the brief requires every criticism to be
    justified with evidence/reasoning, never a bare disagreement.
    """

    id: str
    role: Literal["advocate", "critic"]
    alternative: str | None = None  # None = applies across alternatives
    claim: str
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    target_note_id: str | None = None  # set on critic notes attacking an advocate note


class VerificationResult(BaseModel):
    cycle: int
    passed: bool
    failed_checks: list[str] = Field(default_factory=list)
    routed_to: str | None = None


class AgentRunMeta(BaseModel):
    agent_name: str
    trace_id: str
    start_time: datetime
    end_time: datetime
    latency_ms: int
    tokens: int
    model: str
    tool_calls: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    confidence: float | None = None


class ExecutionMetadata(BaseModel):
    trace_id: str
    session_id: UUID
    started_at: datetime
    completed_at: datetime | None = None
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    agent_runs: list[AgentRunMeta] = Field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    verification_cycles_used: int = 0


class FinalReport(BaseModel):
    executive_summary: str
    research_question: str
    decision_context: str
    alternatives: list[str]
    criteria: list[DecisionCriteria]
    key_findings: list[str]
    evidence: list[EvidenceItem]
    contradictions: list[Conflict]
    comparative_analysis: DecisionMatrix
    risk_analysis: list[Risk]
    assumptions: list[Assumption]
    decision_rationale: str
    confidence: float
    limitations: list[str]
    sources: list[Source]
    citations: dict[str, str] = Field(default_factory=dict)


class ResearchState(BaseModel):
    request: ResearchRequest
    plan: ResearchPlan | None = None
    retrieved_documents: list[RetrievedDocument] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    verified_claims: list[ClaimVerification] = Field(default_factory=list)
    contradictions: list[Conflict] = Field(default_factory=list)
    debate_notes: list[DebateNote] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    decision_matrix: DecisionMatrix | None = None
    draft_report: FinalReport | None = None
    verification_results: list[VerificationResult] = Field(default_factory=list)
    final_report: FinalReport | None = None
    execution_metadata: ExecutionMetadata
