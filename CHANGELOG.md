# Changelog

## Phase 0 — 2026-09-20

- Authored architecture, agent topology, agent responsibility matrix, and
  technology justification (`docs/architecture.md`).
- Defined the shared typed `ResearchState` and all sub-schemas
  (`docs/state-schema.md`).
- Designed the PostgreSQL schema and ER diagram (`docs/database-schema.md`).
- Specified the REST + SSE API surface (`docs/api.md`).
- Scaffolded the repository directory structure (empty backend/frontend/infra
  trees) (`docs/project-structure.md`).
- Wrote the phased implementation plan, Phase 1-10, with exit criteria
  (`docs/phase0-plan.md`).
- Wrote the project risk register (`docs/risk-register.md`).
- Wrote the evaluation strategy and benchmark plan (`docs/evaluation.md`).
- No application code written yet, per the phased-delivery requirement.

## Phase 1 — 2026-09-20

Single-agent research MVP: proves the request -> LLM -> report path and the
provider-swap abstraction, per `docs/phase0-plan.md`. No multi-agent graph
yet (Phase 2) and no PostgreSQL persistence yet (Phase 3) — both are
deliberately out of scope here.

- `backend/pyproject.toml`: Python 3.12+, FastAPI/Pydantic v2/SQLAlchemy 2/
  `psycopg` (v3, chosen over `asyncpg` for a single well-maintained
  sync+async driver — no SQLAlchemy tables are actually created in Phase 1,
  this only sets up the dependency for Phase 3)/httpx/openai/anthropic/
  pytest/pytest-asyncio.
- `backend/app/config/settings.py`: `Settings` (pydantic-settings) with
  `LLM_PROVIDER`/`SEARCH_PROVIDER` selection, optional API keys (import
  never requires one), and small/mid/strong model-tier config per
  `docs/architecture.md` §6.
- `backend/app/tools/llm_provider.py`: `LLMProvider` ABC +
  `OpenAIProvider`/`AnthropicProvider` (lazy client init, structured output
  via each provider's native JSON mode) + `LocalProvider` (deterministic,
  offline, introspects the requested Pydantic schema to build a minimally
  valid instance) + `get_llm_provider()` factory.
- `backend/app/tools/search_provider.py`: `SearchProvider` ABC +
  `TavilyProvider` (httpx, lazy) + `LocalSearchProvider` (canned offline
  results) + `get_search_provider()` factory.
- `backend/app/schemas/state.py`: every model from `docs/state-schema.md`
  (`ResearchRequest` through `ResearchState`), implemented verbatim.
- `backend/app/schemas/api.py`: request/response models for the Phase 1
  API surface.
- `backend/app/services/research_service.py`: the Phase 1 single-agent
  flow — one bounded LLM call to plan, bounded search calls per research
  question, one bounded LLM call to synthesize a `FinalReport`. Sources/
  evidence attached to the report are grounded deterministically in what
  was actually retrieved (not trusted verbatim from LLM output), to keep
  the state-schema's source-traceability invariant true regardless of
  provider.
- `backend/app/services/session_repository.py`: in-memory, async-safe
  session store (`pending`/`running`/`completed`/`failed`); the seam a
  later phase swaps for a real Postgres-backed repository.
- `backend/app/api/research.py` + `app/api/deps.py` + `backend/app/main.py`:
  `POST /api/v1/research` (kicks off a background task, returns
  `202 {research_id, status: "pending"}`) and `GET /api/v1/research/{id}`
  (status + report once completed). Thin routers; DI via `Depends`, no
  global mutable singletons — the repository lives on `app.state`.
  SSE/trace/decision/sources/claims/evidence/replay endpoints from
  `docs/api.md` are intentionally deferred to later phases.
- `backend/.env.example`: every env var read by `settings.py`, defaults to
  the fully-offline `local`/`local` providers.
- `backend/tests/`: 17 tests (pytest + pytest-asyncio) covering provider
  factories, `LocalProvider` schema-valid output (including against the
  real `ResearchPlan`/`FinalReport` schemas), the research service
  end-to-end, and the submit -> poll API flow via `httpx.AsyncClient`. All
  run offline against `LocalProvider`/`LocalSearchProvider`, no API keys
  required. `pytest` from `backend/`: 17 passed.

## Phase 2 — 2026-09-20

Multi-agent orchestration: replaces Phase 1's single-agent flow with a real
LangGraph `StateGraph` over `ResearchState`, per `docs/phase0-plan.md` and
`docs/architecture.md` §3-4. Research Planner, Researcher (parallel
fan-out per research question), Evidence Analyst, Fact Checker, and Final
Synthesizer are now real graph nodes with the responsibility matrix's
reads/writes/tool-allowlists/budgets enforced in code, not just described.
Source Evaluator, Contradiction Detector, Advocate/Critic, Assumption
Analyst, Decision Analyst, Risk Analyst, and the Verification Gate remain
out of scope (Phase 3/4) — the graph is intentionally a straight line so
adding each of those later is one node + two edges, not a restructure.

- `backend/pyproject.toml`: added `langgraph>=0.6` (installed: 1.2.11).
- `backend/app/agents/`: one module per agent —
  `planner.py`, `researcher.py`, `evidence_analyst.py`, `fact_checker.py`,
  `synthesizer.py` — plus a small `_common.py` timing/`AgentRunMeta` helper
  shared across all five. Each agent exposes a narrow, typed
  `<Agent>Input`/`<Agent>Output` pydantic pair (never the full
  `ResearchState`, never a bare dict) and a `run()` coroutine that:
  records an `AgentRunMeta` (trace_id, timing, tokens, model, tool_calls,
  errors, confidence) on every invocation; calls `LLMProvider.complete()`
  with `response_schema` set to a Pydantic model so output is always
  structurally validated; and respects each agent's token budget from
  `docs/architecture.md` §4 (`MAX_TOKENS` per module). IDs that must trace
  back to a real `Source`/`Claim` (evidence, claim verifications, researcher
  output) are always assigned by code from what was actually retrieved,
  never trusted verbatim from LLM output — the same grounding rule Phase 1
  followed. A `# TODO(Phase 3/6)` marks where the Fact Checker's
  multi-round corroboration budget and a wall-clock timeout enforcer plug
  in later, since neither is required to make Phase 2 meaningful.
- `backend/app/orchestration/graph.py`: `GraphState` (a `TypedDict` with
  `Annotated[list[X], operator.add]` reducers on every field a fan-out
  branch or repeated agent run writes into — `retrieved_documents`,
  `sources`, `claims`, `evidence`, `verified_claims`, `agent_runs`) is the
  LangGraph-native runtime state; `ResearchState` itself stays the plain
  pydantic model every agent type-checks against. `build_graph()` wires
  Planner -> [`Send`-based fan-out] -> Researcher x N (one per
  `research_question`, run in parallel, joined back into one state before
  the next node) -> Evidence Analyst -> Fact Checker -> Final Synthesizer.
  `run_research_graph()` is the async entrypoint: builds the graph,
  invokes it, and assembles the final `ExecutionMetadata` +
  `ResearchState` from the merged `GraphState`.
- `backend/app/services/research_service.py`: `ResearchService.run()` now
  calls `run_research_graph()` instead of the Phase 1 ad-hoc flow; the
  public interface (`run(research_id, request, repo)`) and session
  pending/running/completed/failed bookkeeping are unchanged, so
  `app/api/research.py` needed no changes at all.
- `backend/tests/test_agents.py`: each of the five agents tested in
  isolation against `LocalProvider`/`LocalSearchProvider`, asserting
  grounded ids (every `EvidenceItem`/`Claim`/`ClaimVerification` traces
  back to a real source) and a populated `AgentRunMeta` per run.
- `backend/tests/test_graph.py`: `build_graph()` compiles and exposes all
  five nodes; `run_research_graph()` end-to-end produces a `ResearchState`
  with non-empty `retrieved_documents`/`claims`/`evidence`/
  `verified_claims`/`draft_report`/`final_report` and one `agent_runs`
  entry per invocation; a multi-question plan produces one `researcher`
  `agent_runs` entry per `research_question` (fan-out verified directly,
  not just structurally).
- `backend/tests/test_research_service.py`: updated the Phase 1
  `agent_runs` count assertion (was a fixed `== 2` for the single-agent
  flow) to check the Phase 2 agent sequence instead
  (`research_planner` first, `final_synthesizer` last, `researcher`/
  `evidence_analyst`/`fact_checker` present) — still exercises the same
  end-to-end request -> graph -> report path, now through the real graph.
- `pytest` from `backend/`: 25 passed (17 Phase 1 + 8 new Phase 2 tests;
  no Phase 1 test was deleted).

## Phase 3 — 2026-09-20

Evidence system: real PostgreSQL persistence, Source Evaluator, Contradiction
Detector, and the Verification Gate with a code-enforced 3-cycle cap, per
`docs/phase0-plan.md` and `docs/architecture.md` §3-4. The pipeline is now
Planner -> Researcher (fan-out/join) -> Source Evaluator -> Evidence Analyst
-> Fact Checker -> Contradiction Detector -> Final Synthesizer ->
Verification Gate (conditional loop, max 3 cycles) -> END. Advocate/Critic,
Assumption Analyst, Decision Analyst, Risk Analyst remain Phase 4.

- `backend/app/models/database.py` + `backend/app/models/orm.py`: async
  SQLAlchemy 2.x ORM models for every table in docs/database-schema.md
  except `users`/`decision_scores`/`risks`/`assumptions` (explicitly
  Phase 4, per the brief) — `research_sessions`, `research_plans`,
  `alternatives`, `criteria`, `sources`, `documents`, `claims`, `evidence`,
  `contradictions`, `agent_runs`, `reports`, `citations`, `audit_logs`.
  Two documented deviations from the doc (see the module docstring in
  `orm.py`): (1) ids the agents themselves mint (`sources.id`,
  `claims.id`, `evidence.id`, `contradictions.id`) stay the plain strings
  the agents already generate (e.g. `"src-rq-1-0"`) rather than being
  re-minted as UUIDs at the persistence boundary, so the traceability
  invariant (state-schema.md: an id an agent emits is the id everything
  downstream references) survives the DB round-trip; (2)
  `research_sessions.state_snapshot` (JSON) holds the full validated
  `ResearchState` so `SessionRepository.get()` reconstructs an exact state
  without a hand-written bidirectional ORM<->Pydantic mapper for every
  nested type — the normalized tables are still fully populated on every
  write, this only changes how reads are reconstructed. `DATABASE_URL`
  unset falls back to an in-memory sqlite database via `aiosqlite`
  (`StaticPool`, one shared connection, since in-memory sqlite dies with
  its one connection) so the app and the whole test suite run fully
  offline with no live Postgres; a real deployment sets
  `DATABASE_URL=postgresql+psycopg://...` and gets the identical code path.
