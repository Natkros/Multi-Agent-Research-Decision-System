"""Postgres-backed research session store (Phase 3, docs/database-schema.md).

Replaces Phase 1's in-memory dict with a real SQLAlchemy-async repository,
while keeping the exact interface `app/api/research.py` and
`app/services/research_service.py` already depend on: `create()`, `get()`,
`update()`, plus the `ResearchSession`/`SessionStatus` types. Nothing in
either caller needed to change.

`SessionRepository()` takes no required arguments (matching Phase 1's
constructor) and resolves `DATABASE_URL` from `Settings` itself, falling
back to an in-memory sqlite database when it is unset — see
`app/models/database.py` for why that keeps the whole test suite fast and
offline. Each `SessionRepository` instance owns its own engine, so tests
that construct a fresh repository get a fresh, isolated database.

Every `create()`/`update()` call persists the full `ResearchState` (as
`state_snapshot`, see `app/models/orm.py` for why) *and* decomposes it into
the normalized tables from docs/database-schema.md, so the data is queryable
relationally, not just as an opaque blob.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.models.database import create_engine_for_url, init_models, make_sessionmaker
from app.models.orm import (
    AgentRunORM,
    AlternativeORM,
    AssumptionORM,
    AuditLogORM,
    CitationORM,
    ClaimORM,
    ContradictionORM,
    CriterionORM,
    DecisionScoreORM,
    DocumentORM,
    EvidenceORM,
    ReportORM,
    ResearchPlanORM,
    ResearchSessionORM,
    RiskORM,
    SourceORM,
    UserORM,
)
from app.schemas.state import ResearchState

SessionStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class ResearchSession(BaseModel):
    research_id: UUID
    status: SessionStatus
    state: ResearchState
    error: str | None = None


class SessionRepository:
    """Async-safe, Postgres-backed (sqlite-in-tests) store of
    `research_id -> ResearchSession`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._engine = create_engine_for_url(self._settings.effective_database_url)
        self._sessionmaker = make_sessionmaker(self._engine)
        self._init_lock = asyncio.Lock()
        self._initialized = False
        # sqlite (dev/tests, see app/models/database.py) runs on a single
        # shared `StaticPool` connection -- only one logical DB operation can
        # safely be in flight on it at a time. A read (`get`/`list_recent`)
        # racing a write's multi-statement `_upsert_session` transaction on
        # that one connection can observe a partially-written row (Phase 7
        # exposed this: polling GET /research/{id} while a run's agent_runs
        # were still being upserted intermittently returned an empty
        # `sources`/`final_report` even though `status` already read
        # "completed"). Real Postgres uses a normal connection pool with
        # proper transaction isolation and doesn't need this -- the lock is a
        # no-op there (each connection is independent) so it costs nothing
        # in production, it only actually serializes the sqlite path.
        self._db_lock = asyncio.Lock() if self._settings.effective_database_url.startswith("sqlite") else None

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if not self._initialized:
                await init_models(self._engine)
                self._initialized = True

    async def create(self, session: ResearchSession) -> None:
        await self.update(session)

    async def get(self, research_id: UUID) -> ResearchSession | None:
        await self._ensure_initialized()
        if self._db_lock is not None:
            async with self._db_lock:
                return await self._get(research_id)
        return await self._get(research_id)

    async def _get(self, research_id: UUID) -> ResearchSession | None:
        async with self._sessionmaker() as db:
            row = await db.get(ResearchSessionORM, research_id)
            if row is None:
                return None
            return ResearchSession(
                research_id=row.id,
                status=row.status,  # type: ignore[arg-type]
                state=ResearchState.model_validate(row.state_snapshot),
                error=row.error,
            )

    async def list_recent(
        self, *, limit: int = 50, user_id: str | None = None
    ) -> list[ResearchSession]:
        """Phase 7: list sessions newest-first for the Dashboard page. Reads
        the same `state_snapshot` blob `get()` uses, so callers see the exact
        `ResearchState` shape the rest of the app depends on. Phase 8:
        `user_id` restricts the listing to one owner's sessions at the query
        level (used by non-admin callers, docs/architecture.md §14)."""
        await self._ensure_initialized()
        if self._db_lock is not None:
            async with self._db_lock:
                return await self._list_recent(limit=limit, user_id=user_id)
        return await self._list_recent(limit=limit, user_id=user_id)

    async def _list_recent(self, *, limit: int, user_id: str | None = None) -> list[ResearchSession]:
        async with self._sessionmaker() as db:
            stmt = select(ResearchSessionORM).order_by(desc(ResearchSessionORM.created_at)).limit(limit)
            if user_id is not None:
                stmt = stmt.where(ResearchSessionORM.user_id == user_id)
            rows = (await db.execute(stmt)).scalars().all()
            return [
                ResearchSession(
                    research_id=row.id,
                    status=row.status,  # type: ignore[arg-type]
                    state=ResearchState.model_validate(row.state_snapshot),
                    error=row.error,
                )
                for row in rows
            ]

    async def update(self, session: ResearchSession) -> None:
        await self._ensure_initialized()
        if self._db_lock is not None:
            async with self._db_lock:
                return await self._update(session)
        return await self._update(session)

    async def _update(self, session: ResearchSession) -> None:
        async with self._sessionmaker() as db:
            await self._upsert_session(db, session)
            await db.commit()

    async def mark_running_unless_cancelled(self, session: ResearchSession) -> bool:
        """Atomically transition to "running" unless the session was already
        cancelled. Returns whether the write happened.

        `research_service.run()` used to do a plain `get()` then `update()`
        for this first status write, with a real TOCTOU window in between:
        `POST /cancel` landing in that window got silently overwritten back
        to "running" once the background job's write completed. Confirmed
        by this project's first run against real Postgres (sqlite's
        `_db_lock` fully serializes reads/writes, so the race never
        manifested there -- see CHANGELOG Phase 10). `SELECT ... FOR UPDATE`
        closes the window: a concurrent cancel's write blocks on this row
        until we commit or roll back, so our read is never stale.
        """
        await self._ensure_initialized()
        if self._db_lock is not None:
            async with self._db_lock:
                return await self._mark_running_unless_cancelled(session)
        return await self._mark_running_unless_cancelled(session)

    async def _mark_running_unless_cancelled(self, session: ResearchSession) -> bool:
        async with self._sessionmaker() as db:
            # sqlite has no real row locking and `_db_lock` above already
            # serializes every read/write against it, so `with_for_update`
            # is only meaningful (and only supported) against Postgres.
            row = await db.get(
                ResearchSessionORM, session.research_id, with_for_update=self._db_lock is None
            )
            if row is not None and row.status == "cancelled":
                await db.rollback()
                return False
            await self._upsert_session(db, session)
            await db.commit()
            return True

    # -- normalized persistence -------------------------------------------------

    async def _upsert_session(self, db: AsyncSession, session: ResearchSession) -> None:
        state = session.state
        metadata = state.execution_metadata

        row = await db.get(ResearchSessionORM, session.research_id)
        if row is None:
            row = ResearchSessionORM(
                id=session.research_id,
                # Phase 8: populated from the authenticated user
                # (`ResearchRequest.requested_by`, set by
                # `app/api/research.py` from `CurrentUser.id`) instead of
                # staying unused/nullable -- this is what
                # `list_recent(user_id=...)` and the per-endpoint
                # authorization checks in `app/api/research.py` filter on.
                user_id=state.request.requested_by,
                question=state.request.question,
                mode=state.request.mode,
                status=session.status,
                created_at=metadata.started_at,
                trace_id=metadata.trace_id,
            )
            db.add(row)
        row.status = session.status
        row.error = session.error
        row.completed_at = metadata.completed_at
        row.state_snapshot = state.model_dump(mode="json")
        await db.flush()

        # `decision_scores` FK-references `alternatives`/`criteria`, which
        # `_upsert_plan` below deletes and recreates on every call. Deleting
        # the *old* decision_scores rows must happen before that, or
        # `_upsert_plan`'s delete violates the FK against rows a prior
        # `update()` call already committed. SQLite doesn't enforce FKs by
        # default, so this ordering bug was invisible until this project's
        # first run against real Postgres (see CHANGELOG Phase 10).
        await db.execute(delete(DecisionScoreORM).where(DecisionScoreORM.session_id == session.research_id))
        if state.plan is not None:
            await self._upsert_plan(db, session.research_id, state)
        await self._upsert_sources(db, state)
        await self._upsert_documents(db, session.research_id, state)
        await self._upsert_claims(db, session.research_id, state)
        await self._upsert_evidence(db, state)
        await self._upsert_contradictions(db, session.research_id, state)
        await self._upsert_risks(db, session.research_id, state)
        await self._upsert_assumptions(db, session.research_id, state)
        await self._insert_decision_scores(db, session.research_id, state)
        await self._replace_agent_runs(db, session.research_id, metadata.agent_runs)
        if state.final_report is not None:
            await self._upsert_report(db, session.research_id, state)

    async def _upsert_plan(self, db: AsyncSession, session_id: UUID, state: ResearchState) -> None:
        assert state.plan is not None
        plan = state.plan
        existing = (
            await db.execute(
                select(ResearchPlanORM).where(ResearchPlanORM.session_id == session_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = ResearchPlanORM(
                session_id=session_id,
                objective=plan.objective,
                decision_type=plan.decision_type,
                constraints=plan.constraints,
                assumptions=plan.assumptions,
                created_at=datetime.now(UTC),
            )
            db.add(existing)
            await db.flush()
        else:
            existing.objective = plan.objective
            existing.decision_type = plan.decision_type
            existing.constraints = plan.constraints
            existing.assumptions = plan.assumptions
            await db.execute(delete(AlternativeORM).where(AlternativeORM.plan_id == existing.id))
            await db.execute(delete(CriterionORM).where(CriterionORM.plan_id == existing.id))

        for name in plan.alternatives:
            db.add(AlternativeORM(plan_id=existing.id, name=name, description=""))
        for criterion in plan.criteria:
            db.add(
                CriterionORM(
                    plan_id=existing.id,
                    name=criterion.name,
                    description=criterion.description,
                    weight=criterion.weight,
                    direction=criterion.direction,
                    scoring_method=criterion.scoring_method,
                )
            )

    async def _upsert_sources(self, db: AsyncSession, state: ResearchState) -> None:
        for source in state.sources:
            row = await db.get(SourceORM, source.id)
            if row is None:
                db.add(
                    SourceORM(
                        id=source.id,
                        title=source.title,
                        url=source.url,
                        publisher=source.publisher,
                        author=source.author,
                        published_at=source.published_at,
                        retrieved_at=source.retrieved_at,
                        source_type=source.source_type,
                        credibility_score=source.credibility_score,
                        content_hash=source.content_hash,
                    )
                )
            else:
                row.credibility_score = source.credibility_score
                row.title = source.title
        await db.flush()

    async def _upsert_documents(
        self, db: AsyncSession, session_id: UUID, state: ResearchState
    ) -> None:
        await db.execute(delete(DocumentORM).where(DocumentORM.session_id == session_id))
        for doc in state.retrieved_documents:
            db.add(
                DocumentORM(
                    source_id=doc.source_id,
                    session_id=session_id,
                    relevant_passage=doc.relevant_passage,
                    relevance_score=doc.relevance_score,
                    research_question_id=None,
                )
            )

    async def _upsert_claims(self, db: AsyncSession, session_id: UUID, state: ResearchState) -> None:
        # Known limitation: `Claim.id` is minted per-question (e.g.
        # "claim-rq-1-0"), not per-session, so two different sessions that
        # happen to reuse the same research-question id would collide here.
        # Out of scope to fix in Phase 3 without changing the agents' id
        # scheme; noted for a future phase.
        verification_by_claim = {v.claim_id: v for v in state.verified_claims}
        for claim in state.claims:
            verification = verification_by_claim.get(claim.id)
            row = await db.get(ClaimORM, claim.id)
            if row is None:
                row = ClaimORM(
                    id=claim.id,
                    session_id=session_id,
                    source_id=claim.source_id,
                    research_question_id=claim.research_question_id,
                    text=claim.text,
                )
                db.add(row)
            if verification is not None:
                row.status = verification.status
                row.verification_confidence = verification.confidence
                row.verification_explanation = verification.explanation
        await db.flush()

    async def _upsert_evidence(self, db: AsyncSession, state: ResearchState) -> None:
        for item in state.evidence:
            row = await db.get(EvidenceORM, item.id)
            if row is None:
                db.add(
                    EvidenceORM(
                        id=item.id,
                        claim_id=item.claim_id,
                        source_id=item.source_id,
                        evidence_text=item.evidence_text,
                        evidence_type=item.evidence_type,
                        strength=item.strength,
                        confidence=item.confidence,
                        limitations=item.limitations,
                    )
                )
        await db.flush()

    async def _upsert_contradictions(
        self, db: AsyncSession, session_id: UUID, state: ResearchState
    ) -> None:
        await db.execute(delete(ContradictionORM).where(ContradictionORM.session_id == session_id))
        for conflict in state.contradictions:
            db.add(
                ContradictionORM(
                    id=conflict.id,
                    session_id=session_id,
                    claim_a_id=conflict.claim_a_id,
                    claim_b_id=conflict.claim_b_id,
                    conflict_type=conflict.conflict_type,
                    explanation=conflict.explanation,
                    resolution_status=conflict.resolution_status,
                )
            )

    async def _upsert_risks(self, db: AsyncSession, session_id: UUID, state: ResearchState) -> None:
        # Replace-wholesale, same idempotency rule as contradictions: a
        # session's risks are always the full current Risk Analyst output.
        await db.execute(delete(RiskORM).where(RiskORM.session_id == session_id))
        for risk in state.risks:
            db.add(
                RiskORM(
                    id=risk.id,
                    session_id=session_id,
                    category=risk.category,
                    description=risk.description,
                    probability=risk.probability,
                    impact=risk.impact,
                    severity=risk.severity,
                    mitigation=risk.mitigation,
                    evidence_ids=risk.evidence_ids,
                )
            )

    async def _upsert_assumptions(
        self, db: AsyncSession, session_id: UUID, state: ResearchState
    ) -> None:
        await db.execute(delete(AssumptionORM).where(AssumptionORM.session_id == session_id))
        for assumption in state.assumptions:
            db.add(
                AssumptionORM(
                    id=assumption.id,
                    session_id=session_id,
                    text=assumption.text,
                    origin=assumption.origin,
                    affects=assumption.affects,
                )
            )

    async def _insert_decision_scores(
        self, db: AsyncSession, session_id: UUID, state: ResearchState
    ) -> None:
        if state.decision_matrix is None:
            return
        # Stale rows for this session were already deleted earlier in
        # `_upsert_session`, before `_upsert_plan` recreated the
        # alternatives/criteria this insert looks up (see the comment
        # there) -- this method only ever inserts.

        # `alternatives`/`criteria` rows are recreated per plan update
        # (`_upsert_plan`) with only a `name`, not an agent-stable id; look
        # the current plan's rows back up by name so decision_scores can
        # carry a real FK where one exists, without trusting an id the
        # agent never actually had.
        plan_row = (
            await db.execute(
                select(ResearchPlanORM).where(ResearchPlanORM.session_id == session_id)
            )
        ).scalar_one_or_none()
        alt_id_by_name: dict[str, object] = {}
        crit_id_by_name: dict[str, object] = {}
        if plan_row is not None:
            alt_rows = (
                await db.execute(select(AlternativeORM).where(AlternativeORM.plan_id == plan_row.id))
            ).scalars().all()
            alt_id_by_name = {row.name: row.id for row in alt_rows}
            crit_rows = (
                await db.execute(select(CriterionORM).where(CriterionORM.plan_id == plan_row.id))
            ).scalars().all()
            crit_id_by_name = {row.name: row.id for row in crit_rows}

        for score in state.decision_matrix.scores:
            db.add(
                DecisionScoreORM(
                    session_id=session_id,
                    alternative_id=alt_id_by_name.get(score.alternative),
                    criterion_id=crit_id_by_name.get(score.criterion),
                    alternative_name=score.alternative,
                    criterion_name=score.criterion,
                    score=score.score,
                    rationale=score.rationale,
                    evidence_ids=score.evidence_ids,
                )
            )

    async def _replace_agent_runs(self, db: AsyncSession, session_id: UUID, agent_runs) -> None:
        # A session is updated repeatedly (pending -> running -> completed);
        # `agent_runs` is always the full cumulative list at that point, so
        # replacing rather than appending keeps this idempotent.
        await db.execute(delete(AgentRunORM).where(AgentRunORM.session_id == session_id))
        for run in agent_runs:
            db.add(
                AgentRunORM(
                    session_id=session_id,
                    agent_name=run.agent_name,
                    trace_id=run.trace_id,
                    start_time=run.start_time,
                    end_time=run.end_time,
                    latency_ms=run.latency_ms,
                    tokens=run.tokens,
                    model=run.model,
                    status="success" if not run.errors else "retried",
                    error="; ".join(run.errors) if run.errors else None,
                    confidence=run.confidence,
                )
            )

    async def _upsert_report(self, db: AsyncSession, session_id: UUID, state: ResearchState) -> None:
        assert state.final_report is not None
        report = state.final_report
        existing = (
            await db.execute(select(ReportORM).where(ReportORM.session_id == session_id))
        ).scalar_one_or_none()
        if existing is None:
            existing = ReportORM(
                session_id=session_id,
                version=1,
                content=report.model_dump(mode="json"),
                confidence=report.confidence,
                created_at=datetime.now(UTC),
            )
            db.add(existing)
            await db.flush()
        else:
            existing.version += 1
            existing.content = report.model_dump(mode="json")
            existing.confidence = report.confidence
            await db.execute(delete(CitationORM).where(CitationORM.report_id == existing.id))

        for marker, source_id in report.citations.items():
            db.add(CitationORM(report_id=existing.id, marker=marker, source_id=source_id))

    # -- users (Phase 8, docs/database-schema.md `users`) -----------------------
    # Deliberately methods on this repository rather than a second
    # `UserRepository` with its own engine: sqlite's in-memory fallback
    # (`app/models/database.py`) only exists for the lifetime of one
    # connection/engine, so a second engine against the same
    # `sqlite+aiosqlite:///:memory:` URL would silently be a *different*,
    # empty database -- exactly the trap a second repository class would
    # fall into. Reusing this instance's engine keeps users and sessions in
    # the one database the rest of the app already talks to.

    async def create_user(self, *, email: str, hashed_password: str, role: str) -> UserORM:
        await self._ensure_initialized()
        if self._db_lock is not None:
            async with self._db_lock:
                return await self._create_user(email=email, hashed_password=hashed_password, role=role)
        return await self._create_user(email=email, hashed_password=hashed_password, role=role)

    async def _create_user(self, *, email: str, hashed_password: str, role: str) -> UserORM:
        async with self._sessionmaker() as db:
            row = UserORM(
                email=email.lower(),
                hashed_password=hashed_password,
                role=role,
                created_at=datetime.now(UTC),
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row

    async def get_user_by_email(self, email: str) -> UserORM | None:
        await self._ensure_initialized()
        if self._db_lock is not None:
            async with self._db_lock:
                return await self._get_user_by_email(email)
        return await self._get_user_by_email(email)

    async def _get_user_by_email(self, email: str) -> UserORM | None:
        async with self._sessionmaker() as db:
            return (
                await db.execute(select(UserORM).where(UserORM.email == email.lower()))
            ).scalar_one_or_none()

    async def get_user_by_id(self, user_id: UUID) -> UserORM | None:
        await self._ensure_initialized()
        if self._db_lock is not None:
            async with self._db_lock:
                return await self._get_user_by_id(user_id)
        return await self._get_user_by_id(user_id)

    async def _get_user_by_id(self, user_id: UUID) -> UserORM | None:
        async with self._sessionmaker() as db:
            return await db.get(UserORM, user_id)

    async def dispose(self) -> None:
        """Release the underlying engine/connection pool. Not required for
        correctness (sqlite/Postgres both clean up on GC), but production
        callers (e.g. `main.py`'s lifespan) should call this on shutdown to
        close connections deterministically rather than via `ResourceWarning`."""
        await self._engine.dispose()

    async def record_audit(
        self, *, session_id: UUID, actor: str, action: str, payload: dict
    ) -> None:
        """Insert one `audit_logs` row. Called by `app/services/audit_service.py`
        from the orchestration layer only — never from inside an agent."""
        await self._ensure_initialized()
        if self._db_lock is not None:
            async with self._db_lock:
                return await self._record_audit(session_id=session_id, actor=actor, action=action, payload=payload)
        return await self._record_audit(session_id=session_id, actor=actor, action=action, payload=payload)

    async def _record_audit(
        self, *, session_id: UUID, actor: str, action: str, payload: dict
    ) -> None:
        async with self._sessionmaker() as db:
            db.add(
                AuditLogORM(
                    session_id=session_id,
                    actor=actor,
                    action=action,
                    payload=payload,
                    created_at=datetime.now(UTC),
                )
            )
            await db.commit()
