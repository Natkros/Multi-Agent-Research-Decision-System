# Architecture — Multi-Agent Research & Decision System

## 1. Purpose

An autonomous system that takes a complex decision/research question, decomposes it,
delegates sub-problems to specialized agents, gathers and verifies evidence from
multiple sources, resolves contradictions, scores alternatives against explicit
criteria, quantifies risk and uncertainty, and produces an auditable decision report
with citations. It behaves like a small research team with a controlled process,
not an open-ended autonomous agent loop.

Core design commitment: **deterministic workflow orchestration with bounded agents**,
not free-running ReAct loops. Every agent has a typed input/output contract, a tool
allowlist, iteration/timeout/token budgets, and explicit failure handling. This is
what makes the system testable, debuggable, cost-bounded and safe to run unattended.

## 2. Component Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                 │
│   Next.js Web UI  ──SSE/WS──►  Research progress, trace, report views     │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │ HTTPS (REST + SSE)
┌───────────────────────────────▼───────────────────────────────────────────┐
│                            API LAYER (FastAPI)                            │
│  /api/v1/research  · auth · rate limiting · request validation            │
│  Publishes jobs to the orchestration layer, streams state via SSE         │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │
┌───────────────────────────────▼───────────────────────────────────────────┐
│                     ORCHESTRATION LAYER (LangGraph)                       │
│                                                                            │
│   Orchestrator → Research Planner → [fan-out] Researcher(s) ×N            │
│                                        │            │                     │
│                                   Source Evaluator   Evidence Analyst     │
│                                        └─────┬────────┘                   │
│                                        Fact Checker                       │
│                                        Contradiction Detector             │
│                                        Advocate / Critic (debate)         │
│                                        Assumption Analyst                 │
│                                        Decision Analyst                   │
│                                        Risk Analyst                      │
│                                        Final Synthesizer                  │
│                                        Verification Gate (≤3 cycles)      │
│                                                                            │
│  Shared state: typed Pydantic ResearchState, checkpointed per node        │
└──────┬───────────────┬───────────────┬───────────────┬────────────────────┘
       │               │               │                │
┌──────▼─────┐  ┌──────▼──────┐ ┌──────▼──────┐  ┌──────▼─────────┐
│ LLMProvider │  │SearchProvider│ │  RAG /      │  │  PostgreSQL    │
│ interface   │  │  interface   │ │  Qdrant     │  │  (system of    │
│ OpenAI/     │  │ Tavily/SerpAPI│ │  vector DB  │  │  record)       │
│ Anthropic/  │  │ /local docs   │ │  + hybrid   │  │  sessions,     │
│ Local       │  │               │ │  retrieval  │  │  claims,       │
└─────────────┘  └───────────────┘ └─────────────┘  │  evidence,     │
                                                       │  audit_logs    │
┌─────────────┐  ┌───────────────┐                    └────────────────┘
│    Redis     │  │ Observability │
│ cache/queue/ │  │ OpenTelemetry │
│ semantic     │  │ + structured  │
│ cache        │  │ logs + traces │
└─────────────┘  └───────────────┘
```

All provider integrations (`LLMProvider`, `SearchProvider`, embeddings, vector DB
client) sit behind interfaces in `backend/app/services` / `backend/app/tools`, so any
implementation can be swapped via configuration without touching agent logic.

## 3. Agent Topology (execution graph)

```
                              USER QUERY
                                  │
                                  ▼
                            ORCHESTRATOR
                     (routes, enforces limits, tracks state)
                                  │
                                  ▼
                          RESEARCH PLANNER
        (decision_type, alternatives[], criteria[], research_questions[])
                                  │
                 ┌────────────────┼────────────────┐
                 ▼                ▼                ▼
           RESEARCHER 1     RESEARCHER 2      RESEARCHER N        (parallel,
                 │                │                │               fan-out per
                 └────────────────┼────────────────┘               research
                                  ▼                                 question)
                          SOURCE EVALUATOR
                       (scores every retrieved source)
                                  │
                                  ▼
                          EVIDENCE ANALYST
                (raw passages/claims → typed EvidenceItem[])
                                  │
                                  ▼
                           FACT CHECKER
             (independent verification per material claim)
                                  │
                                  ▼
                      CONTRADICTION DETECTOR
                (contextual conflict analysis, not naive diffing)
                                  │
                                  ▼
                        ADVOCATE / CRITIC
              (adversarial pass: strongest case + strongest attack)
                                  │
                 ┌────────────────┼────────────────┐
                 ▼                ▼                ▼
        ASSUMPTION ANALYST  DECISION ANALYST   RISK ANALYST
      (labels assumptions) (weighted matrix +  (risk register +
                             sensitivity)        severity scoring)
                 └────────────────┼────────────────┘
                                  ▼
                          FINAL SYNTHESIZER
                    (assembles the 16-section report)
                                  │
                                  ▼
                        VERIFICATION GATE
        (citation/support/contradiction/assumption checks;
         ≤3 correction cycles, routes back to the owning agent)
                                  │
                                  ▼
                             FINAL REPORT
