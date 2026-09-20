# Multi-Agent Research & Decision System

A production-oriented platform that turns a complex decision question ("build
vs. buy," "which vector database," "should we migrate X") into an auditable
research and decision report — produced by a controlled pipeline of
specialized agents (planner, researchers, fact checker, contradiction
detector, decision analyst, risk analyst, synthesizer, verification gate)
rather than a single unrestricted LLM loop.

**Status: all 10 phases complete.** Secured LangGraph multi-agent backend
(auth, PostgreSQL, RAG/Qdrant, Redis caching/rate-limiting, background job
runner, OpenTelemetry observability, guardrails), an authenticated Next.js
frontend, a 22-question evaluation benchmark, Docker Compose for local
deployment, and a GitHub Actions CI/CD pipeline. 225 backend tests pass; see
[CHANGELOG.md](CHANGELOG.md) for the full phase-by-phase build history.

## Why multi-agent, and why controlled orchestration

A single LLM call answering "should we build or buy X" produces a
plausible-sounding paragraph with no evidence trail. This system instead runs
a bounded, inspectable pipeline: each stage has a narrow responsibility, a
typed input/output contract, a tool allowlist, and hard iteration/timeout/
token limits. The result is a report where every material claim traces back
to a source, every score has a stated rationale, contradictions are surfaced
rather than silently resolved, and the system explicitly states what it
assumed and how confident it is. Full rationale:
[docs/architecture.md](docs/architecture.md) §1.

## Architecture at a glance

```
Next.js frontend ──HTTP(S)──► FastAPI (auth, rate limiting, CORS)
                                   │
                          LangGraph orchestration
     Planner → Researcher×N (fan-out) → Source Evaluator → Evidence Analyst
     → Fact Checker → Contradiction Detector → Advocate/Critic
     → Assumption Analyst → Decision Analyst → Risk Analyst
     → Final Synthesizer → Verification Gate (≤3 correction cycles) → Report
                                   │
         ┌─────────────┬──────────┼──────────┬─────────────┐
   LLMProvider    SearchProvider  Qdrant   PostgreSQL      Redis
 (OpenAI/Anthropic/  (Tavily/    (hybrid    (system of   (result +
    local)             local)    RAG)       record)    semantic cache)
```

Full component diagram, agent topology, and the per-agent responsibility
matrix (reads/writes/tool allowlist/budgets/model tier for every one of the
12 agents): [docs/architecture.md](docs/architecture.md) §2-4.

### Agent responsibilities, in one line each

| Agent | Job |
|---|---|
| Research Planner | Decomposes the question into alternatives, criteria, and research questions |
| Researcher (×N, parallel) | Gathers evidence per research question from web search + internal KB |
| Source Evaluator | Weighted credibility score per source (authority/relevance/recency/specificity/independence) |
| Evidence Analyst | Raw passages → typed, source-linked `EvidenceItem`s |
| Fact Checker | Independently verifies each material claim against evidence |
| Contradiction Detector | Contextual conflict analysis (not naive text diffing) |
| Advocate / Critic | One adversarial pass: strongest case for each alternative, strongest attack on it |
| Assumption Analyst | Labels every assumption (planner-stated vs. evidence-backed vs. inferred) |
| Decision Analyst | Weighted decision matrix + mandatory sensitivity analysis |
| Risk Analyst | Risk register with a deterministic probability×impact severity table |
| Final Synthesizer | Assembles the full report; dedicated-analyst output always overrides its own guess |
| Verification Gate | Citation/support/contradiction/confidence checks; routes failures back for correction, capped at 3 cycles |

### RAG architecture

Document ingestion → recursive-character chunking (paragraph → line →
sentence → word, with overlap, never naive fixed-length splitting) →
embedding (`sentence-transformers` or a deterministic offline fake) → Qdrant
(or an in-memory fake) → **hybrid retrieval**: a real BM25 keyword index
merged with vector search via an alpha-weighted score, not two vector
searches dressed up as "hybrid" → reranking (lexical/recency by default, an
opt-in real cross-encoder). Every environment variable defaults to a fully
offline, no-API-key configuration. Details: [docs/architecture.md](docs/architecture.md)
§8, `backend/app/retrieval/`.

### Decision engine

The LLM only proposes per-(alternative, criterion) scores with a rationale;
every number that actually decides the recommendation — weight
normalization, the weighted total, the argmax pick, and sensitivity analysis
(±20% weight perturbation on every criterion, checking whether the
recommendation flips) — is computed in plain, unit-tested Python, never
trusted from the model. Risk severity is likewise always a table lookup
(`probability × impact`), never LLM-eyeballed. See
`backend/app/decision/sensitivity.py`, `backend/app/decision/severity.py`.

### Database schema

PostgreSQL is the system of record: `research_sessions`, `research_plans`,
`alternatives`, `criteria`, `sources`, `documents`, `claims`, `evidence`,
`contradictions`, `agent_runs`, `reports`, `citations`, `audit_logs`,
`users`, `risks`, `assumptions`, `decision_scores`, `jobs`. Full ER diagram
and indexing strategy: [docs/database-schema.md](docs/database-schema.md).
`DATABASE_URL` unset falls back to an in-memory sqlite database (via
`aiosqlite`) so the app and full test suite run fully offline with no live
Postgres — point `DATABASE_URL` at a real instance (or use
`docker compose up`) for persistent/production use, and migrations
(`alembic upgrade head`) apply identically either way.

### API

REST + SSE-shaped surface under `/api/v1` — auth (register/login), research
submission/status/cancel, sources/claims/evidence/decision/trace/report reads,
evaluation report. Full spec: [docs/api.md](docs/api.md). Every route except
`/health` requires `Authorization: Bearer <token>`.

## Local setup

### Option A — Docker Compose (recommended, zero local Python/Node setup)

```bash
cp .env.example .env        # defaults work with zero API keys
docker compose up --build
```

- Backend: http://localhost:8000 (health: `GET /health`)
- Frontend: http://localhost:3000
- Postgres/Qdrant/Redis run as named-volume-backed services; the backend
  container runs `alembic upgrade head` on every boot before starting
  `uvicorn` (`infra/docker/backend-entrypoint.sh`), so the schema is always
  current.
- Every provider defaults to the offline `local`/`local` implementation — no
  `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/`TAVILY_API_KEY` required to run the
  full stack end to end. Set them in `.env` to use a real LLM/search
  provider instead.
- `.env.example` documents every compose-level variable; see
  `backend/.env.example` for the full backend variable reference (RAG,
  caching, resilience, observability, rate limiting, etc. — all optional,
  all documented inline).

### Option B — manual dev (no Docker)

Backend:
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # or: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env       # optional — defaults already work offline
uvicorn app.main:app --reload
```

Frontend:
```bash
cd frontend
npm install
npm run dev
```
> **Windows note**: if your checkout path contains an `&` (as this project's
> default OneDrive path does), plain `npm`/`npx` invocations fail on
> `cmd.exe`'s script-shim resolution. Invoke the Next.js CLI directly instead,
> e.g. `node node_modules/next/dist/bin/next build` /
> `node node_modules/next/dist/bin/next dev` (see CHANGELOG Phase 7-9).

Both the backend and its full test suite work with **zero external
services** by default: `DATABASE_URL`/`QDRANT_URL`/`REDIS_URL` unset fall
back to in-memory sqlite / an in-memory vector store+BM25 index / an
in-memory cache, respectively — the identical code path runs against real
Postgres/Qdrant/Redis once those are configured.

## Environment variables

Two files, two scopes:
- [`.env.example`](.env.example) (repo root) — what `docker compose up`
  reads: provider selection, `JWT_SECRET_KEY`, Postgres credentials, the
  frontend's build-time API URL.
- [`backend/.env.example`](backend/.env.example) — the full backend
  reference, every variable `Settings` (`backend/app/config/settings.py`)
  reads, grouped by subsystem (LLM/search providers, source scoring,
  verification, debate, risk, RAG, caching, job runner, resilience,
  observability, auth, rate limiting).

`ENVIRONMENT=production` gates a hard startup check
(`Settings.check_production_safe`): the app refuses to boot if
`JWT_SECRET_KEY` is still the default/short, `DATABASE_URL` is unset, or
`CORS_ALLOW_ORIGINS` contains a wildcard — `dev`/`test`/`staging` are
unaffected. Generate a real secret with:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Docker

- `infra/docker/backend.Dockerfile` — multi-stage (builder installs from
  `pyproject.toml` into a venv; slim runtime copies only that venv + app
  source), non-root user, `HEALTHCHECK` against `GET /health`, entrypoint
  (`infra/docker/backend-entrypoint.sh`) runs `alembic upgrade head` before
  `uvicorn` starts.
- `infra/docker/frontend.Dockerfile` — deps → build (Next.js
  `output: "standalone"`) → runtime, non-root user, `HEALTHCHECK`.
- `docker-compose.yml` (root) — `backend`, `frontend`, `postgres`, `qdrant`,
  `redis`, named volumes for Postgres/Qdrant/Redis data, healthchecks, and
  `depends_on: condition: service_healthy` throughout so `frontend` never
  starts against a `backend` that isn't actually ready, and `backend` never
  starts migrations against a `postgres` that isn't accepting connections
  yet.

## Testing

```bash
# Backend — offline, in-memory sqlite, no external services required
cd backend && pytest -q

# Backend — lint / type check
ruff check app tests
mypy app

# Frontend
cd frontend
npm run lint
npm run typecheck
npm run build
```

CI (`.github/workflows/ci.yml`) additionally spins up a real Postgres
service container and runs `alembic upgrade head` against it — the first
time in this project's history any migration was verified against real
Postgres rather than only a scratch sqlite file (every prior phase's
CHANGELOG entry documents this as an open gap; Phase 10 closes it). See
[CHANGELOG.md](CHANGELOG.md) Phase 10 for what that run found.

## Evaluation

```bash
cd backend
python scripts/evaluate_system.py --limit 5   # fast subset
python scripts/evaluate_system.py             # full 22-question benchmark
```

Runs each question in [docs/evaluation.md](docs/evaluation.md)'s 22-question
benchmark (7 categories: technology selection, architecture, cloud, business,
product, security, engineering) through the real graph, computes research/
agent/decision/system-quality metrics, and writes a JSON report
(`backend/evaluation_reports/latest.json`, also served at
`GET /api/v1/evaluation/latest` and rendered at `/evaluation` in the
frontend). Metric definitions and target methodology:
[docs/evaluation.md](docs/evaluation.md).

## Observability

Every agent run emits one structured JSON log line (`trace_id`, agent name,
latency, tokens, status) and one OpenTelemetry span
(`backend/app/observability/`). `OTEL_EXPORTER=console` (default) needs no
extra infrastructure; `OTEL_EXPORTER=otlp` sends spans to a real collector at
`OTEL_EXPORTER_OTLP_ENDPOINT`. The Agent Trace UI (`/research/[id]/trace` in
the frontend) renders the full pipeline run, grouped by stage, including
fan-out (parallel Researcher runs) and verification-loop retries.

## Security

JWT auth on every route except `/health`; per-user authorization (a user only
reads/cancels their own sessions unless `role=admin`); per-user token-bucket
rate limiting on `POST /research`; prompt-injection guardrails on all
retrieved web/KB content before it reaches any agent; SSRF protection on
search-result URLs (rejects private/loopback/link-local/cloud-metadata
targets); standard security response headers (CSP, `X-Frame-Options`, HSTS
over https); no hardcoded secrets anywhere in the repo (`.env`/`.env.*.local`
gitignored, `docker-compose.yml` reads only `${VAR}` references); CI runs
`pip-audit`/`npm audit` on every push. Full detail:
[docs/architecture.md](docs/architecture.md) §7, CHANGELOG Phase 8.

## Example research task walkthrough

The canonical end-to-end example throughout this project (also the E2E test
fixture, `backend/tests/test_e2e_pgvector_question.py`, and a benchmark
question) is:

> "Should we use PostgreSQL with the pgvector extension or a dedicated
> vector database (e.g. Qdrant) for our RAG pipeline?"

```bash
curl -X POST http://localhost:8000/api/v1/research \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Should we use PostgreSQL with pgvector or a dedicated vector database (Qdrant) for our RAG pipeline?",
    "constraints": ["team already runs Postgres in production", "budget-conscious"],
    "mode": "auto"
  }'
# -> 202 {"research_id": "...", "status": "pending"}

curl http://localhost:8000/api/v1/research/<research_id> \
  -H "Authorization: Bearer <token>"
# -> poll until status == "completed"
```

What happens underneath: the Planner extracts two alternatives (pgvector,
Qdrant) and criteria (operational simplicity, query performance at scale,
filtering capability, cost); Researchers gather evidence per research
question in parallel; the Source Evaluator scores each source; the Fact
Checker and Contradiction Detector verify and reconcile claims; Advocate/
Critic build and stress-test the case for each option; the Decision Analyst
produces a weighted matrix with sensitivity analysis (does the recommendation
survive a ±20% reweighting of "query performance" vs. "operational
simplicity"?); the Risk Analyst flags e.g. "pgvector's ANN index performance
at very large scale is less proven"; the Verification Gate confirms every
citation resolves and every low-confidence area is surfaced in
`limitations`; the Final Synthesizer assembles the full report. The
frontend's Report, Decision Matrix, Evidence, Sources, and Agent Trace tabs
(`/research/<id>/*`) render every part of this — see
`frontend/src/features/`.

## Documentation index

| Doc | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | System architecture, component diagram, agent topology, responsibility matrix, tech justification, model routing, guardrail summary |
| [docs/state-schema.md](docs/state-schema.md) | The typed `ResearchState` shared across every agent |
| [docs/database-schema.md](docs/database-schema.md) | PostgreSQL ER diagram and indexing strategy |
| [docs/api.md](docs/api.md) | REST + SSE API specification |
| [docs/project-structure.md](docs/project-structure.md) | Repository layout |
| [docs/phase0-plan.md](docs/phase0-plan.md) | Phased build order (Phase 1 → Phase 10) and exit criteria |
| [docs/risk-register.md](docs/risk-register.md) | Project/engineering risks and mitigations |
| [docs/evaluation.md](docs/evaluation.md) | Quantitative evaluation metrics and benchmark strategy |
| [CHANGELOG.md](CHANGELOG.md) | What shipped in every phase, including documented deviations and their rationale |

## Stack

FastAPI + Pydantic v2 + SQLAlchemy 2 + PostgreSQL backend, LangGraph
orchestration, provider-agnostic `LLMProvider` (OpenAI/Anthropic/local) and
`SearchProvider` (Tavily/local) interfaces, Qdrant for hybrid RAG retrieval,
Redis for caching/rate limiting, a lightweight asyncio job runner for durable
background execution, Next.js 14 + TypeScript (strict) + Tailwind frontend,
OpenTelemetry + structured JSON logging, Docker Compose for local
deployment, GitHub Actions for CI/CD. Full justification:
[docs/architecture.md](docs/architecture.md) §5.
