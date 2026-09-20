# Phase 0 Summary & Phased Implementation Plan

## Phase 0 deliverables (this document set)

| # | Deliverable | Location |
|---|---|---|
| 1 | System architecture | [architecture.md](architecture.md) §1-2 |
| 2 | Component diagram | [architecture.md](architecture.md) §2 |
| 3 | Agent topology | [architecture.md](architecture.md) §3 |
| 4 | Agent responsibility matrix | [architecture.md](architecture.md) §4 |
| 5 | Shared state schema | [state-schema.md](state-schema.md) |
| 6 | Database ER diagram | [database-schema.md](database-schema.md) |
| 7 | API specification | [api.md](api.md) |
| 8 | Directory structure | [project-structure.md](project-structure.md) (scaffolded on disk) |
| 9 | Phase 0 implementation plan | this document |
| 10 | Technology justification | [architecture.md](architecture.md) §5 |
| 11 | Risk register | [risk-register.md](risk-register.md) |
| 12 | Evaluation strategy | [evaluation.md](evaluation.md) |

## Phased build order

Each phase ends with passing tests for what it added before the next phase starts.
No phase is "complete everything" — each is scoped to be independently demoable.

- **Phase 1 — Single-agent MVP.** FastAPI skeleton, `LLMProvider`/`SearchProvider`
  interfaces (OpenAI + one stub), a single research-and-report flow (no multi-agent
  graph yet), basic Markdown report output. Goal: prove the end-to-end request →
  LLM → report path and the provider-swap abstraction before adding orchestration
  complexity.
- **Phase 2 — Multi-agent orchestration.** LangGraph `StateGraph` over
  `ResearchState`; Planner, Researcher (parallel fan-out), Evidence Analyst, Fact
  Checker, Final Synthesizer wired as real graph nodes with the budgets from the
  responsibility matrix enforced.
- **Phase 3 — Evidence system.** Claims/citations persisted to PostgreSQL, Source
  Evaluator scoring, Contradiction Detector, Verification Gate with the 3-cycle cap.
- **Phase 4 — Decision intelligence.** Weighted decision matrix, Risk Analyst,
  Assumption Analyst, sensitivity analysis, Advocate/Critic debate pass.
- **Phase 5 — RAG.** Document ingestion pipeline, chunking, embeddings, Qdrant,
  hybrid (semantic + keyword) retrieval, reranking, internal-KB search tool.
- **Phase 6 — Production infra.** Redis caching (result + semantic), Celery/async
  job execution so runs survive API restarts, retries with backoff, circuit
  breakers, full OpenTelemetry tracing and structured logs.
- **Phase 7 — Frontend.** Dashboard, research submission + live progress (SSE),
  Evidence Explorer, Decision Matrix view, Agent Trace UI.
- **Phase 8 — Security + testing.** Auth/authz, prompt-injection defenses, unit +
  integration + E2E test suites (including the pgvector-vs-Qdrant benchmark
  question as the canonical E2E case, §23).
- **Phase 9 — Evaluation.** 20-question benchmark dataset, evaluation harness,
  metrics dashboard (§24-25).
- **Phase 10 — Deployment.** Docker Compose, GitHub Actions CI/CD, production
  configuration and `.env.example` hardening.

## Exit criteria per phase (summary)

A phase is not "done" until: its own unit tests pass, it does not break any
previous phase's tests, and `CHANGELOG.md` records what shipped. Phase 2 onward
additionally requires at least one manual run through the API showing the new
agent(s) actually executing (not just importable).

## Immediate next step

Awaiting approval to begin **Phase 1**. No application code will be written
before that approval, per the brief's explicit instruction.
