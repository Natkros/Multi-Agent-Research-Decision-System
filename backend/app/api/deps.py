"""FastAPI dependency providers.

No module-level singletons: the session repository lives on `app.state`
(set up once in `main.py`'s lifespan) and is fetched per-request; providers
are constructed fresh per-request from settings, which is cheap since their
underlying SDK clients are lazily initialized.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.config.settings import Settings, get_settings
from app.retrieval.hybrid_retrieval import HybridRetriever
from app.security.auth import CurrentUser, get_current_user  # noqa: F401 - re-exported dep
from app.security.rate_limit import RateLimiter
from app.services.cache_service import CacheService as _CacheService
from app.services.job_runner import JobRunner
from app.services.session_repository import SessionRepository
from app.tools.llm_provider import LLMProvider, get_llm_provider
from app.tools.search_provider import SearchProvider, get_search_provider


def get_settings_dep() -> Settings:
    return get_settings()


def get_llm_provider_dep(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> LLMProvider:
    return get_llm_provider(settings)


def get_search_provider_dep(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SearchProvider:
    return get_search_provider(settings)


def get_session_repository(request: Request) -> SessionRepository:
    return request.app.state.session_repository


def get_retrieval_pipeline(request: Request) -> HybridRetriever:
    return request.app.state.retrieval_pipeline


def get_job_runner(request: Request) -> JobRunner:
    return request.app.state.job_runner


def get_cache_service_dep(request: Request) -> _CacheService:
    return request.app.state.cache_service


def get_rate_limiter_dep(request: Request) -> RateLimiter:
    """One `RateLimiter` per process, built once in `main.py` against the
    process's shared cache/Redis client -- not reconstructed per request,
    same singleton-on-`app.state` pattern as `cache_service`/
    `retrieval_pipeline` (a fresh `InMemoryRateLimiter` per request would
    never actually limit anything, since its buckets would never persist
    across calls)."""
    return request.app.state.rate_limiter
