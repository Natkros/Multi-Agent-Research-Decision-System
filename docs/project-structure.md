# Directory Structure

```
multi-agent-research-system/
├── backend/
│   └── app/
│       ├── api/            # FastAPI routers — thin, delegate to services
│       ├── agents/         # one module per agent (prompt + logic + schemas)
│       ├── orchestration/  # LangGraph graph definition, state merge logic
│       ├── models/         # SQLAlchemy ORM models
│       ├── schemas/        # Pydantic request/response + ResearchState types
│       ├── services/       # business logic: session mgmt, report assembly
│       ├── tools/          # LLMProvider, SearchProvider, tool allowlist enforcement
│       ├── retrieval/      # RAG pipeline: ingest, chunk, embed, hybrid retrieve, rerank
│       ├── decision/        # decision matrix engine, sensitivity analysis
│       ├── verification/    # verification gate checks, citation validator
│       ├── memory/          # short/working/long-term memory adapters
│       ├── observability/   # OTel setup, structured logging, tracing decorators
│       ├── security/        # auth, guardrails, prompt-injection detection
│       └── config/          # settings, model routing, agent config (yaml/env)
│   └── tests/
├── frontend/
│   └── src/
│       ├── app/            # Next.js routes (dashboard, research, trace, etc.)
│       ├── components/     # shared UI primitives
│       ├── features/       # feature-scoped modules (evidence explorer, matrix, trace)
│       ├── hooks/          # SSE/WS subscriptions, data fetching
│       ├── lib/            # API client, formatting utilities
│       └── types/          # TS mirrors of backend Pydantic schemas
├── infra/
│   ├── docker/
│   ├── postgres/
│   ├── qdrant/
│   └── redis/
├── docs/
│   ├── architecture.md
│   ├── agent-design.md      (superset lives in architecture.md §3-4 for Phase 0;
│                              split out if it grows past Phase 2)
│   ├── state-schema.md
│   ├── database-schema.md
│   ├── api.md
│   ├── research-workflow.md (authored alongside LangGraph implementation, Phase 2)
│   ├── security.md          (authored Phase 8)
│   └── evaluation.md
├── scripts/
│   ├── seed_data.py
│   ├── ingest_documents.py
│   └── evaluate_system.py
├── .github/workflows/
├── docker-compose.yml
├── .env.example
└── README.md
```

This scaffold is created empty in Phase 0 (folders only) and filled incrementally
per the phase plan in [phase0-plan.md](phase0-plan.md) — no phase writes outside
its own directories without a documented reason.
