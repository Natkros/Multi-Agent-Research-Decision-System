"""FastAPI application entrypoint (Phase 1)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.evaluation import router as evaluation_router
from app.api.research import router as research_router
from app.config.settings import get_settings
from app.observability.logging import configure_logging
from app.observability.tracing import configure_tracing
from app.retrieval.hybrid_retrieval import get_hybrid_retriever
from app.security.headers import SecurityHeadersMiddleware
from app.security.rate_limit import get_rate_limiter
from app.services.cache_service import get_cache_service
from app.services.job_runner import JobRecord, JobRunner, PostgresJobStore
from app.services.research_service import ResearchService
from app.services.session_repository import SessionRepository
from app.tools.llm_provider import get_llm_provider
from app.tools.search_provider import get_search_provider

# Configured at import time (not inside `lifespan`) so both `uvicorn` and the
# ASGI test transport (which doesn't drive lifespan events — see the
# `app.state` comment below) get structured logs/tracing from the first line.
configure_logging()
configure_tracing()


def _make_research_job_handler(
    *, session_repository: SessionRepository, settings, kb, cache
):
    """Bound at app-construction time so the handler reuses the process's
    singleton providers/KB/cache instead of building fresh ones per job —
    same reasoning as `app.state.retrieval_pipeline` being one instance for
    the process."""

    async def handle_research_job(job: JobRecord) -> None:
        research_id = UUID(job.payload["research_id"])
        session = await session_repository.get(research_id)
        if session is None:
            raise RuntimeError(f"job {job.id}: no research session {research_id}")
        service = ResearchService(
            llm=get_llm_provider(settings),
            search=get_search_provider(settings),
            settings=settings,
            kb=kb,
            cache=cache,
        )
        await service.run(research_id=research_id, request=session.state.request, repo=session_repository)

    return handle_research_job


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Explicit recovery pass at startup, in addition to `JobRunner.enqueue`'s
    # lazy self-start (see its docstring) — this is what actually resumes a
    # job left `running` when the previous process died, on a normal
    # `uvicorn` boot rather than only on the next incoming request.
    await app.state.job_runner.start()
    yield
    await app.state.job_runner.stop()
    await app.state.session_repository.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    # Phase 7: the Next.js frontend (a separate origin in dev, e.g.
    # localhost:3000) calls this API directly from the browser via
    # `frontend/src/lib/api.ts`, so it needs CORS enabled. Permissive by
    # default (dev has no auth layer yet -- Phase 8); tighten via
    # `settings.cors_allow_origins` for a real deployment.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Phase 8: standard security response headers on every response,
    # including error responses (brief §27).
    app.add_middleware(SecurityHeadersMiddleware)
    # Set eagerly (not inside `lifespan`) so the app works correctly under
    # ASGI test transports that don't drive lifespan events themselves.
    app.state.session_repository = SessionRepository()
    cache = get_cache_service(settings)
    app.state.cache_service = cache
    # Phase 8: one process-lifetime rate limiter, reusing `cache`'s Redis
    # client when one is configured (see app/security/rate_limit.py).
    app.state.rate_limiter = get_rate_limiter(cache)
    # Phase 5: one process-lifetime `HybridRetriever` (embeddings + vector
    # store + keyword index), same singleton-on-app.state pattern as the
    # session repository — so ingested documents/the in-memory fallback
    # store actually persist across requests. Phase 6: wired with the cache
    # service so repeated/similar sub-questions hit the semantic cache.
    app.state.retrieval_pipeline = get_hybrid_retriever(settings, cache=cache)
    # Phase 6: durable job runner (`app/services/job_runner.py`). `start()`
    # is idempotent and also called lazily from `enqueue()`, so it works
    # whether or not `lifespan` actually runs (see `lifespan` above).
    app.state.job_runner = JobRunner(
        store=PostgresJobStore(settings),
        handler=_make_research_job_handler(
            session_repository=app.state.session_repository,
            settings=settings,
            kb=app.state.retrieval_pipeline,
            cache=cache,
        ),
        concurrency=settings.job_runner_concurrency,
    )
    app.include_router(auth_router, prefix=settings.api_v1_prefix)
    app.include_router(research_router, prefix=settings.api_v1_prefix)
    app.include_router(evaluation_router, prefix=settings.api_v1_prefix)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
