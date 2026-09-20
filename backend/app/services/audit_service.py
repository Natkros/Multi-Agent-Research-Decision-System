"""Audit logging (Phase 3, docs/database-schema.md `audit_logs`).

Every agent run and every Verification Gate cycle produces one
`audit_logs` row. This module is the *only* place that writes them — it is
called from the orchestration layer (`ResearchService`, which drives
`run_research_graph`), never from inside an individual agent module, so
audit logging stays centralized instead of scattered across every agent.
"""

from __future__ import annotations

from uuid import UUID

from app.schemas.state import ResearchState
from app.services.session_repository import SessionRepository


async def log_run(repo: SessionRepository, research_id: UUID, state: ResearchState) -> None:
    """Write one audit row per agent run and one per verification cycle,
    recorded from the final `ResearchState` of a completed (or failed)
    orchestration run."""
    for run in state.execution_metadata.agent_runs:
        await repo.record_audit(
            session_id=research_id,
            actor=run.agent_name,
            action="agent_run",
            payload=run.model_dump(mode="json"),
        )

    for result in state.verification_results:
        await repo.record_audit(
            session_id=research_id,
            actor="verification_gate",
            action="verification_cycle",
            payload=result.model_dump(mode="json"),
        )
