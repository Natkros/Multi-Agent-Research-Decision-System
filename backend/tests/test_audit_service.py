"""Audit logging tests (Phase 3, docs/database-schema.md `audit_logs`)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.config.settings import Settings
from app.models.orm import AuditLogORM
from app.schemas.state import (
    AgentRunMeta,
    ExecutionMetadata,
    ResearchRequest,
    ResearchState,
    VerificationResult,
)
from app.services import audit_service
from app.services.session_repository import ResearchSession, SessionRepository


async def test_log_run_writes_one_row_per_agent_run_and_per_verification_cycle() -> None:
    repo = SessionRepository(Settings(database_url=None))
    research_id = uuid4()
    now = datetime.now(UTC)
    request = ResearchRequest(
        id=research_id, question="Q", requested_by="test-user", created_at=now
    )
    agent_runs = [
        AgentRunMeta(
            agent_name=name, trace_id=f"trace-{research_id}", start_time=now, end_time=now,
            latency_ms=1, tokens=1, model="local", tool_calls=[], errors=[], confidence=None,
        )
        for name in ["research_planner", "researcher", "source_evaluator"]
    ]
    verification_results = [
        VerificationResult(cycle=1, passed=False, failed_checks=["x"], routed_to="fact_checker"),
        VerificationResult(cycle=2, passed=True, failed_checks=[], routed_to=None),
    ]
    metadata = ExecutionMetadata(
        trace_id=f"trace-{research_id}", session_id=research_id, started_at=now,
        completed_at=now, status="completed", agent_runs=agent_runs, total_tokens=3,
        verification_cycles_used=2,
    )
    state = ResearchState(
        request=request, verification_results=verification_results, execution_metadata=metadata
    )
    await repo.update(ResearchSession(research_id=research_id, status="completed", state=state))

    await audit_service.log_run(repo, research_id, state)

    async with repo._sessionmaker() as db:  # noqa: SLF001
        rows = (
            await db.execute(select(AuditLogORM).where(AuditLogORM.session_id == research_id))
        ).scalars().all()

    assert len(rows) == len(agent_runs) + len(verification_results)
    actions = {row.action for row in rows}
    assert actions == {"agent_run", "verification_cycle"}
    agent_actors = {row.actor for row in rows if row.action == "agent_run"}
    assert agent_actors == {"research_planner", "researcher", "source_evaluator"}