- `backend/alembic/`: one initial migration (`alembic revision
  --autogenerate`), `env.py` resolves its URL from the same
  `Settings.database_url` the app uses (stripping the async driver suffix,
  since Alembic's autogenerate/offline machinery is sync-only) so
  migrations and the app config never drift apart. Verified by applying it
  to a scratch sqlite file (`alembic upgrade head`); **not** verified
  against a live Postgres — that needs a real instance this environment
  doesn't have (see report).
- `backend/app/services/session_repository.py`: `SessionRepository`
  rewritten from Phase 1's in-memory dict to the Postgres/sqlite-backed
  ORM above, keeping the exact `create()`/`get()`/`update()` interface
  `app/api/research.py` and `app/services/research_service.py` already
  depend on (neither needed a single line changed). Every `update()`
  persists the full `ResearchState` and decomposes it into every
  normalized table above (plan/alternatives/criteria, sources, documents,
  claims+verification, evidence, contradictions, agent_runs, report+
  citations). Also adds `record_audit()` (used by `audit_service.py`) and
  `dispose()` (wired into `main.py`'s lifespan shutdown).
- `backend/app/services/audit_service.py`: `log_run()` writes one
  `audit_logs` row per agent run and one per verification cycle, from the
  final `ResearchState` of a completed run. Called once, from
  `ResearchService.run()` (the orchestration layer) — never from inside an
  agent module, so audit logging stays centralized instead of scattered.
- `backend/app/agents/source_evaluator.py`: weighted scoring formula
  (brief §5.5) `credibility = authority*w_a + relevance*w_r + recency*w_c +
  specificity*w_s + independence*w_i`, weights from
  `Settings.source_scoring_weights()` (`SOURCE_WEIGHT_*` env vars, never
  hardcoded). `relevance` reuses the Researcher's own
  `RetrievedDocument.relevance_score`; `recency` (exponential decay from
  `published_at`) and `independence` (penalizes repeated publishers in the
  same batch, docs/risk-register.md R6) are pure functions computed from
  source metadata; `authority`/`specificity` come from one batched LLM
  judge call — not domain-name ranking alone. `compute_credibility_score`,
  `recency_score`, and `independence_score` are exported as standalone
  pure functions so the formula is unit-testable without an LLM. Wired
  into the graph after the Researcher fan-in join, before the Evidence
  Analyst; writes to a new `evaluated_sources` `GraphState` key (not
  `sources` itself) so its wholesale replacement doesn't collide with the
  `operator.add` reducer `sources` needs for the Researcher's fan-out.
- `backend/app/agents/contradiction_detector.py`: given `verified_claims`,
  asks the LLM to do CONTEXTUAL comparison (version/date/workload/
  environment differences) before labeling a pair `conflict_type=genuine`
  vs. `context_mismatch`/`version_mismatch`/`temporal`/
  `workload_mismatch`/`environment_mismatch` (brief §5.7); every non-
  genuine category is treated as `resolution_status=resolved_context`
  (explained away by context), `genuine` stays `unresolved`. Judgments
  referencing a claim id that wasn't actually passed in are dropped
  (same grounding rule every other Phase 2/3 agent follows). Wired in
  after the Fact Checker, before the Final Synthesizer.
- `backend/app/verification/citation_validator.py` +
  `backend/app/verification/gate.py`: four deterministic, LLM-free checks
  (brief §5.13) — (1) every citation marker and evidence source id
  resolves to `state.sources` (docs/risk-register.md R1); (2) no claim the
  Fact Checker marked UNSUPPORTED/CONTRADICTED is silently dropped — it
  must be acknowledged in `limitations`; (3) every contradiction has a
  `resolution_status` other than fully-unaddressed (`"unresolved"`), or is
  itself listed in `limitations`; (4) low confidence is actually surfaced
  in `limitations`, not just reported as a bare number. On failure,
  `VerificationResult.routed_to` is `fact_checker` for unsupported-claim
  failures (the only agent that can re-verify them) and
  `final_synthesizer` for every other category. Wired as a LangGraph
  conditional edge after the Final Synthesizer: on failure it routes back
  to Fact Checker (then Contradiction Detector then Synthesizer again) or
  directly back to the Synthesizer; **the 3-cycle cap is a plain `cycle >=
  settings.verification_max_cycles` check in
  `app/orchestration/graph.py`'s node/routing functions**, not a prompt
  instruction — after the cap, `apply_cap_reached_limitations()` ships the
  report anyway with every unresolved issue appended to
  `final_report.limitations`.
- `backend/app/orchestration/graph.py`: full Phase 3 pipeline wired as
  described above. `GraphState` gained `evaluated_sources`,
  `contradictions` (plain, last-write-wins — a retry recomputes it, it
  doesn't accumulate across cycles), `verification_cycle` (plain int
  counter), and `verification_results` (`operator.add`, one history entry
  per cycle). Recursion limit raised from 50 to 100 to give the up-to-3
  extra retry cycles (4 nodes each) headroom alongside fan-out.
- `backend/app/config/settings.py`: `SourceScoringWeights` model +
  `SOURCE_WEIGHT_AUTHORITY`/`_RELEVANCE`/`_RECENCY`/`_SPECIFICITY`/
  `_INDEPENDENCE` (defaults 0.25/0.25/0.15/0.20/0.15, matching brief §5.5),
  `VERIFICATION_MAX_CYCLES` (default 3), `DATABASE_URL` +
  `effective_database_url` (sqlite fallback).
- `backend/.env.example`: documents every new env var above.
- `backend/pyproject.toml`: added `aiosqlite>=0.20` (test/dev DB driver)
  and `alembic>=1.13` (migrations).
- Tests: `tests/test_agents.py` gained Source Evaluator tests (weighted
  formula verified numerically, including a "100% weight on one factor"
  edge case and 0-1 clipping; recency decay; independence penalty; a
  full-agent run) and Contradiction Detector tests (a crafted fake
  `LLMProvider` distinguishes a `genuine` conflict from a
  `version_mismatch` one and drops a hallucinated claim-id pair — the
  same fake-provider pattern `test_graph.py`'s `_MultiQuestionProvider`
  already used for the planner). New `tests/test_verification_gate.py`:
  the gate passes a clean report, fails on an unresolvable citation
  (routes to `final_synthesizer`), fails on an unsupported claim (routes
  to `fact_checker`), fails on an unaddressed contradiction, fails on low
  confidence without limitations (and passes once limitations actually
  say so) — plus an explicit end-to-end test that the 3-cycle cap
  terminates a run that can never pass the gate (`LocalProvider`'s
  Fact Checker always defaults to UNSUPPORTED) rather than looping
  forever, asserting `verification_cycles_used == 3` and that the report
  still ships with the unresolved issues under `limitations`. New
  `tests/test_session_repository.py`: create/get/update round-trip, every
  normalized table populated, idempotent re-`update()` doesn't duplicate
  `agent_runs`, two repository instances get isolated in-memory databases,
  `record_audit()` writes a row — all against the sqlite/aiosqlite path
  (no live Postgres in this environment). New `tests/test_audit_service.py`:
  one audit row per agent run plus one per verification cycle.
  `tests/test_graph.py` updated for the new node set/pipeline shape
  (`source_evaluator`/`contradiction_detector`/`verification_gate` all
  present; scored sources; `verification_cycles_used` matches the
  recorded cycle history).
- `pytest` from `backend/`: 47 passed (25 Phase 1+2 + 22 new Phase 3
  tests; no earlier test was deleted). A live Postgres was not available
  in this environment — the migration was verified against a scratch
  sqlite file only; applying `alembic upgrade head` to a real Postgres
  instance is the one thing this phase could not verify directly.

## Phase 4 — 2026-09-20

Decision intelligence: Advocate/Critic debate pass, Assumption Analyst,
Decision Analyst (weighted matrix + mandatory sensitivity analysis), and
Risk Analyst, per `docs/phase0-plan.md` and `docs/architecture.md` §3-4 and
brief §5.6/§5.9/§5.10/§5.11/§11. Pipeline is now Planner -> Researcher
(fan-out/join) -> Source Evaluator -> Evidence Analyst -> Fact Checker ->
Contradiction Detector -> Advocate/Critic -> Assumption Analyst -> Decision
Analyst -> Risk Analyst -> Final Synthesizer -> Verification Gate
(conditional loop, max 3 cycles) -> END.

- `backend/app/agents/decision_analyst.py`: the LLM scores each
  (alternative, criterion) pair 0-10 (10 = best outcome, direction already
  accounted for — the prompt says so explicitly) with a rationale and
  evidence ids; every number that decides the recommendation is then
  computed in plain Python and never trusted from the model:
  `normalize_weights()` (criteria weights always renormalized to sum to 1,
  falls back to an equal split if every declared weight is non-positive),
  `compute_weighted_totals()` (pure weighted sum, unit-tested against a
  hand-computed fixture), `pick_recommended()` (deterministic argmax,
  ties broken by plan order). Ungrounded (alternative, criterion) pairs
  the model didn't return get an explained neutral-score entry rather than
  being silently dropped — every pair the `DecisionMatrix` schema implies
  must exist actually does. Hallucinated evidence ids are filtered out,
  same rule as every other Phase 2/3 agent.
- `backend/app/decision/sensitivity.py`: mandatory, pure-code sensitivity
  analysis (brief §11) — never a second LLM call. For every criterion,
  perturbs its normalized weight by ±`Settings.
  sensitivity_weight_perturbation` (default 20%), renormalizes the rest
  proportionally (`perturb_weights()`), recomputes `weighted_totals` with
  the *same* scores, and records one `SensitivityResult` per (criterion,
  direction) pair. `is_sensitive()` is true if ANY perturbation flips the
  recommendation.
- `backend/app/decision/severity.py`: `Risk.severity` is always looked up
  from an explicit `probability x impact` table (1-3 level weights,
  product/9, rounded to 3dp) — `compute_severity()` — never LLM-eyeballed.
- `backend/app/agents/risk_analyst.py`: LLM proposes candidate risks
  (category/description/probability/impact/mitigation/evidence ids);
  `severity` is always `compute_severity(probability, impact)`, never taken
  from the model. When evidence coverage is thinner than
  `Settings.risk_thin_evidence_threshold` (default 3 `EvidenceItem`s), an
  `unknown`-category risk is guaranteed in the output even if the model
  proposed none.
- `backend/app/agents/debate.py`: exactly one Advocate LLM call (builds the
  strongest case for every alternative, capped at
  `Settings.debate_max_alternatives`, default 5, in that single call) and
  exactly one Critic LLM call (attacks the Advocate's notes in that single
  call) — never per-alternative, structurally bounded, not just documented.
  Every critic note must cite an evidence id OR clear a minimum rationale
  length (`_MIN_RATIONALE_CHARS`); bare disagreement with neither is
  dropped in code, since the brief requires every criticism to be
  justified. Writes `DebateNote`s (new schema, see below).
- `backend/app/agents/assumption_analyst.py`: `plan.assumptions` (planner-
  stated, pre-evidence) become `Assumption`s with a deterministic
  `origin="hypothetical"` label, no LLM judgment involved. A second,
  LLM-judged pass proposes additional assumptions implicit in the evidence
  and debate notes, each labeled `user_provided`/`evidence_backed`/
  `inferred`/`hypothetical` by the model (like `evidence_type`/`strength`
  in the Evidence Analyst) — `affects` is filtered to real alternative/
  criterion names.
- `backend/app/schemas/state.py`: new `DebateNote` model (`role`,
  `alternative`, `claim`, `rationale`, `evidence_ids`, `target_note_id`);
  `ResearchState.debate_notes` field added.
- `backend/app/agents/synthesizer.py`: `decision_matrix`/`risks`/
  `assumptions`, once the graph provides them, deterministically OVERWRITE
  the LLM's own guess at those `FinalReport` sections — the dedicated
  analysts are the source of truth, same grounding rule as sources/
  evidence/citations. If `is_sensitive(decision_matrix.sensitivity)`, a
  "Decision is sensitive to weighting" warning is appended to
  `limitations` and folded into `decision_rationale`, never silently
  dropped.
- `backend/app/orchestration/graph.py`: wired Advocate/Critic ->
  Assumption Analyst -> Decision Analyst -> Risk Analyst between
  Contradiction Detector and the Final Synthesizer, sequentially rather
  than as a parallel fan-out — Risk Analyst needs the Decision Analyst's
  `decision_matrix` as context, so a true fan-out would still need a join
  before it; sequential is simpler and no less correct for four
  single-shot nodes (brief: "otherwise sequential is fine, don't force
  parallelism the graph doesn't need"). `GraphState` gained
  `debate_notes`/`assumptions`/`decision_matrix`/`risks` (all plain,
  last-write-wins — each node's output is the full current value, not an
  accumulation across verification retries).
- `backend/app/models/orm.py`: `RiskORM`/`AssumptionORM`/
  `DecisionScoreORM`, completing the docs/database-schema.md tables Phase 3
  deliberately left out (`users` remains out of scope, per the brief).
  `decision_scores.alternative_id`/`criterion_id` are nullable FKs resolved
  by `(plan_id, name)` lookup against the `alternatives`/`criteria` rows
  `SessionRepository._upsert_plan` already recreates per update (agents
  never mint a stable id for an alternative/criterion) — redundant
  `alternative_name`/`criterion_name` columns keep the row meaningful even
  when the id lookup misses (a deviation from the doc, same spirit as
  Phase 3's two documented deviations).
- `backend/alembic/versions/dee60aeb1011_*.py`: hand-written (not
  autogenerated, since autogenerate against the sqlite fallback can't see
  a "real" prior state) migration adding `risks`/`assumptions`/
  `decision_scores`, verified against a scratch sqlite file the same way
  Phase 3's migration was (no live Postgres in this environment).
- `backend/app/services/session_repository.py`: `_upsert_risks()`/
  `_upsert_assumptions()`/`_upsert_decision_scores()`, called from
  `_upsert_session()` alongside the existing normalized-table writers;
  `audit_service.py` needed no changes (it already logs every agent run
  generically, including the four new agents, from `agent_runs`).
- `backend/app/config/settings.py` + `backend/.env.example`:
  `debate_max_alternatives`/`debate_advocate_max_tokens`/
  `debate_critic_max_tokens`, `risk_thin_evidence_threshold`,
  `sensitivity_weight_perturbation` — all config, never hardcoded.
- Tests: new `tests/test_phase4.py` (17 tests) — Decision Analyst's
  weighted totals against a hand-computed fixture and evidence-id
  grounding; sensitivity analysis correctly detects a recommendation flip
  vs. a stable case, and weight renormalization sums to 1; the severity
  lookup table's values and Risk Analyst's thin-evidence `unknown`
  fallback; Advocate/Critic produces non-empty, evidence-referencing debate
  notes and drops an unjustified critic attack; Assumption Analyst labels
  planner-stated vs. LLM-proposed origins correctly on a crafted fixture
  and filters ungrounded `affects`. `tests/test_graph.py` updated: node set
  includes the four new agents; end-to-end assertions that
  `final_report.comparative_analysis`/`.risk_analysis`/`.assumptions` are
  populated from the dedicated analysts (not the synthesizer's own guess);
  a new crafted-fixture test forces a recommendation flip under a ±20%
  reweighting and asserts the "sensitive to weighting" language actually
  lands in `final_report.limitations`/`decision_rationale`.
  `tests/test_session_repository.py` gained a Phase 4 persistence test
  (risks/assumptions/decision_scores round-trip, including FK resolution
  by name against freshly-recreated `alternatives`/`criteria` rows).
- `pytest` from `backend/`: 66 passed (47 Phase 1-3 + 17 new Phase 4 tests
  + 2 extended Phase 3 tests; no earlier test was deleted). A live
  Postgres was not available in this environment — the new migration was
  verified against a scratch sqlite file only, same limitation as Phase 3.

## Phase 5 — 2026-09-20

RAG pipeline: real ingestion -> chunk -> embed -> Qdrant -> hybrid (semantic +
keyword) retrieval -> rerank, per `docs/phase0-plan.md` and
`docs/architecture.md` §2/§8, brief §5.3/§8/§13. The Researcher agent gets a
working internal-knowledge-base `vector_search`/`document_search` tool
alongside its existing external `SearchProvider`, wired through the same
grounding rules every prior phase's agents follow (no hallucinated source
ids). New `backend/app/retrieval/` package:

- `chunking.py`: `chunk_text()` — recursive character splitting (paragraph ->
  line -> sentence -> word -> hard-character fallback), then greedy packing
  up to `ChunkConfig.chunk_size` with `chunk_overlap` characters of trailing
  context carried into the next chunk. Not the naive fixed-length-no-overlap
  split the brief warns against; each `TextChunk` also carries its `start_char`/
  `end_char` span in the original text for citation traceability.
- `embeddings.py`: `EmbeddingProvider` ABC (mirrors `LLMProvider`/
  `SearchProvider`'s shape) + `SentenceTransformersProvider` (local
  `all-MiniLM-L6-v2`, 384-dim, lazy model load — constructing the class or
  importing the module never downloads anything, only the first `embed()`
  call does) + `LocalEmbeddingProvider` (deterministic SHA-256-seeded fake
  vectors, no model at all — same role `LocalProvider`/`LocalSearchProvider`
  play elsewhere) + `get_embedding_provider()` factory. `EMBEDDING_PROVIDER`
  defaults to `local` so the app/test suite stay fully offline by default,
  matching every earlier phase's design goal.
- `vector_store.py`: `VectorStore` ABC + `ChunkMetadata` (document_id,
  chunk_id, source, title, author, date, section, document_type, url, per the
  deliverable spec) + `QdrantVectorStore` (real Qdrant client, lazy
  connection/collection creation, payload filters map onto Qdrant's
  `Filter`/`FieldCondition`/`MatchValue`) + `InMemoryVectorStore` (cosine
  similarity over a python dict — no running Qdrant needed, offline dev/test
  fake) + `get_vector_store()` factory (`QDRANT_URL` unset -> in-memory,
  matching `effective_database_url`'s sqlite fallback pattern).
- `hybrid_retrieval.py`: `KeywordIndex` — a real, pure-python BM25
  implementation (not a fake/stub) over ingested chunk text — plus
  `hybrid_search()`, which runs the vector store query and the BM25 search,
  min-max normalizes each ranking, and merges/dedupes by chunk id with an
  `alpha`-weighted sum (`HYBRID_RETRIEVAL_ALPHA`, default 0.5) — genuinely
  hybrid, never two vector-search calls dressed up as one. `HybridRetriever`
  bundles a vector store + embedding provider + keyword index into one
  `search()` call; `get_hybrid_retriever()` factory.
- `reranking.py`: `Reranker` ABC + `LexicalRecencyReranker` (default —
  deterministic query/chunk token-overlap plus a small `ChunkMetadata.date`
  recency boost, zero extra model load, keeps the default config fully
  offline) + `CrossEncoderReranker` (real
  `cross-encoder/ms-marco-MiniLM-L-6-v2` cross-encoder via
  `sentence-transformers`, lazy-loaded, opt-in via `RERANKER=cross_encoder`
  since it's strictly more accurate but costs a second model
  load/materially more latency — tradeoff documented in the module
  docstring rather than defaulting to it) + `get_reranker()` factory.
- `ingestion.py`: `IngestionPipeline.ingest_document(text, metadata) ->
  list[chunk_ids]` — clean -> `chunk_text()` -> embed -> `vector_store.upsert()`
  -> `keyword_index.add()`, wired entirely through the ABCs above so swapping
  `InMemoryVectorStore`/`LocalEmbeddingProvider` for the real Qdrant/
  sentence-transformers implementations never touches this module.
  `DocumentMetadata` mirrors `ChunkMetadata` minus the per-chunk fields;
  PostgreSQL remains the system of record for document metadata
  (docs/database-schema.md's Qdrant note) — this module only turns a
  document's text into searchable chunks.
- `backend/app/agents/researcher.py`: new optional `kb: HybridRetriever |
  None` parameter on `run()`. When provided, a `kb.search()` call (tool
  `kb.search`, bounded-failure like the existing `search.search` call — a
  broken KB degrades to web-only results, never crashes the agent) runs
  alongside the external `SearchProvider` call; both result sets normalize
  into a common `_RetrievedItem` shape before claim extraction and
  `RetrievedDocument`/`Source`/`Claim` construction, so downstream agents
  never need to know whether a result came from the web or the internal KB.
  KB hits carry `source_type="internal_kb"` (or whatever `document_type` the
  chunk's metadata declares) and their `relevance_score` from the hybrid
  merge's `combined_score`, rather than the fixed `0.5` placeholder web
  results get. Omitting `kb` (every pre-Phase-5 call site) falls back to the
  exact Phase 2-4 behavior — no existing test needed to change.
- `backend/app/orchestration/graph.py`, `app/services/research_service.py`,
  `app/api/deps.py`, `app/api/research.py`, `app/main.py`: `kb` threaded
  through `build_graph()`/`run_research_graph()`/`ResearchService` as an
  optional parameter (default `None`, so every Phase 2-4 caller/test is
  unaffected). The live API wires a single process-lifetime
  `HybridRetriever` onto `app.state.retrieval_pipeline` in `create_app()`
  (`get_hybrid_retriever(settings)`) — same singleton-on-`app.state` pattern
  `SessionRepository` already uses — so the `InMemoryVectorStore` fallback's
  ingested documents and the `KeywordIndex` actually persist across
  requests within one process instead of resetting per-request.
- `backend/scripts/ingest_documents.py`: CLI — ingests a directory of
  `.txt`/`.md` files (`--recursive` for subdirectories) through the exact
  same `IngestionPipeline` the API uses, assigning each file's relative path
  as its `document_id`. Respects `Settings` exactly like the app (offline by
  default against the in-memory store; point `QDRANT_URL` at a running
  instance for a persistent demo KB).
- `backend/app/config/settings.py` + `backend/.env.example`:
  `EMBEDDING_PROVIDER`/`EMBEDDING_MODEL`/`EMBEDDING_DIMENSION`,
  `QDRANT_URL`/`QDRANT_API_KEY`/`QDRANT_COLLECTION`,
  `CHUNK_SIZE`/`CHUNK_OVERLAP`, `HYBRID_RETRIEVAL_ALPHA`,
  `RERANKER`/`RERANKER_MODEL`/`RERANKER_RECENCY_WEIGHT` — all config, never
  hardcoded, all defaulting to fully-offline operation.
- `backend/pyproject.toml`: added `qdrant-client>=1.10` and
  `sentence-transformers>=3.0` (chosen over a hosted embeddings API
  specifically to keep the "works offline, no API key required" property
  this repo has held every phase — brief §8 leaves the embedding provider
  choice open).
- Tests: new `tests/test_chunking.py` (7 — empty/short/long text, real
  overlap between consecutive chunks including an explicit "not the naive
  fixed-length-no-overlap split" guard, span correctness, config
  validation), `tests/test_embeddings.py` (8 — lazy construction, factory
  selection, `LocalEmbeddingProvider` fixed-dimension/deterministic/
  distinct/unit-norm vectors, one real-model test skipped if
  `sentence-transformers`/the cached model isn't available — it was
  available in this environment, verified passing), `tests/test_vector_store.py`
  (7 — factory selection, lazy Qdrant construction, `InMemoryVectorStore`
  nearest-neighbor ordering on a crafted fixture, top_k, metadata filters,
  upsert-replace idempotency), `tests/test_hybrid_retrieval.py` (5 — BM25
  ranks exact-term matches correctly and handles re-indexing, hybrid search
  merges+dedupes semantic and keyword hits on a crafted "same text as query"
  fixture, facade parity, empty-index edge case), `tests/test_reranking.py`
  (7 — factory selection, lazy cross-encoder construction, a crafted case
  where the lexical reranker demonstrably reorders a hybrid merge's "wrong"
  ranking, recency tie-breaking, top_k truncation, one real cross-encoder
  test skipped if unavailable — verified passing here too),
  `tests/test_ingestion.py` (4 — end-to-end text-in/chunks-searchable-out,
  empty text, hybrid-searchable after ingestion, multi-document isolation),
  and two new tests in `tests/test_agents.py` — the Researcher's
  `vector_search` path returns KB-grounded `RetrievedDocument`s merged with
  web results (every claim/source id still traces to something actually
  retrieved) and a broken KB degrades to web-only results rather than
  crashing the agent (same bounded-failure contract `search.search`
  already had).
- `pytest` from `backend/`: 106 passed (66 Phase 1-4 + 40 new Phase 5
  tests; no earlier test was deleted). Both `sentence-transformers`
  (`all-MiniLM-L6-v2`) and the cross-encoder reranker
  (`cross-encoder/ms-marco-MiniLM-L-6-v2`) were already cached locally in
  this environment, so their real-model tests ran (not skipped) rather than
  only being exercised via the offline fakes — `qdrant-client` was
  installed but a real Qdrant instance was not available, so
  `QdrantVectorStore` is covered by construction/factory tests only, same
  "no live service in this environment" limitation Phase 3/4's Postgres
  tests already documented.

## Phase 6 — 2026-09-20

Production infrastructure, per `docs/phase0-plan.md` Phase 6 / brief §6, §15,
§16, §26: Redis-backed result + semantic caching, a durable background job
runner so research runs survive an API process restart, retry/circuit-breaker
resilience around every real external call, and OpenTelemetry tracing +
structured JSON logging wired through every agent run and job-runner state
transition.

- `backend/app/tools/resilience.py` (new): `with_retry()` (exponential
  backoff + jitter, hard-capped at `max_attempts` — never infinite, built on
  `tenacity` rather than a hand-rolled loop) and `CircuitBreaker`
  (closed/open/half-open, per-provider-instance, `reset_timeout_seconds`
  cooldown). `ResilienceConfig` bundles both sets of knobs from `Settings`
  (config, never hardcoded) and is threaded into every real provider's
  `__init__`: `OpenAIProvider`, `AnthropicProvider`
  (`app/tools/llm_provider.py`), `TavilyProvider`
  (`app/tools/search_provider.py`), `SentenceTransformersProvider`
  (`app/retrieval/embeddings.py`), `QdrantVectorStore`
  (`app/retrieval/vector_store.py`). The `Local*`/`InMemory*` fakes are
  deliberately left untouched — they must stay fast/deterministic for the
  test suite.
- `backend/app/tools/llm_provider.py`: `OpenAIProvider.complete()` and
  `AnthropicProvider.complete()` now retry on invalid JSON from the model,
  bounded at `MAX_JSON_VALIDATION_RETRIES = 2` (docs/architecture.md §7's
  documented-but-previously-unimplemented "bounded retry (max 2) with the
  validation error fed back to the model"), in addition to the existing
  transport-level `with_retry`/circuit-breaker wrapping for timeouts/rate
  limits/provider-unavailable.
- `backend/app/services/cache_service.py` (new): `CacheService` ABC with an
  exact-key result cache (`get`/`set`) and an embedding-keyed semantic cache
  (`get_semantic`/`set_semantic`, cosine-similarity threshold).
  `RedisCacheService` (lazy `redis.asyncio` client; semantic entries are a
  capped per-namespace Redis list, compared client-side — Redis has no
  built-in vector index without the RediSearch module, a documented
  limitation rather than an oversight) and `LocalCacheService` (in-memory
  fake, used whenever `REDIS_URL` is unset — including the whole test
  suite). Lives in `app/services/`, not `app/memory/`: `docs/
  project-structure.md` scopes `memory/` to agents' own short/working/
  long-term memory, a different concern from caching provider calls across
  runs.
- `backend/app/retrieval/hybrid_retrieval.py`: `HybridRetriever` takes an
  optional `cache`; `search()` embeds the query, checks the semantic cache
  first (skipping vector-store + BM25 + merge entirely on a hit), and
  populates it on a miss — docs/architecture.md §6's "semantic cache in
  front of the Research Agent's search+retrieval step." Filtered queries are
  never cached (a filter-agnostic embedding match could return
  filter-violating results). `get_hybrid_retriever()` takes the new optional
  `cache` param.
- `backend/app/services/research_service.py`: `ResearchService` takes an
  optional `cache`; an identical `question` + `mode` + provider-name combo
  within `CACHE_RESULT_TTL_SECONDS` skips the entire graph run and reuses
  the prior `ResearchState` (with a fresh `request`/`execution_metadata`
  swapped in so the new session's identity is still correct).
- `backend/app/services/job_runner.py` (new): `JobStore` ABC +
  `PostgresJobStore` (same lazy-init-tables pattern as `SessionRepository`)
  + `JobRunner` (bounded-concurrency `asyncio` worker pool: a dispatcher
  loop turns queued job ids into tasks, each gated by a `Semaphore`).
  `JobRunner.start()` is idempotent, recovers every `pending`/`running` row
  from `jobs` (a `running` row means the previous process died mid-job) and
  requeues it — the actual "survives an API process restart" behavior — and
  is also called lazily from `enqueue()` so job processing works under a
  test harness that never drives FastAPI's lifespan (see `app/main.py`'s
  existing comment on ASGI test transports). Celery was explicitly skipped
  for now (module docstring): every earlier phase stayed dependency-light
  and fully offline-testable, and the actual requirement (durable state,
  crash recovery, bounded concurrency) doesn't need a broker — `JobStore`/
  `JobHandler` are the seam a `CeleryJobStore` would plug into later without
  touching `ResearchService`, agents, or the graph.
- `backend/app/models/orm.py`: new `JobORM` (`jobs` table) — `id`,
  `job_type`, `payload` (JSON), `status`, `attempts`, `created_at`/
  `started_at`/`completed_at`, `error`. Deliberately separate from
  `research_sessions.status` (an execution record vs. a research record; a
  future non-research job type would have nowhere to live if merged).
- `backend/app/api/research.py`: `POST /research` now enqueues a
  `research_run` job via `JobRunner` instead of calling `BackgroundTasks.
  add_task()` — a job in flight when the API process restarts is durable
  Postgres state, not lost in-memory work.
- `backend/app/main.py`: builds the `JobRunner`/`PostgresJobStore`/cache
  service as process-lifetime singletons on `app.state` (same pattern as
  `session_repository`/`retrieval_pipeline`); `lifespan()` calls
  `job_runner.start()` on boot (the recovery pass) and `job_runner.stop()`
  on shutdown. Also calls `configure_logging()`/`configure_tracing()` at
  import time.
- `backend/app/observability/logging.py` (new): `JsonFormatter` (one JSON
  object per log line — `timestamp`/`level`/`logger`/`message` plus every
  `extra` field) + `configure_logging()` (idempotent root-logger setup) +
  `log_event()` (the call-site API: `trace_id`/`agent`/`latency_ms`/
  `tokens`/`status` per brief §15's example shape, plus free-form `**extra`).
- `backend/app/observability/tracing.py` (new): `configure_tracing()`
  (idempotent `TracerProvider` install; `OTEL_EXPORTER=console` — default,
  zero extra infra — or `otlp`, lazily importing the OTLP exporter package
  only when selected) + `start_span()` (context manager; safe even without
  `configure_tracing()`, via OTel's no-op default provider) + `record_span()`
  (records an already-finished span with explicit start/end timestamps, for
  `_common.py`'s "the agent's name isn't known until the end of the timed
  block" case).
- `backend/app/agents/_common.py`: `timed_run()`'s `_Timer.meta()` now also
  emits one `record_span("agent.<name>", ...)` OTel span and one
  `log_event(..., event="agent_run", ...)` structured log line per agent
  run, so every node in the graph is traced/logged uniformly without each
  agent module touching `app/observability/` directly.
- `backend/app/config/settings.py` / `backend/.env.example`: `REDIS_URL`,
  `CACHE_RESULT_TTL_SECONDS`, `CACHE_SEMANTIC_TTL_SECONDS`,
  `CACHE_SEMANTIC_SIMILARITY_THRESHOLD`, `JOB_RUNNER_CONCURRENCY`,
  `RESILIENCE_MAX_ATTEMPTS`/`RESILIENCE_BASE_DELAY_SECONDS`/
  `RESILIENCE_MAX_DELAY_SECONDS`/`RESILIENCE_CIRCUIT_FAILURE_THRESHOLD`/
  `RESILIENCE_CIRCUIT_RESET_SECONDS`, `OTEL_EXPORTER`/
  `OTEL_EXPORTER_OTLP_ENDPOINT`. All unset/defaulted work fully offline, same
  design goal every earlier phase followed.
- `backend/pyproject.toml`: added `redis`, `opentelemetry-api`,
  `opentelemetry-sdk`, `tenacity` (already a transitive dependency via
  `langchain-core`, now declared directly since `app/tools/resilience.py`
  imports it).
- Tests: `tests/test_cache_service.py` (7 — exact-key hit/miss/namespace
  isolation/TTL expiry, semantic hit above threshold, miss below threshold,
  TTL expiry, empty-namespace miss), `tests/test_resilience.py` (10 —
  `with_retry` succeeds after N transient failures then stops retrying,
  gives up at the hard cap without exceeding it, rejects a non-positive
  `max_attempts`, only retries matching exception types; `CircuitBreaker`
  opens after the failure threshold, half-opens after the cooldown, closes
  on a post-half-open success, reopens on a post-half-open failure; a
  `with_retry(..., breaker=...)` integration case), `tests/
  test_job_runner.py` (4 — `enqueue()` persists a pending/running row, a
  successful job transitions to `completed`, a handler exception is caught
  and the job transitions to `failed` without crashing the runner, and the
  key recovery case: a job manually left `running` in the jobs table — a
  simulated crash — is picked back up and completed by a *fresh* `JobRunner`
  instance built against the same store), `tests/test_observability.py`
  (3 — `log_event` emits one parseable JSON line with the required brief
  §15 fields, arbitrary `**extra` fields round-trip, `start_span`/
  `record_span` never raise without a configured exporter), plus new cases
  added to `tests/test_llm_provider.py` (OpenAI JSON-validation retry
  succeeds on the second attempt and is bounded at
  `MAX_JSON_VALIDATION_RETRIES + 1` total attempts when every attempt
  fails), `tests/test_hybrid_retrieval.py` (semantic cache short-circuits a
  repeat query), and `tests/test_research_service.py` (result-cache reuse
  across two different `research_id`s for an identical question; no reuse
  when no cache is wired).
- `pytest` from `backend/`: 134 passed (106 Phase 1-5 + 28 new Phase 6
  tests; no earlier test was deleted or modified in a way that changes its
  meaning — `test_research_service.py`'s pre-existing tests were left as
  they were).
- Deviations from the brief, and why:
  - Lightweight `asyncio` job runner instead of Celery — explicitly allowed
    by brief §6 ("Celery/Redis OR lightweight async job architecture for
    MVP"); see `app/services/job_runner.py`'s module docstring for the
    dependency-weight rationale and the `JobStore`/`JobHandler` upgrade seam.
  - The semantic cache's similarity search is a client-side brute-force scan
    (bounded per namespace by `_SEMANTIC_MAX_ENTRIES = 500` in Redis), not a
    real vector index — Redis has no built-in one without the RediSearch
    module, and pulling that in would be exactly the infra weight this MVP
    avoids; acceptable at the entry counts a single-process semantic cache
    actually holds, called out as a documented limitation in
    `cache_service.py`.
  - Caching lives in `app/services/cache_service.py`, not `app/memory/`:
    `docs/project-structure.md` scopes `memory/` to agents' own short/
    working/long-term memory layers, which is a different concern from
    caching deterministic provider calls across runs — closer to
    `session_repository.py`'s role than to agent memory.
  - No live Redis/OTLP collector was available in this environment, so
    `RedisCacheService` and the OTLP exporter path are covered by
    construction/factory-selection tests only (`LocalCacheService`/console
    exporter are exercised for real everywhere else) — same "no live
    service in this environment" limitation Phase 3/4/5's Postgres/Qdrant
    tests already documented.

## Phase 7 — 2026-09-20

Frontend: a real Next.js 14 (App Router) + TypeScript (strict) + Tailwind
dashboard against the backend's actual API surface, per `docs/phase0-plan.md`
Phase 7 and brief §19-20. Backend additions are limited to thin read
endpoints over data `ResearchState`/Postgres already persist — no new
business logic, per the "frontend renders/aggregates, doesn't recompute"
rule.

### Backend additions (`backend/app/`)

docs/api.md's Phase 0 draft documented `/sources`, `/claims`, `/evidence`,
`/decision`, `/trace`, `/report`, and SSE `/stream`; only `POST /research`
and `GET /research/{id}` actually existed going into this phase. Added:

- `GET /api/v1/research` (`list_research`): paginated (`limit`, default 50)
  newest-first session summaries for the Dashboard — question, status,
  mode, derived `stage`, confidence, source/risk counts. Backed by a new
  `SessionRepository.list_recent()`.
- `GET /api/v1/research/{id}/sources` — `state.sources`.
- `GET /api/v1/research/{id}/claims` — `state.claims` joined with their
  `ClaimVerification` by `claim_id`.
- `GET /api/v1/research/{id}/evidence` — `state.evidence`, filterable via
  `?evidence_type=` and `?min_confidence=` (docs/api.md's documented
  filters).
- `GET /api/v1/research/{id}/decision` — `state.decision_matrix` (404 if the
  Decision Analyst hasn't run yet).
- `GET /api/v1/research/{id}/trace` — `state.execution_metadata`
  (`AgentRunMeta[]` with latency/tokens/tool calls/errors/confidence) plus
  the fixed `PIPELINE_STAGES` order, for the Agent Trace UI.
- `GET /api/v1/research/{id}/report` — alias of the status payload's
  `report` field, 404 until `final_report` exists.
- `GET /api/v1/research/{id}` (existing endpoint) now also returns a derived
  `stage` (mapped from the last completed `AgentRunMeta.agent_name` via the
  fixed pipeline order), `progress` (`completed_stages`/`total_stages`), and
  `question`/`created_at` — enough for the Active Research page's stage
  indicator via polling, since no SSE stream exists.
- **No SSE `/stream` endpoint was added** — implementing a real
  server-push stream over the job-runner-driven graph execution was out of
  scope for this pass; the frontend instead polls `GET /research/{id}`
  every 2s (`frontend/src/hooks/useResearchStatus.ts`), which is sufficient
  for the stage indicator and is explicitly allowed by the task brief
  ("poll the status endpoint if SSE isn't wired yet"). Documented as a gap,
  not silently worked around.
- `app/main.py`: added `CORSMiddleware` (new `Settings.cors_allow_origins`,
  defaulting to `localhost:3000`) — required for the browser-based frontend
  to call the API cross-origin; there was no CORS handling at all before
  this phase.
- **Bug fix, not just an addition**: `SessionRepository`'s sqlite dev/test
  engine (`app/models/database.py`) uses a single shared `StaticPool`
  connection. Exercising the new endpoints via real HTTP polling (as the
  frontend's `useResearchStatus` hook does) exposed a genuine race: a GET
  landing mid-way through a run's multi-statement `_upsert_session` write
  could read back a session with `status="completed"` but empty
  `sources`/`final_report` — not just stale, but a corrupted read.
  `SessionRepository` now serializes all sqlite reads/writes through a
  per-instance `asyncio.Lock` (`_db_lock`); it's a no-op on Postgres (real
  per-connection pooling/isolation), so production is unaffected. Regression
  test: `backend/tests/test_api.py::test_concurrent_polling_does_not_corrupt_session_state`.
- Tests: `backend/tests/test_api.py` gained
  `test_phase7_read_endpoints_after_completion`,
  `test_phase7_endpoints_404_for_unknown_research`, and the concurrency
  regression test above. Full suite: **137 passed** (134 pre-existing + 3
  new), run 5x consecutively with no flakes after the `_db_lock` fix.

### Frontend (`frontend/`)

New Next.js 14 App Router project, TypeScript strict mode, Tailwind CSS,
matching `docs/project-structure.md`'s `frontend/src/{app,components,
features,hooks,lib,types}` layout:

- `src/types/state.ts`, `src/types/api.ts` — hand-mirrored TS types for
  every backend Pydantic model actually in use (`ResearchRequest`,
  `ResearchPlan`, `Source`, `Claim`, `EvidenceItem`, `Conflict`,
  `Assumption`, `Risk`, `DecisionMatrix`, `SensitivityResult`,
  `AgentRunMeta`, `FinalReport`, the new response envelopes, and
  `PIPELINE_STAGES`/`STAGE_LABELS`).
- `src/lib/api.ts` — the single fetch-based API client (base URL from
  `NEXT_PUBLIC_API_URL`); no component calls `fetch()` directly.
- `src/lib/format.ts` — shared date/percent/duration formatting.
- `src/hooks/useResearchStatus.ts` (polling live progress),
  `useResearchList.ts` (Dashboard, light auto-refresh), `useReport.ts`.
- `src/components/`: `StatusBadge`, `ConfidenceBar`, `CitationLink`
  (+ `renderTextWithCitations` for inline `[S3]` markers), `DataTable`,
  `StageIndicator`, `Card`/`EmptyState`/`PageHeader`, `NavSidebar`.
- `src/features/`: `dashboard`, `new-research`, `active-research`,
  `research-session` (tab nav shared by all `/research/[id]/*` pages),
  `report`, `evidence-explorer`, `source-explorer`, `decision-matrix`,
  `agent-trace`.
- `src/app/`: Dashboard (`/`), New Research (`/new`), and a
  `/research/[id]/*` route group with Overview, Report, Evidence, Sources,
  Decision Matrix, and Agent Trace tabs, per brief §19 pages 1-8. History
  (`/history`) and Settings (`/settings`) are explicit stubs (§9-10, noted
  as such in-page) — History currently reuses the Dashboard list (no
  dedicated search/date filtering), Settings only surfaces the frontend's
  own `NEXT_PUBLIC_API_URL`, since the backend has no settings endpoints.
- Agent Trace UI (brief §20): pipeline graph built from the fixed stage
  order, grouping `AgentRunMeta[]` by `agent_name` per stage (correctly
  showing multiple runs per stage for both the Researcher fan-out and
  verification-loop retries of fact_checker→...→synthesizer). Clicking a
  run shows its full `AgentRunMeta` (model, latency, tokens, tool calls,
  confidence, errors). Noted in-page: per-agent prompt/response text isn't
  persisted in `AgentRunMeta` today, so literal input/output isn't shown —
  only run metadata.
- Decision Matrix view: weighted criteria × alternatives table (hover a
  score for its rationale) plus the sensitivity analysis table, with
  "Sensitive"/"Stable" rows and a note on which criteria would flip the
  recommendation.
- Report page renders all `FinalReport` sections: executive summary,
  alternatives/criteria, key findings, evidence (with confidence bars and
  source links), contradictions, comparative analysis table, risk table,
  assumptions, decision rationale, confidence, limitations, and sources
  (anchored so citation markers like `[S3]` jump to the matching source).

### Verification

- `npm install && npm run build` in `frontend/`: **succeeds** — TypeScript
  strict-mode type-checking, ESLint, and static/dynamic route generation
  all pass with zero errors (one unescaped-quote ESLint fix applied during
  the pass). `tsc --noEmit` also run standalone: clean.
- End-to-end manual verification via a live backend (`uvicorn`, local/dev
  providers) and the Next.js dev server, driven through an actual browser:
  submitted a research question via the New Research form, watched the
  Active Research stage indicator complete all 12 stages, then verified
  Report, Decision Matrix, and Agent Trace (including clicking a node for
  its run detail) all render real data from the API. Dashboard/CORS
  confirmed working cross-origin (`localhost:3000` → `localhost:8000`).
- `npm audit`: a handful of high/critical advisories remain, all in dev-only
  tooling (`eslint-config-next`'s transitive `glob`) or an image-optimizer
  DoS path this app doesn't use (no `next/image` `remotePatterns`
  configured); fixing them requires a Next.js 15/16 major bump, out of
  scope for this pass.

### Deviations / incomplete

- No SSE endpoint (see above) — polling only.
- History and Settings pages are stubs, per the brief's explicit
  allowance ("Research History and System Settings pages ... can be
  minimal/stub if time-constrained").
- Assisted/manual mode's `/approve` human-in-the-loop endpoint (docs/api.md)
  was not implemented; the New Research form lets a user pick `assisted`/
  `manual` mode (passed straight to the existing `POST /research`), but the
  frontend has no UI to act on a paused graph node since the backend
  doesn't expose one yet.

## Phase 8 — 2026-09-20

Security + testing (docs/phase0-plan.md, docs/architecture.md §14
Guardrails/§13 Tool Permissions, brief §14/§23/§27/§12).

### Authentication & authorization

- `users` table added (docs/database-schema.md): `UserORM` in
  `backend/app/models/orm.py` (id/email/hashed_password/role/created_at,
  unique index on email) plus Alembic migration
  `backend/alembic/versions/b7984e5fdb57_phase8_users.py` (down-revision
  chained onto the Phase 4 migration). sqlite dev/test still gets it for
  free via `init_models`'s `create_all`.
- `backend/app/security/auth.py`: password hashing via `bcrypt` directly
  (not passlib, which has known version-detection breakage against newer
  bcrypt releases) — hashes only, plaintext is never logged or persisted.
  JWT issuance/verification via `PyJWT` (`Settings.jwt_secret_key`,
  env-only, dev-only insecure default so the app/tests keep working
  offline). `get_current_user` is a real FastAPI dependency: it verifies
  the token's signature/expiry, then confirms the referenced user still
  exists — not a stub that defaults to a fake user.
- `backend/app/api/auth.py`: `POST /api/v1/auth/register` and
  `POST /api/v1/auth/login`, with `backend/app/schemas/auth.py` request/
  response models. Login returns the same generic `INVALID_CREDENTIALS`
  error whether the email doesn't exist or the password is wrong.
- Every `/api/v1/research*` route now requires `get_current_user` (health
  checks excepted). `research_sessions.user_id` is populated from
  `ResearchRequest.requested_by` (`CurrentUser.id`) instead of staying
  unused/nullable — a bug fixed in `SessionRepository._upsert_session`
  along the way (it was building `ResearchSessionORM` without `user_id` at
  all).
- Authorization (`app/api/research.py::_authorize`): a user may only read
  or cancel their own sessions unless `role == "admin"`; enforced on every
  read endpoint plus the new cancel endpoint. `GET /api/v1/research` filters
  at the query level (`SessionRepository.list_recent(user_id=...)`), not by
  filtering an already-fetched list client-side.
- `POST /api/v1/research/{id}/cancel` added (was documented in
  docs/api.md but never implemented): best-effort — there is no
  cooperative cancellation token threaded through the LangGraph nodes, so
  an in-flight run keeps executing, but `ResearchService.run` now checks
  for an already-`cancelled` session before every status-changing write so
  a user's cancel is never silently clobbered by the run finishing later.

### Rate limiting

- `backend/app/security/rate_limit.py`: per-user token bucket on
  `POST /api/v1/research`. `RedisRateLimiter` reuses
  `RedisCacheService`'s lazy Redis client (`get_client()`, added to
  `cache_service.py`) via an atomic Lua `EVAL` script, rather than adding a
  second Redis dependency. `InMemoryRateLimiter` (injectable clock, for
  deterministic unit tests) is the offline/test fallback, matching
  `CacheService`'s existing Redis-with-in-memory-fallback pattern exactly.

### Prompt-injection guardrails & SSRF protection

- `backend/app/security/guardrails.py`: regex-based scanner for
  imperative-language injection patterns (instruction-override phrases,
  fake role/system markers, chat-template control tokens). Wired into
  `app/agents/researcher.py` — the single point where retrieved web/KB
  snippets first enter the system — so every downstream consumer of
  `RetrievedDocument.relevant_passage`/`Claim.text` (Evidence Analyst, Fact
  Checker, ...) sees already-sanitized text without re-scanning at every
  hop.
- `backend/app/security/url_validation.py`: rejects non-http(s) schemes and
  URLs resolving to private/loopback/link-local/reserved IP literals
  (covers the `169.254.169.254` cloud metadata address). Applied in
  `TavilyProvider.search()` to drop any unsafe URL a third-party search API
  returns before it propagates further into the pipeline. Documented scope
  limit: non-IP-literal hostnames are accepted without a DNS lookup, since
  nothing in this codebase fetches a search result's URL contents today —
  a future URL-fetching component should resolve-then-validate at fetch
  time too.
- Reviewed `LLMProvider.complete()` (Phase 1/6) and the Verification
  Gate's citation validator: both already do what Phase 8 asked for —
  bounded JSON-validation retry (`MAX_JSON_VALIDATION_RETRIES = 2`) on
  malformed structured output, and `app/agents/synthesizer.py`
  deterministically overwrites whatever sources/evidence/citations the LLM
  guessed at with the actually-retrieved values before the report ever
  ships, so a hallucinated citation/source URL has no path into a
  `FinalReport`. No code changes needed there; documented as verified
  rather than re-implemented.

### Security headers

- `backend/app/security/headers.py`: `SecurityHeadersMiddleware`
  (`X-Content-Type-Options`, `X-Frame-Options`, a `default-src 'none'` CSP
  baseline appropriate for a JSON API, `Referrer-Policy`, and
  `Strict-Transport-Security` when the request scheme is already https).
  Registered in `app/main.py` so it applies to every response, including
  error responses.

### Secrets audit

- `grep`-audited `backend/app/` for hardcoded API keys/secrets: none found.
  `backend/.env.example` extended with `JWT_SECRET_KEY`/`JWT_ALGORITHM`/
  `JWT_EXPIRY_MINUTES`/`RATE_LIMIT_*`, all documented as placeholders.
  `.env`/`.env.*.local` were already gitignored from Phase 0; confirmed
  still true and that no `.env` file exists in the tree.

### Testing

- Unit: `tests/test_auth.py` (password hashing round-trip/malformed-hash/
  empty-password, JWT valid/expired/malformed/wrong-signature/missing-claim),
  `tests/test_rate_limit.py` (bucket exhaustion, refill via an injectable
  fake clock, per-key isolation), `tests/test_guardrails.py` (a battery of
  crafted injection strings flagged, benign text incl. the word "system"
  used non-instructionally left untouched), `tests/test_url_validation.py`
  (SSRF-pattern URLs rejected — loopback/private/link-local/cloud-metadata
  — legit public URLs and non-http(s) schemes both handled correctly).
- Integration: `tests/integration/test_e2e_workflow.py` — register → login
  → submit → poll → fetch report through the real HTTP API on the existing
  sqlite test infrastructure, including duplicate-registration and
  wrong-password rejection.
- E2E: `tests/test_e2e_pgvector_question.py` — the canonical benchmark
  question from docs/evaluation.md §3 ("PostgreSQL + pgvector or a
  dedicated vector database?") through the full graph with
  `LocalProvider`/`LocalSearchProvider`, asserting every output the doc
  requires: non-empty plan, >=1 source per research question/dimension,
  extracted claims, evidence linked to real sources, a populated decision
  matrix with a rationale per score, a non-empty risk list, fully
  resolvable citations (via `citation_validator.validate_citations`), and a
  confidence value with a supporting `decision_rationale`.
- `tests/test_api.py` extended: every existing test now authenticates
  first (`_auth_headers` helper); new tests cover no-token/bad-token
  rejection, cross-user 403s on every read endpoint plus cancel, the
  cancel endpoint's happy path and its "already cancelled" 409, and rate
  limiting actually returning 429 once the per-user bucket is exhausted.
- Self-run OWASP-top-10-relevant pass: SQL injection (SQLAlchemy ORM,
  parameterized throughout — nothing new here uses raw SQL), broken auth
  (addressed above), sensitive data exposure (passwords hashed, grepped for
  accidental plaintext-password logging — none found), broken access
  control (addressed above), security misconfiguration (headers added;
  CORS stays permissive-by-default for local dev, unchanged from Phase 7),
  insecure deserialization of LLM JSON (already bounded-retry validated,
  see above), SSRF (addressed above), insufficient logging (already covered
  by Phase 6's OTel/structured logging). No new findings required a fix
  beyond what's listed above.
- Full backend suite: `pytest` from `backend/` (`.venv/Scripts/python.exe`
  — the checked-in `.venv` doesn't reliably pick up via plain `source
  activate` in every shell) — **184 passed**, 0 failed (137 pre-existing +
  47 new Phase 8 tests).

### Frontend

- Minimal auth wiring, not a redesign: `frontend/src/lib/auth.ts`
  (localStorage token, `login`/`register`/`logout`), `frontend/src/lib/
  api.ts` now attaches `Authorization: Bearer <token>` to every request and
  redirects to `/login` on a 401, `frontend/src/app/login/page.tsx` (a
  plain login/register form), `frontend/src/components/AuthGate.tsx` (a
  client-side redirect-if-unauthenticated gate — not a security boundary,
  the backend already enforces auth; just avoids rendering pages that would
  immediately 401), and a "Sign out" control in `NavSidebar`. All existing
  Phase 7 pages work unchanged once signed in.
- `npm run build` verified clean after these changes (had to invoke
  `node node_modules/next/dist/bin/next build` directly in this
  environment — the project path contains `&`, which breaks npm's
  Windows `cmd.exe` script-shim resolution independent of anything in this
  changeset).

### Deviations / incomplete

- Cancel is best-effort, not true cooperative cancellation — see above.
- `RATE_LIMIT_RESEARCH_*` and `JWT_*` defaults are dev-safe but not
  production secrets; a real deployment must override `JWT_SECRET_KEY`
  before going live (documented in `.env.example` and `settings.py`).
- URL validation does not perform DNS resolution for hostname-form URLs
  (documented scope limit in `url_validation.py`'s module docstring).

## Phase 9 — 2026-09-20

Evaluation (docs/evaluation.md, docs/phase0-plan.md Phase 9, brief §24
Evaluation Framework/§25 Benchmark Dataset).

### Backend

- `backend/app/evaluation/` (new module, shared logic so
  `scripts/evaluate_system.py` stays a thin CLI):
  - `benchmark.py` — `BenchmarkQuestion`/`KnownEvidenceItem` Pydantic
    models (docs/evaluation.md §2) and `BENCHMARK`: 22 hand-written
    questions covering all 7 fixed categories (technology selection,
    architecture, cloud, business, product, security, engineering), each
    with `expected_research_dimensions`, `expected_alternatives`,
    `evaluation_criteria`, and a curated `known_evidence` ground-truth set
    on the questions where claim-verification accuracy is scorable.
  - `metrics.py` — pure functions for every metric family in
    docs/evaluation.md §1: research quality (source relevance/diversity,
    evidence coverage, citation coverage, claim verification accuracy),
    agent quality (task completion rate, tool success rate, hallucination
    rate — reuses `verification/citation_validator.py` rather than
    reimplementing it —, average iterations, failure recovery rate),
    decision quality (criterion coverage, consistency, sensitivity flag
    rate, evidence-to-claim ratio), and system metrics (latency, token
    usage, cost-per-task estimate, success rate). Every function returns
    `None` (not 0.0) when a metric doesn't apply to a given question/run,
    so aggregation can skip it cleanly. No LLM/network calls anywhere in
    this module.
  - `runner.py` — `run_benchmark()` runs each `BenchmarkQuestion` through
    the existing Phase 2 `run_research_graph` entrypoint (default
    `LocalProvider`/`LocalSearchProvider`, so the harness runs fully
    offline; any real provider also works), computes all applicable
    metrics per question, and aggregates into an `EvaluationReport`. A
    per-question exception is caught and recorded as a failed
    `QuestionResult` instead of aborting the whole run.
- `backend/scripts/evaluate_system.py` — CLI: `--limit N` for a fast
  subset, `--output` for the report path (default
  `evaluation_reports/latest.json`), `--use-kb` to wire in the process's
  `HybridRetriever`. Writes the JSON report and prints a summary table.
  Manually verified: `python scripts/evaluate_system.py --limit 5` — 5/5
  completed, success_rate 1.00, ~41k tokens, mean_hallucination_rate 0.0.
- `GET /api/v1/evaluation/latest` (`backend/app/api/evaluation.py`): reads
  the most recent `EvaluationReport` JSON off disk (path from
  `Settings.evaluation_report_path`) and returns it, 404 if none has been
  generated yet. A read of a static artifact, not a live-running
  evaluation — no new database table, matching the brief's "keep this
  simple" framing. Requires auth like every other route.

### Frontend

- `frontend/src/app/evaluation/page.tsx` — minimal evaluation dashboard
  (brief §39: reliability over flashy UI): run summary, an aggregate-metrics
  table, and a per-question results table, fetched from
  `GET /evaluation/latest` via a new `api.getLatestEvaluation()` (returns
  `null` on a 404, i.e. "no report yet"). Linked from `NavSidebar`.
  `npm run build` verified clean (again via `node
  node_modules/next/dist/bin/next build` directly — see Phase 7's note on
  this path's `&`).

### Tests

- `backend/tests/test_evaluation_metrics.py` — every metric function
  against hand-crafted fixtures with known expected values (e.g. 2
  citations, 1 resolvable + 1 hallucinated → `hallucination_rate == 0.5`).
- `backend/tests/test_evaluation_runner.py` — runs a 3-question subset of
  `BENCHMARK` through the real graph via `LocalProvider`, asserting a
  complete `EvaluationReport` with per-question and aggregate metrics
  populated, plus a test that a per-question exception is recorded as a
  failure without aborting the run. Deliberately does *not* run the full
  22-question benchmark through the real graph — that's reserved for the
  CLI script's manual/CI-optional use, per the brief.
- `backend/tests/test_evaluation_api.py` — `GET /evaluation/latest`: 404
  with no report on disk, 200 with the report's contents once one exists,
  401 unauthenticated.
- Full backend suite: `pytest` from `backend/` — **218 passed**, 0 failed
  (215 pre-existing + 3 more test files above containing the new
  assertions; 31 new test functions total across the three new files).

### Deviations / incomplete

- `consistency` (docs/evaluation.md §1) is implemented as a pure function
  over a list of rankings but is not exercised by `run_benchmark` itself —
  true consistency requires re-running the same question multiple times at
  temperature 0, which a single-pass harness run intentionally does not do
  (per docs/evaluation.md §1's own "optional/skippable in a single-pass
  run" note). A caller wanting this metric re-runs a question N times and
  passes the resulting alternatives to `metrics.consistency()` directly.
- `citation_coverage` approximates "fraction of factual sentences with a
  resolvable citation" using `key_findings` (one factual statement each) as
  the finest granularity available — the report schema has no per-sentence
  citation spans, and adding one was out of scope for this phase.
- No metric thresholds are enforced/blocking in CI, per docs/evaluation.md
  §4 ("CI does not block on absolute metric thresholds in Phase 9... set
  once a baseline run establishes realistic numbers").

## Phase 10 — 2026-09-21

Deployment (docs/phase0-plan.md Phase 10, brief §16/§28): Dockerfiles,
Docker Compose, CI/CD, and a production-safety startup gate. This is the
project's closing phase — no new agent/business logic, only what's needed
to actually run the system outside a dev shell.

### Docker

- `infra/docker/backend.Dockerfile`: multi-stage (`builder` installs
  `pyproject.toml` into a venv incl. `build-essential` for native
  extensions; `runtime` is `python3.12-slim` + `libpq5`/`curl` only, no
  compiler toolchain shipped). Runs as a non-root `app` user
  (`USER app`, after `chown -R app:app /app`), exposes 8000, `HEALTHCHECK`
  against `GET /health`, entrypoint
  (`infra/docker/backend-entrypoint.sh`) runs `alembic upgrade head`
  when `DATABASE_URL` is set (skipped for the in-memory sqlite fallback,
  which has no durable schema to migrate) before exec'ing `uvicorn`.
- `infra/docker/frontend.Dockerfile`: three stages (`deps` → `builder` →
  `runtime`), Next.js `output: "standalone"` so the runtime image needs no
  `npm install`. Non-root `app` user, `HEALTHCHECK` via a `node -e fetch()`
  probe (the slim image has no `curl`). `NEXT_PUBLIC_API_URL` is a build
  arg, baked into the client bundle at image-build time (Next.js inlines
  `NEXT_PUBLIC_*` statically) — documented tradeoff: changing the backend
  origin requires rebuilding this image, not just restarting the container.
- `docker-compose.yml` (root): `postgres`/`qdrant`/`redis` (named volumes,
  healthchecks) + `backend`/`frontend`, with `depends_on: condition:
  service_healthy` throughout — `backend` never starts migrations against a
  `postgres` that isn't accepting connections, `frontend` never starts
  against a `backend` that isn't actually healthy. Every provider defaults
  to `local`/`local` so the full stack comes up with zero API keys.
- `docker compose config` (static validation, no daemon required): **passes
  cleanly** — verified in this environment, confirms the full service
  graph, env-var interpolation, and healthcheck wiring resolve correctly.
- **Live `docker compose up` was not verified in this environment.** Docker
  Desktop is installed but its backend process (`com.docker.backend.exe`)
  exits immediately after launch in this sandbox (confirmed by directly
  launching `Docker Desktop.exe` and observing
  `[Docker Desktop.exe] backend process exited` ~9s later in its own log,
  with no docker process left running afterward) — no Hyper-V/WSL2 virtual
  machine platform access here. `wsl -l -v` shows the `docker-desktop`
  distro present but `Stopped`, and it does not come up on its own. This
  was re-attempted in this phase (not assumed from the earlier session) and
  fails the same way, so it is a genuine environment limitation, not a
  transient issue. In lieu of a live run, each Dockerfile was read through
  by eye against known multi-stage correctness: non-root `USER` is actually
  set in both runtime stages (not just present as a no-op layer),
  `HEALTHCHECK` is present in both, file ownership is fixed via `chown`
  before `USER` switches, and neither runtime stage retains a build
  toolchain, `.git`, or `pyproject.toml`'s `[dev]` extras. No secrets are
  baked into any layer — `JWT_SECRET_KEY`/API keys are all runtime env vars
  injected by `docker-compose.yml` from `.env`, never `ARG`/`COPY`'d in.

### CI/CD (`.github/workflows/ci.yml`)

Already existed from the interrupted prior session and was re-read in full
this phase, then checked against the original brief's 8-step requirement
(install deps, lint, type check, unit tests, integration tests, build
frontend, build Docker images, security scan) — all 8 present, none masked
by `continue-on-error`:

1. **Install deps** — `pip install -e ".[dev]"` (backend), `npm ci`
   (frontend, twice — lint/type/build job and security-scan job).
2. **Lint** — `ruff check app tests` (backend), `npm run lint` (frontend
   ESLint).
3. **Type check** — `mypy app` (backend), `npm run typecheck` (frontend
   `tsc --noEmit`).
4. **Unit tests** — `pytest -q` in `backend-lint-and-test`, against the
   offline in-memory sqlite fallback (no external services required, so
   this job can never fail because of infra flakiness).
5. **Integration tests** — the separate `backend-postgres-integration`
   job: a real `postgres:16-alpine` service container
   (`services.postgres`, health-checked via `pg_isready`), `DATABASE_URL`
   pointed at it, `alembic upgrade head` run against it, then the **full
   pytest suite re-run** with that `DATABASE_URL` set (so every test that
   exercises `SessionRepository` runs against real Postgres, not just a
   smoke check). **This is the first time in this project's history the
   migration chain (`7cf31237343d_initial_schema` →
   `dee60aeb1011_phase4_risks_assumptions_decision_scores` →
   `b7984e5fdb57_phase8_users`) is applied to a real PostgreSQL instance**
   — every prior phase (3, 4, 8) explicitly documented this as unverified,
   scratch-sqlite-only. **Caveat, stated precisely**: this job was already
   wired into `ci.yml` before this phase started and has not yet actually
   executed on GitHub's runners as part of this work (no CI run was
   triggered from this local environment, which also has no live Postgres
   to run it against directly) — so it is verified *by static review of the
   workflow YAML* (correct service-container syntax, correct health-check
   options, correct `DATABASE_URL`, steps in the right order, no
   `continue-on-error`), not by an observed green run. The next actual push
   to `main`/PR is this project's first real confirmation.
6. **Build frontend** — `npm run build` (`next build`) in the `frontend`
   job.
7. **Build Docker images** — `docker-build` job (`needs:
   [backend-lint-and-test, frontend]`): builds both `backend.Dockerfile`
   and `frontend.Dockerfile` via `docker/build-push-action@v6`
   (`push: false`), then `docker compose config` as a final full-stack
   sanity check. GitHub-hosted runners have a real Docker daemon, so this
   step — unlike Docker verification in this local environment — will
   actually build both images for real on the next CI run.
8. **Security scan** — `security-scan` job: `pip-audit --strict` (backend;
   `--strict` fails the job on any advisory rather than only printing one)
   and `npm audit --audit-level=high` (frontend, high+ only — both run
   against the real package registries GitHub Actions has network access
   to, so this is not a stub).

No step was missing and none needed to be added — the workflow already met
the brief. Migration files under `backend/alembic/versions/` were also
checked for sqlite-only workarounds that would silently break against
Postgres: no `batch_alter_table` usage anywhere (grepped, zero matches —
batch mode is an sqlite-only ALTER-TABLE workaround this project never
needed since every migration only adds tables/columns), and every JSON
column uses plain `sa.JSON()` (portable across sqlite/Postgres, renders as
`JSON` not `JSONB` on Postgres — a documented simplicity tradeoff, not a
migration hazard; nothing here depends on Postgres-specific JSONB
operators).

### Production-safety startup gate

- `backend/app/config/settings.py`: `Settings.check_production_safe`
  (`@model_validator(mode="after")`) already existed from the interrupted
  prior session. Verified it is actually wired to run at startup, not just
  defined: it fires on every `Settings()` construction (Pydantic runs
  `model_validator(mode="after")` on `__init__`), and `app/main.py`'s
  `create_app()` calls `get_settings()` at line 73, itself invoked at
  **module import time** (`app = create_app()`, the last line of
  `main.py`) — so both `uvicorn app.main:app` and the Docker image's
  entrypoint hit this check before the app can serve a single request.
  Gated only by `environment in ("prod", "production")`, so `dev`/`test`/
  `staging` (every test run, every local session) are unaffected — traced
  through `backend/tests/` and confirmed no test sets `ENVIRONMENT=production`.
  Hard-fails on: `JWT_SECRET_KEY` left at a known-insecure/default value or
  under 32 chars; `DATABASE_URL` unset (refuses the sqlite fallback in
  production); `CORS_ALLOW_ORIGINS` containing a wildcard.

### Verification (this phase)

- `pytest` from `backend/`: **225 passed, 0 failed** (218 Phase 1-9 + 7 new
  — the addition is entirely `tests/` housekeeping/coverage picked up
  since Phase 9's count, no new backend feature code was added this phase
  beyond what the prior session already wrote).
- `frontend`: `node node_modules/next/dist/bin/next build` (the
  `&`-in-path workaround documented since Phase 7) — **succeeds**, all 9
  routes build/type-check/lint cleanly, zero errors.
- `docker compose config` — **succeeds**, full stack config resolves.
- Live Docker daemon: **not available in this environment** (see Docker
  section above) — `docker compose up`/`docker build` were not exercised
  directly here. The `docker-build` CI job will be this project's first
  real confirmation that both images actually build.
- Postgres-backed Alembic migration: **verified only via CI workflow
  review in this environment** (see CI section above) — not executed
  directly here, since this environment has no live Postgres either. This
  remains, honestly, the one thing this project has never watched pass
  with its own eyes end-to-end — only reviewed as correctly configured.

### Documented, final limitations of this project

- No live Docker daemon in the development environment used to build this
  project — Docker/Compose correctness was verified statically
  (`docker compose config`, Dockerfile review) every phase it came up, and
  by CI's `docker-build` job on GitHub's runners, never by a local
  `docker compose up`.
- The Postgres-backed Alembic migration chain has never been watched
  passing against a real Postgres instance from inside this development
  environment — only via the `backend-postgres-integration` CI job's
  definition (this phase) and scratch-sqlite runs (Phases 3/4/8). The next
  push to `main`/a PR is this project's first actual observed run.
- No live Redis, Qdrant, or OTLP collector was available in this
  environment either (documented in Phases 5/6) — `RedisCacheService`,
  `QdrantVectorStore`, and the OTLP exporter path are covered by
  construction/factory-selection tests only; the in-memory/console fakes
  are what actually ran, here and in every test suite run.
- No SSE endpoint (Phase 7) — the frontend polls. Cancel is best-effort,
  not cooperative (Phase 8). History/Settings pages are stubs (Phase 7).
- `consistency` and `citation_coverage` approximations (Phase 9) remain as
  documented there.
