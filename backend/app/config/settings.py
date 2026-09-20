"""Application configuration.

Loaded from environment variables (and a local .env file in dev). Import of
this module must never require any API key to be set — providers lazily read
their keys only when actually invoked, so tests and offline dev work with the
`local` provider and no secrets at all.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The dev-only default `jwt_secret_key` below (and any obviously-placeholder
# value someone pastes from an example file) must never reach a real
# deployment — checked in `Settings.check_production_safe` (Phase 10).
_INSECURE_JWT_SECRETS = {
    "dev-only-insecure-secret-change-me",
    "change-me",
    "changeme",
    "secret",
    "",
}


class SourceScoringWeights(BaseModel):
    """Weights for the Source Evaluator's credibility formula (Phase 3,
    docs/architecture.md §4/§5). Config, never hardcoded in the agent."""

    authority: float = 0.25
    relevance: float = 0.25
    recency: float = 0.15
    specificity: float = 0.20
    independence: float = 0.15


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- App --
    app_name: str = "Multi-Agent Research & Decision System"
    # "dev"/"prod" (this repo's original short spellings, still accepted for
    # `backend/.env.example`) plus "development"/"production" (the compose
    # setup and Phase 10 brief's spelling) are all valid; whichever is set,
    # `is_production` below is what every production-safety check reads.
    environment: Literal["dev", "development", "test", "staging", "prod", "production"] = "dev"
    api_v1_prefix: str = "/api/v1"
    # Phase 7: origins allowed to call the API from a browser (the Next.js
    # frontend). Permissive localhost defaults for dev; override via
    # CORS_ALLOW_ORIGINS (comma-separated) in a real deployment.
    cors_allow_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # -- LLM provider selection --
    llm_provider: Literal["openai", "anthropic", "local"] = "local"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # Model routing tiers (docs/architecture.md §6): small = cheap
    # classification/extraction, mid = general purpose, strong = best
    # available reasoning model for synthesis/critique/decision work.
    # These are config, never hardcoded in agent/service code.
    model_small: str = "gpt-4o-mini"
    model_mid: str = "gpt-4o"
    model_strong: str = "gpt-4o"
    anthropic_model_small: str = "claude-haiku-4-5"
    anthropic_model_mid: str = "claude-sonnet-4-5"
    anthropic_model_strong: str = "claude-opus-4-1"

    # -- Search provider selection --
    search_provider: Literal["tavily", "local"] = "local"
    tavily_api_key: str | None = None

    # -- Database (Phase 3: real SQLAlchemy-backed repository. If unset, a
    # local sqlite+aiosqlite in-memory database is used instead so the app
    # and test suite work fully offline with no live Postgres — see
    # `app/models/database.py`.) --
    database_url: str | None = None

    # -- Source Evaluator weighted scoring formula (docs/architecture.md
    # §5.5): authority*0.25 + relevance*0.25 + recency*0.15 +
    # specificity*0.20 + independence*0.15 by default, overridable via env
    # (SOURCE_WEIGHT_AUTHORITY etc.) or a single SOURCE_SCORING_WEIGHTS
    # JSON blob. --
    source_weight_authority: float = 0.25
    source_weight_relevance: float = 0.25
    source_weight_recency: float = 0.15
    source_weight_specificity: float = 0.20
    source_weight_independence: float = 0.15

    # -- Verification Gate (docs/architecture.md §3/§4): hard cap enforced
    # in code (app/orchestration/graph.py), not just described in a prompt. --
    verification_max_cycles: int = 3

    # -- Advocate/Critic debate pass (Phase 4, docs/architecture.md §4,
    # brief §5.6): bounded to one advocate + one critic LLM call per run.
    # `debate_max_alternatives` caps how many alternatives the single
    # advocate call builds a case for, so the prompt/response stays bounded
    # even when the planner produced many alternatives. --
    debate_max_alternatives: int = 5
    debate_advocate_max_tokens: int = 2_500
    debate_critic_max_tokens: int = 2_500

    # -- Risk Analyst (Phase 4, brief §5.10): below this many EvidenceItems
    # overall, evidence coverage is considered "thin" and an "unknown"
    # category risk is guaranteed in the risk register even if the LLM
    # didn't propose one. --
    risk_thin_evidence_threshold: int = 3

    # -- Decision Analyst sensitivity analysis (Phase 4, brief §11): each
    # criterion's weight is perturbed by this fraction (both directions),
    # renormalizing the rest, to test whether the recommendation flips. --
    sensitivity_weight_perturbation: float = 0.20

    # -- RAG pipeline (Phase 5, docs/architecture.md §2 RAG box, brief §8) --
    # Embeddings: local sentence-transformers (offline, no API key — matches
    # this repo's design goal every phase) or a deterministic hash-based fake
    # for tests/dev that don't want to load any ML model at all.
    embedding_provider: Literal["sentence-transformers", "local"] = "local"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # Vector store: unset QDRANT_URL falls back to an in-memory fake, same
    # pattern as `effective_database_url`'s sqlite fallback.
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str = "document_chunks"

    # Chunking (recursive character splitter, `app/retrieval/chunking.py`).
    chunk_size: int = 800
    chunk_overlap: int = 150

    # Hybrid retrieval merge weight: 0 = pure keyword (BM25), 1 = pure
    # semantic (vector) search.
    hybrid_retrieval_alpha: float = 0.5

    # Reranking: `lexical_recency` (default, no second model, keeps offline
    # operation true by default) or `cross_encoder` (real cross-encoder
    # rerank, opt-in — see `app/retrieval/reranking.py` module docstring for
    # the tradeoff).
    reranker: Literal["lexical_recency", "cross_encoder"] = "lexical_recency"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_recency_weight: float = 0.1

    # -- Misc --
    request_timeout_seconds: float = 30.0
    max_search_results: int = 5

    # -- Redis caching (Phase 6, docs/architecture.md §6/§16): result cache
    # (identical question+provider combo within a TTL) and a semantic cache
    # in front of the Researcher's search+retrieval step. Unset REDIS_URL
    # falls back to an in-memory fake (`LocalCacheService`), same pattern as
    # every other external-service seam in this codebase. --
    redis_url: str | None = None
    cache_result_ttl_seconds: int = 3600
    cache_semantic_ttl_seconds: int = 3600
    cache_semantic_similarity_threshold: float = 0.92

    # -- Background job runner (Phase 6, brief §6/§26): bounded-concurrency
    # asyncio worker pool over a Postgres-backed `jobs` table. --
    job_runner_concurrency: int = 4

    # -- Resilience (Phase 6, brief §26): retry/circuit-breaker knobs applied
    # only to real external providers (never the Local*/in-memory fakes). --
    resilience_max_attempts: int = 3
    resilience_base_delay_seconds: float = 0.5
    resilience_max_delay_seconds: float = 8.0
    resilience_circuit_failure_threshold: int = 5
    resilience_circuit_reset_seconds: float = 30.0

    # -- Observability (Phase 6, brief §15): OTel exporter selection.
    # `console` (default) needs no extra infra; `otlp` sends to a real
    # collector at OTEL_EXPORTER_OTLP_ENDPOINT. --
    otel_exporter: Literal["console", "otlp"] = "console"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    # -- Auth (Phase 8, docs/api.md "Auth & rate limiting"): JWT-based auth.
    # `jwt_secret_key` has a dev-only default so the app/test suite work
    # offline with no secrets configured, matching every other provider seam
    # in this codebase -- a real deployment MUST override it via env, never
    # commit a real secret. `Settings` validation does not hard-fail on the
    # default so `environment=dev/test` keeps working out of the box; ops
    # tooling should still assert this is overridden before a prod deploy. --
    jwt_secret_key: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    # -- Rate limiting (Phase 8, brief §14/§27): per-user token bucket on the
    # expensive POST /api/v1/research endpoint, via the same Redis client
    # `RedisCacheService` lazily builds (see app/security/rate_limit.py) --
    # no second Redis dependency. --
    rate_limit_research_capacity: int = 5
    rate_limit_research_refill_per_minute: float = 5.0

    # -- Evaluation (Phase 9, docs/evaluation.md): path `scripts/evaluate_system.py`
    # writes its JSON report to, and `GET /api/v1/evaluation/latest` reads it
    # from. A static-artifact read, not a live system -- no new database
    # table needed (relative paths resolve against `backend/`). --
    evaluation_report_path: str = "evaluation_reports/latest.json"

    @property
    def is_production(self) -> bool:
        return self.environment in ("prod", "production")

    @model_validator(mode="after")
    def check_production_safe(self) -> "Settings":
        """Hard-fail at startup (Phase 10, brief §39 security bar) rather than
        silently booting a production deployment on dev-safe defaults. Only
        gated by `environment` — `dev`/`test`/`staging` are unaffected, so
        this never breaks local dev or the test suite, which never set
        `ENVIRONMENT=production`."""
        if not self.is_production:
            return self
        if self.jwt_secret_key in _INSECURE_JWT_SECRETS or len(self.jwt_secret_key) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be set to a real random secret (>= 32 chars) when "
                "ENVIRONMENT=production — refusing to start with a default/weak value. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if not self.database_url:
            raise ValueError(
                "DATABASE_URL must be set to a real Postgres instance when "
                "ENVIRONMENT=production — refusing to fall back to the in-memory sqlite store."
            )
        if any(origin in ("*",) for origin in self.cors_allow_origins):
            raise ValueError(
                "CORS_ALLOW_ORIGINS must not be a wildcard when ENVIRONMENT=production."
            )
        return self

    @property
    def effective_database_url(self) -> str:
        """The URL actually used to build the async engine. Falls back to an
        in-memory sqlite database so dev/tests never require a live
        Postgres instance."""
        return self.database_url or "sqlite+aiosqlite:///:memory:"

    def source_scoring_weights(self) -> SourceScoringWeights:
        return SourceScoringWeights(
            authority=self.source_weight_authority,
            relevance=self.source_weight_relevance,
            recency=self.source_weight_recency,
            specificity=self.source_weight_specificity,
            independence=self.source_weight_independence,
        )

    def model_name_for_tier(self, tier: Literal["small", "mid", "strong"]) -> str:
        """Resolve a model-tier name to a concrete model id for the active provider."""
        if self.llm_provider == "anthropic":
            return {
                "small": self.anthropic_model_small,
                "mid": self.anthropic_model_mid,
                "strong": self.anthropic_model_strong,
            }[tier]
        return {
            "small": self.model_small,
            "mid": self.model_mid,
            "strong": self.model_strong,
        }[tier]


@lru_cache
def get_settings() -> Settings:
    return Settings()
