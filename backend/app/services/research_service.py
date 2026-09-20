"""Phase 2 research service: runs the multi-agent LangGraph orchestration
(`app/orchestration/graph.py`) instead of Phase 1's ad-hoc single-agent flow.

`ResearchService` keeps the exact same public surface (`run(research_id,
request, repo)`) the API layer and Phase 1 tests already depend on — only
what happens inside changed. Session bookkeeping (pending -> running ->
completed/failed) and error handling stay here; all research logic now
lives in `app/agents/` + `app/orchestration/graph.py`.

Phase 6 (docs/architecture.md §6): an optional `cache` short-circuits the
entire graph run for an identical `question` + provider combo within a TTL.
Optional and defaulted to `None` so every existing caller/test keeps working
uncached, matching this codebase's "new infra is additive, never a required
constructor arg" convention (see `kb`/`settings` above).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from app.config.settings import Settings, get_settings
from app.orchestration.graph import run_research_graph
from app.retrieval.hybrid_retrieval import HybridRetriever
from app.schemas.state import ExecutionMetadata, ResearchRequest, ResearchState
from app.services import audit_service
from app.services.cache_service import CacheService
from app.services.session_repository import ResearchSession, SessionRepository
from app.tools.llm_provider import LLMProvider
from app.tools.search_provider import SearchProvider

_RESULT_CACHE_NAMESPACE = "research_result"


def _result_cache_key(request: ResearchRequest, llm: LLMProvider, search: SearchProvider) -> str:
    """Deterministic key: identical question + provider combo (mode
    included, since "auto" vs "manual" can change the pipeline's behavior)
    within the TTL reuses the prior run's result."""
    raw = f"{request.question}|{request.mode}|{llm.name}|{search.name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ResearchService:
    def __init__(
        self,
        llm: LLMProvider,
        search: SearchProvider,
        settings: Settings | None = None,
        kb: HybridRetriever | None = None,
        cache: CacheService | None = None,
    ) -> None:
        self._llm = llm
        self._search = search
        self._settings = settings or get_settings()
        self._kb = kb
        self._cache = cache

    async def run(
        self,
        *,
        research_id: UUID,
        request: ResearchRequest,
        repo: SessionRepository,
    ) -> None:
        """Execute the multi-agent graph end to end, writing progress into
        `repo` as it goes. A result-cache hit skips the graph entirely."""
        trace_id = f"trace-{research_id}"
        pending_metadata = ExecutionMetadata(
            trace_id=trace_id,
            session_id=research_id,
            started_at=datetime.now(UTC),
            status="running",
        )
        pending_state = ResearchState(request=request, execution_metadata=pending_metadata)
        # Guard against a race with POST .../cancel firing between job
        # dispatch and this first write (see the "best-effort cancellation"
        # note further down): never flip an already-cancelled session back
        # to "running".
        existing = await repo.get(research_id)
        if existing is not None and existing.status == "cancelled":
            return
        await repo.update(
            ResearchSession(research_id=research_id, status="running", state=pending_state)
        )

        cache_key = _result_cache_key(request, self._llm, self._search) if self._cache else None
        if self._cache is not None and cache_key is not None:
            cached = await self._cache.get(_RESULT_CACHE_NAMESPACE, cache_key)
            if cached is not None:
                cached_state = ResearchState.model_validate(cached)
                reused_metadata = cached_state.execution_metadata.model_copy(
                    update={
                        "session_id": research_id,
                        "trace_id": trace_id,
                        "completed_at": datetime.now(UTC),
                        "status": "completed",
                    }
                )
                reused_state = cached_state.model_copy(
                    update={"request": request, "execution_metadata": reused_metadata}
                )
                current = await repo.get(research_id)
                if current is not None and current.status == "cancelled":
                    return
                await repo.update(
                    ResearchSession(research_id=research_id, status="completed", state=reused_state)
                )
                await audit_service.log_run(repo, research_id, reused_state)
                return

        try:
            state = await run_research_graph(
                request,
                llm=self._llm,
                search=self._search,
                settings=self._settings,
                kb=self._kb,
            )
            # Phase 8 best-effort cancellation (docs/api.md POST
            # .../cancel): the graph itself has no cooperative cancellation
            # token, so a run that was already in flight still executes to
            # completion -- but its result must never clobber a user's
            # explicit cancel. If the session was marked `cancelled` while
            # this run was executing, leave that status as the final one
            # instead of silently overwriting it with "completed".
            current = await repo.get(research_id)
            if current is not None and current.status == "cancelled":
                return
            await repo.update(
                ResearchSession(research_id=research_id, status="completed", state=state)
            )
            # Audit logging happens here, in the orchestration layer, not
            # inside any agent module (docs/database-schema.md audit_logs).
            await audit_service.log_run(repo, research_id, state)
            if self._cache is not None and cache_key is not None and state.final_report is not None:
                await self._cache.set(
                    _RESULT_CACHE_NAMESPACE,
                    cache_key,
                    state.model_dump(mode="json"),
                    self._settings.cache_result_ttl_seconds,
                )
        except Exception as exc:  # noqa: BLE001 - surfaced via session status
            failed_metadata = pending_metadata.model_copy(
                update={"status": "failed", "completed_at": datetime.now(UTC)}
            )
            failed_state = ResearchState(request=request, execution_metadata=failed_metadata)
            await repo.update(
                ResearchSession(
                    research_id=research_id,
                    status="failed",
                    state=failed_state,
                    error=str(exc),
                )
            )