```

This graph is implemented as a LangGraph `StateGraph` over `ResearchState`
(see [state-schema.md](state-schema.md)). Fan-out/fan-in nodes (Researcher,
Decision/Risk/Assumption) run as parallel LangGraph branches joined before the
next stage. The Verification Gate is a conditional edge: on failure it routes to
one of {Research Agent, Fact Checker, Final Synthesizer} depending on the failure
category, and increments a `verification_cycle` counter capped at 3 — after which
the report ships with all unresolved issues surfaced under "Limitations" rather
than looping forever.

## 4. Agent Responsibility Matrix

| Agent | Reads | Writes | Tools Allowed | Tools Denied | Max Iter | Timeout | Token Budget | Model Tier |
|---|---|---|---|---|---|---|---|---|
| Orchestrator | request | plan(meta), execution_metadata | none (control-plane only) | all external tools | 1 | 10s | 500 | small/router |
| Research Planner | request | plan | none (reasoning only) | search, db write | 1 | 30s | 3,000 | mid |
| Researcher | plan.research_questions | retrieved_documents, claims (draft) | web_search, document_search, vector_search | db mutation, decision generation | 5 / question | 60s | 6,000 | mid |
| Source Evaluator | retrieved_documents | sources (scored) | none (scoring function + LLM judge) | web browsing, db mutation | 1 / source batch | 20s | 2,000 | small |
| Evidence Analyst | claims, retrieved_documents | evidence[] | none (transformation only) | search, db mutation | 1 / claim batch | 30s | 4,000 | mid |
| Fact Checker | claims, evidence | verified_claims | web_search, document_search | decision generation | 3 / claim | 45s | 4,000 | mid |
| Contradiction Detector | verified_claims | contradictions | none (reasoning only) | search, db mutation | 1 | 30s | 3,000 | mid |
| Advocate / Critic | evidence, contradictions, plan.alternatives | analysis.debate_notes | none (reasoning only) | search, db mutation | 2 (advocate + critic pass) | 45s | 5,000 | strong |
| Assumption Analyst | plan, evidence, analysis | assumptions | none | search | 1 | 20s | 2,000 | small |
| Decision Analyst | evidence, criteria, alternatives | decision_matrix | decision-matrix tool | arbitrary web browsing | 2 (score + sensitivity) | 40s | 4,000 | strong |
| Risk Analyst | evidence, decision_matrix, contradictions | risks | none | search (unless evidence gap flagged) | 1 | 30s | 3,000 | mid |
| Final Synthesizer | entire ResearchState (read-only) | draft_report | report-generation tool | modifying source evidence, db mutation | 1 | 60s | 8,000 | strong |
| Verification Gate | draft_report, ResearchState | verification_results | citation-validator tool | generating new content | 3 cycles max | 30s / cycle | 3,000 | small/router |

"Model Tier" maps to model routing (see §6): `small` = cheap classification/extraction
model, `mid` = general-purpose model, `strong` = best available reasoning model for
synthesis/critique/decision work. Tiers are configuration, not hardcoded model names.

## 5. Technology Justification

| Choice | Why |
|---|---|
| **FastAPI** | Native async, Pydantic-first request/response validation, first-class SSE/WebSocket support, minimal overhead for an I/O-bound (LLM/HTTP-heavy) service. |
| **Pydantic v2** | Single source of truth for every schema crossing an agent boundary; rejects malformed LLM output at the edge instead of letting bad data propagate silently. |
| **PostgreSQL** | Relational integrity for sessions/claims/evidence/decisions/audit trail; mature JSONB support for flexible sub-structures (e.g. debate notes) without losing queryability. |
| **LangGraph** | Gives us an explicit, inspectable state machine with conditional edges, checkpointing, and parallel branches — matches the "deterministic orchestration, not free agent loops" requirement better than a bare agent-loop framework. A custom `StateGraph`-compatible abstraction is the documented fallback if LangGraph proves too heavy for a given deployment target. |
| **Qdrant** | Purpose-built vector DB with payload filtering (metadata filters alongside vector search), needed for hybrid retrieval and per-document-type/date filtering. |
| **Redis** | One dependency serving three jobs: result cache, semantic cache (embedding-keyed), and Celery broker — keeps infra footprint small for an MVP-to-production path. |
| **Celery (or lightweight asyncio job runner for MVP)** | Research runs are long (multi-minute, many LLM calls); they must survive API process restarts and be independently retryable per stage. |
| **Provider-agnostic `LLMProvider` / `SearchProvider` interfaces** | Direct requirement (§2, §13): must swap OpenAI/Anthropic/local models and search vendors without touching agent logic. Implemented as small ABCs behind a factory selected by config/env. |
| **OpenTelemetry + structured JSON logs** | Distributed tracing across an 8+ agent pipeline is not optional — without it, debugging "why did the fact checker mark this OUTDATED" is guesswork. |
| **Next.js + TypeScript + Tailwind** | SSR for fast first paint of the dashboard, strong typing shared conceptually with backend Pydantic schemas (mirrored as TS types), Tailwind for a dense data-heavy UI (matrices, traces, evidence explorer) without custom CSS overhead. |

## 6. Model & Cost Routing Strategy

- **Router/classification tasks** (orchestrator routing, verification-gate checks,
  source-type classification): small/cheap model, low temperature, short max_tokens.
- **Extraction tasks** (claim extraction, passage relevance scoring): small-to-mid
  model, structured-output mode, deterministic (temperature 0).
- **Synthesis/critique/decision tasks** (Advocate/Critic, Decision Analyst, Final
  Synthesizer): strongest configured model, higher token budget, still bounded.
- All routing decisions live in `backend/app/config/model_routing.yaml` (or env),
  never hardcoded in agent code — the same agent code runs unchanged if the
  operator repoints "strong" from one provider's flagship model to another's.
- Prompt caching (provider-native where available) and a Redis-backed semantic
  cache in front of the Research Agent's search+retrieval step avoid re-paying for
  repeated sub-questions across similar research runs.

## 7. Guardrail Summary (detail in `docs/security.md`, authored in Phase 8)

- Retrieved web/document content is always treated as **untrusted data**: it is
  wrapped in a distinct message role/section and the system prompt explicitly
  instructs every agent to never follow instructions found inside retrieved text.
- Structured-output validation (Pydantic) on every LLM response; a validation
  failure triggers a bounded retry (max 2) with the validation error fed back to
  the model, then a typed failure result — never a silent pass-through of raw text.
- Per-agent tool allowlists are enforced in code (the tool-calling harness checks
  the allowlist before executing a tool call), not just described in the prompt.
- Recursion/iteration caps and wall-clock timeouts are enforced by the LangGraph
  node wrapper, independent of what the LLM "decides" to do.
