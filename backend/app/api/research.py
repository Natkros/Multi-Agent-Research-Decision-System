"""Research endpoints (docs/api.md). Thin routers only — all logic lives in
`ResearchService`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import (
    get_job_runner,
    get_rate_limiter_dep,
    get_session_repository,
    get_settings_dep,
)
from app.config.settings import Settings
from app.schemas.api import (
    PIPELINE_STAGES,
    ClaimsResponse,
    ClaimWithVerification,
    DecisionResponse,
    EvidenceResponse,
    ResearchCreateRequest,
    ResearchCreateResponse,
    ResearchListItem,
    ResearchListResponse,
    ResearchProgress,
    ResearchStatusResponse,
    SourcesResponse,
    TraceResponse,
)
from app.schemas.state import ExecutionMetadata, ResearchRequest, ResearchState
from app.security.auth import CurrentUser, get_current_user
from app.security.rate_limit import RateLimiter
from app.services.job_runner import JobRunner
from app.services.session_repository import ResearchSession, SessionRepository

router = APIRouter(prefix="/research", tags=["research"])


def _authorize(session: ResearchSession, user: CurrentUser) -> None:
    """Phase 8 authorization (brief §14/§27): a user may only see/cancel
    their own research sessions, unless they are an admin. Enforced here,
    in code, on every read/write endpoint below -- not left to the frontend
    to respect."""
    if user.role == "admin":
        return
    if session.state.request.requested_by != user.id:
        raise HTTPException(status_code=403, detail="FORBIDDEN")


def _current_stage(session: ResearchSession) -> str | None:
    """Derive a human-readable pipeline stage from the agent runs recorded
    so far, matching `orchestration/graph.py`'s node order. Thin, read-only
    projection over already-persisted data -- no new state is introduced."""
    if session.status == "completed":
        return "complete"
    if session.status == "failed":
        return "failed"
    if session.status == "cancelled":
        return "cancelled"
    agent_runs = session.state.execution_metadata.agent_runs
    if not agent_runs:
        return "pending" if session.status == "pending" else "research_planner"
    last_agent = agent_runs[-1].agent_name
    if last_agent in PIPELINE_STAGES:
        idx = PIPELINE_STAGES.index(last_agent)
        if idx + 1 < len(PIPELINE_STAGES):
            return PIPELINE_STAGES[idx + 1]
        return last_agent
    return last_agent


def _progress(session: ResearchSession) -> ResearchProgress:
    completed = len(
        {
            run.agent_name
            for run in session.state.execution_metadata.agent_runs
            if run.agent_name in PIPELINE_STAGES
        }
    )
    if session.status == "completed":
        completed = len(PIPELINE_STAGES)
    return ResearchProgress(completed_stages=completed, total_stages=len(PIPELINE_STAGES))


@router.get("", response_model=ResearchListResponse)
async def list_research(
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ResearchListResponse:
    # Admins see every session; everyone else only ever sees their own
    # (query-level filter, not a client-side/post-hoc one).
    owner_filter = None if current_user.role == "admin" else current_user.id
    sessions = await repo.list_recent(limit=limit, user_id=owner_filter)
    items = [
        ResearchListItem(
            research_id=session.research_id,
            question=session.state.request.question,
            status=session.status,
            mode=session.state.request.mode,
            created_at=session.state.execution_metadata.started_at,
            completed_at=session.state.execution_metadata.completed_at,
            stage=_current_stage(session),
            confidence=(session.state.final_report.confidence if session.state.final_report else None),
            num_sources=len(session.state.sources),
            num_risks=len(session.state.risks),
        )
        for session in sessions
    ]
    return ResearchListResponse(items=items)


@router.post("", response_model=ResearchCreateResponse, status_code=202)
async def create_research(
    payload: ResearchCreateRequest,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    job_runner: Annotated[JobRunner, Depends(get_job_runner)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter_dep)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ResearchCreateResponse:
    # Phase 8: per-user token bucket on the expensive endpoint
    # (docs/api.md "Auth & rate limiting"). Keyed by user id, not IP, so it
    # can't be bypassed by rotating source addresses.
    allowed = await rate_limiter.allow(
        f"research:{current_user.id}",
        capacity=settings.rate_limit_research_capacity,
        refill_per_second=settings.rate_limit_research_refill_per_minute / 60.0,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="RATE_LIMITED")

    research_id = uuid4()
    request = ResearchRequest(
        id=research_id,
        question=payload.question,
        constraints=payload.constraints,
        alternatives_hint=payload.alternatives,
        criteria_hint=payload.criteria,
        mode=payload.mode,
        requested_by=current_user.id,
        created_at=datetime.now(UTC),
    )
    pending_state = ResearchState(
        request=request,
        execution_metadata=ExecutionMetadata(
            trace_id=f"trace-{research_id}",
            session_id=research_id,
            started_at=datetime.now(UTC),
            status="pending",
        ),
    )
    await repo.create(
        ResearchSession(research_id=research_id, status="pending", state=pending_state)
    )

    # Phase 6: route through the durable job runner instead of
    # `BackgroundTasks` (an in-memory-only mechanism — a run in flight when
    # the API process restarts would simply vanish). The job row persists
    # `research_id`; the handler bound in `app/main.py` reloads the request
    # from `repo` and reuses the process's singleton providers.
    await job_runner.enqueue("research_run", {"research_id": str(research_id)})

    return ResearchCreateResponse(research_id=research_id, status="pending")


@router.get("/{research_id}", response_model=ResearchStatusResponse)
async def get_research(
    research_id: UUID,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ResearchStatusResponse:
    session = await repo.get(research_id)
    if session is None:
        raise HTTPException(status_code=404, detail="RESEARCH_NOT_FOUND")
    _authorize(session, current_user)

    return ResearchStatusResponse(
        research_id=session.research_id,
        status=session.status,
        error=session.error,
        report=session.state.final_report,
        stage=_current_stage(session),
        progress=_progress(session),
        question=session.state.request.question,
        created_at=session.state.execution_metadata.started_at,
    )


async def _get_session_or_404(
    research_id: UUID, repo: SessionRepository, current_user: CurrentUser
) -> ResearchSession:
    session = await repo.get(research_id)
    if session is None:
        raise HTTPException(status_code=404, detail="RESEARCH_NOT_FOUND")
    _authorize(session, current_user)
    return session


@router.get("/{research_id}/sources", response_model=SourcesResponse)
async def get_sources(
    research_id: UUID,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SourcesResponse:
    session = await _get_session_or_404(research_id, repo, current_user)
    return SourcesResponse(sources=session.state.sources)


@router.get("/{research_id}/claims", response_model=ClaimsResponse)
async def get_claims(
    research_id: UUID,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ClaimsResponse:
    session = await _get_session_or_404(research_id, repo, current_user)
    verification_by_claim = {v.claim_id: v for v in session.state.verified_claims}
    claims = [
        ClaimWithVerification(claim=claim, verification=verification_by_claim.get(claim.id))
        for claim in session.state.claims
    ]
    return ClaimsResponse(claims=claims)


@router.get("/{research_id}/evidence", response_model=EvidenceResponse)
async def get_evidence(
    research_id: UUID,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    evidence_type: str | None = None,
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
) -> EvidenceResponse:
    session = await _get_session_or_404(research_id, repo, current_user)
    evidence = session.state.evidence
    if evidence_type is not None:
        evidence = [e for e in evidence if e.evidence_type == evidence_type]
    if min_confidence is not None:
        evidence = [e for e in evidence if e.confidence >= min_confidence]
    return EvidenceResponse(evidence=evidence)


@router.get("/{research_id}/decision", response_model=DecisionResponse)
async def get_decision(
    research_id: UUID,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> DecisionResponse:
    session = await _get_session_or_404(research_id, repo, current_user)
    if session.state.decision_matrix is None:
        raise HTTPException(status_code=404, detail="DECISION_MATRIX_NOT_AVAILABLE")
    return DecisionResponse(decision_matrix=session.state.decision_matrix)


@router.get("/{research_id}/trace", response_model=TraceResponse)
async def get_trace(
    research_id: UUID,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> TraceResponse:
    session = await _get_session_or_404(research_id, repo, current_user)
    return TraceResponse(execution_metadata=session.state.execution_metadata)


@router.get("/{research_id}/report", response_model=ResearchStatusResponse)
async def get_report(
    research_id: UUID,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ResearchStatusResponse:
    """Thin alias returning the same payload as the status endpoint, kept
    separate to match docs/api.md's documented `/report` path -- some
    frontend callers want a URL that reads as "give me the report"."""
    session = await _get_session_or_404(research_id, repo, current_user)
    if session.state.final_report is None:
        raise HTTPException(status_code=404, detail="REPORT_NOT_READY")
    return ResearchStatusResponse(
        research_id=session.research_id,
        status=session.status,
        error=session.error,
        report=session.state.final_report,
        stage=_current_stage(session),
        progress=_progress(session),
        question=session.state.request.question,
        created_at=session.state.execution_metadata.started_at,
    )


@router.post("/{research_id}/cancel", response_model=ResearchStatusResponse)
async def cancel_research(
    research_id: UUID,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ResearchStatusResponse:
    """Cancels a pending/running research session (docs/api.md). Best-effort:
    in-flight agent work already dispatched by the job runner is not
    interrupted mid-step (no cooperative cancellation token exists in the
    graph yet); this marks the session `cancelled` so it stops being treated
    as live by clients and won't be presented as if research is ongoing."""
    session = await _get_session_or_404(research_id, repo, current_user)
    if session.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail="RESEARCH_NOT_CANCELLABLE")

    cancelled = session.model_copy(update={"status": "cancelled"})
    await repo.update(cancelled)
    return ResearchStatusResponse(
        research_id=cancelled.research_id,
        status=cancelled.status,
        error=cancelled.error,
        report=cancelled.state.final_report,
        stage=_current_stage(cancelled),
        progress=_progress(cancelled),
        question=cancelled.state.request.question,
        created_at=cancelled.state.execution_metadata.started_at,
    )
