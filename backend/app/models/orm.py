"""SQLAlchemy 2.x async ORM models (Phase 3/4, docs/database-schema.md).

Mirrors the documented ER diagram table-for-table for
`research_sessions`/`research_plans`/`alternatives`/`criteria`/`sources`/
`documents`/`claims`/`evidence`/`contradictions`/`agent_runs`/`reports`/
`citations`/`audit_logs`/`risks`/`assumptions`/`decision_scores`. `users`
remains intentionally omitted (Phase 4 brief: "skip `users` still").

Two deliberate deviations from the doc, called out in CHANGELOG.md:

1. Application-assigned ids (`sources.id`, `documents.id`/claims/evidence/
   contradictions ids, `research_questions`) are plain agent-generated
   strings (e.g. `"src-rq-1-0"`), not UUIDs — every agent module already
   mints them this way (see `app/agents/researcher.py`) and re-minting them
   as UUIDs at the persistence boundary would break the traceability
   invariant (state-schema.md) that an id an agent emits is the same id
   downstream agents/tests reference. Rows that the *database* mints
   (sessions, plans, alternatives, criteria, agent_runs, reports, citations,
   audit_logs) keep UUID primary keys as documented.
2. `research_sessions.state_snapshot` (JSON) is not in the documented ER
   diagram. It holds the full validated `ResearchState` so
   `SessionRepository.get()` can reconstruct an exact `ResearchState`
   without hand-writing a bidirectional ORM<->Pydantic mapper for every
   nested type; the normalized tables below are still fully populated on
   every write for querying/audit/reporting, so nothing here is a shortcut
   around persistence, just around *reconstruction*.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class UserORM(Base):
    """Phase 8 (docs/database-schema.md `users`, brief §14/§27). Password is
    never stored in cleartext -- only a bcrypt hash (`app/security/auth.py`)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_users_email", "email", unique=True),)


class ResearchSessionORM(Base):
    __tablename__ = "research_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False, default="auto")
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trace_id: Mapped[str] = mapped_column(String, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Deviation (2) above.
    state_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_research_sessions_user_status", "user_id", "status"),
        Index("ix_research_sessions_trace_id", "trace_id"),
    )


class ResearchPlanORM(Base):
    __tablename__ = "research_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_sessions.id"), nullable=False, unique=True
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    decision_type: Mapped[str] = mapped_column(String, nullable=False)
    constraints: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    alternatives: Mapped[list[AlternativeORM]] = relationship(cascade="all, delete-orphan")
    criteria: Mapped[list[CriterionORM]] = relationship(cascade="all, delete-orphan")


class AlternativeORM(Base):
    __tablename__ = "alternatives"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_plans.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class CriterionORM(Base):
    __tablename__ = "criteria"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("research_plans.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    scoring_method: Mapped[str] = mapped_column(String, nullable=False)


class SourceORM(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # deviation (1) above
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    credibility_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Documented as the dedup key (docs/database-schema.md); not declared
    # unique at the DB level because two independent research sessions can
    # legitimately retrieve byte-identical content (e.g. the offline
    # `LocalSearchProvider`'s canned snippets) under different
    # agent-assigned `id`s — cross-session dedup is app-level future work,
    # not something a hard uniqueness constraint should crash a run over.
    content_hash: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (Index("ix_sources_content_hash", "content_hash"),)


class DocumentORM(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.id"), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_sessions.id"), nullable=False
    )
    relevant_passage: Mapped[str] = mapped_column(Text, nullable=False, default="")
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    research_question_id: Mapped[str | None] = mapped_column(String, nullable=True)


class ClaimORM(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # deviation (1) above
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_sessions.id"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.id"), nullable=False)
    research_question_id: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    verification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verification_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_claims_session_status", "session_id", "status"),)


class EvidenceORM(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # deviation (1) above
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.id"), nullable=False)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_type: Mapped[str] = mapped_column(String, nullable=False)
    strength: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_evidence_claim_id", "claim_id"),)


class ContradictionORM(Base):
    __tablename__ = "contradictions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # deviation (1) above
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_sessions.id"), nullable=False
    )
    claim_a_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"), nullable=False)
    claim_b_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"), nullable=False)
    conflict_type: Mapped[str] = mapped_column(String, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolution_status: Mapped[str] = mapped_column(String, nullable=False, default="unresolved")

    __table_args__ = (
        Index("ix_contradictions_session_resolution", "session_id", "resolution_status"),
    )


class AgentRunORM(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_sessions.id"), nullable=False
    )
    # `agents` (name/version/config registry) is out of scope for Phase 3;
    # the agent's name is stored directly rather than via an `agent_id` FK.
    agent_name: Mapped[str] = mapped_column(String, nullable=False)
    trace_id: Mapped[str] = mapped_column(String, nullable=False)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_runs.id"), nullable=True
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="success")
    input_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_agent_runs_session_agent", "session_id", "agent_name"),
        Index("ix_agent_runs_trace_id", "trace_id"),
    )


class ReportORM(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_sessions.id"), nullable=False, unique=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    citations: Mapped[list[CitationORM]] = relationship(cascade="all, delete-orphan")


class CitationORM(Base):
    __tablename__ = "citations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    report_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("reports.id"), nullable=False)
    marker: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.id"), nullable=False)


class RiskORM(Base):
    __tablename__ = "risks"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # deviation (1) above
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_sessions.id"), nullable=False
    )
    category: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    probability: Mapped[str] = mapped_column(String, nullable=False)
    impact: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mitigation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (Index("ix_risks_session_id", "session_id"),)


class AssumptionORM(Base):
    __tablename__ = "assumptions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # deviation (1) above
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_sessions.id"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    origin: Mapped[str] = mapped_column(String, nullable=False)
    affects: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (Index("ix_assumptions_session_id", "session_id"),)


class DecisionScoreORM(Base):
    __tablename__ = "decision_scores"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_sessions.id"), nullable=False
    )
    # `alternatives`/`criteria` rows are recreated per plan update (see
    # SessionRepository._upsert_plan) and only carry a `name`, not a stable
    # agent-minted id — so these FKs are resolved by (plan_id, name) lookup
    # at persistence time rather than being echoed back from the agent, the
    # same "app resolves the id, never trusts it verbatim" rule as sources/
    # claims/evidence elsewhere in this module.
    alternative_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("alternatives.id"), nullable=True
    )
    criterion_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("criteria.id"), nullable=True
    )
    alternative_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    criterion_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (Index("ix_decision_scores_session_id", "session_id"),)


class JobORM(Base):
    """Durable background-job record (Phase 6, brief §6: research runs must
    survive an API process restart). Deliberately separate from
    `research_sessions` rather than reusing its `status` column: a job is an
    *execution* record (attempts, worker-visible pending/running/completed/
    failed lifecycle) while a session is the *research* record — a future
    job type that isn't "run this research session" (e.g. a batch re-index)
    would have nowhere to live if the two were merged."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_jobs_status", "status"),)


class AuditLogORM(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_sessions.id"), nullable=False
    )
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_audit_logs_session_created", "session_id", "created_at"),)
