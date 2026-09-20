# Evaluation Strategy

Evaluation must be quantitative, not "does the final answer look plausible."
Implemented in Phase 9, defined now so later phases build toward fixed targets.

## 1. Metric families

**Research quality**
- *Source relevance*: mean `relevance_score` of retrieved documents actually
  cited in the final report.
- *Source diversity*: distinct `source_type` count and distinct publisher count
  per report; penalize single-source-type dominance.
- *Evidence coverage*: fraction of `research_questions` with ≥1 `EvidenceItem`.
- *Citation coverage*: fraction of factual sentences in the final report that
  carry a citation marker resolvable to a `Source`.
- *Claim verification accuracy*: on a labeled subset of the benchmark (claims
  with a known ground-truth status), fraction where `ClaimVerification.status`
  matches the label.

**Agent quality**
- *Task completion rate*: fraction of agent runs that return a schema-valid
  output without exhausting retries.
- *Tool success rate*: fraction of tool calls that return usable (non-error,
  non-empty) results.
- *Hallucination rate*: fraction of cited claims not traceable to any retrieved
  passage (checked by the citation validator, sampled/audited).
- *Average iterations*: mean iterations used per agent vs. its configured max
  — a value consistently near the max indicates the budget is mis-tuned.
- *Failure recovery rate*: fraction of tool/LLM failures that succeed on retry
  vs. propagate to a hard failure.

**Decision quality**
- *Criterion coverage*: fraction of planner-identified criteria that receive a
  score for every alternative (no silently-dropped criteria).
- *Consistency*: re-running the same question at temperature 0 for the Decision
  Analyst produces the same ranking (allows evidence-driven variance only).
- *Sensitivity*: at least one sensitivity check run per report; flag rate at
  which the recommendation is sensitive to plausible weight changes.
- *Evidence-to-claim ratio*: mean `EvidenceItem` count per `Claim`, a proxy for
  how well-substantiated the report's claims are.

**System**
- *Latency*: end-to-end wall clock per research run, and per-stage breakdown
  (from `AgentRunMeta`).
- *Cost per research task*: summed token cost across all agent runs.
- *Token usage*: total and per-agent-tier (small/mid/strong) breakdown.
- *Success rate*: fraction of research runs reaching `completed` without
  hitting the verification-cycle ceiling or a hard failure.

## 2. Benchmark dataset (authored in full at Phase 9; categories fixed now)

20+ questions across:
- Technology selection (e.g. "Postgres+pgvector vs. dedicated vector DB")
- Architecture decisions (e.g. "monolith vs. microservices for a 5-person team")
- Cloud decisions (e.g. "AWS vs. GCP vs. self-hosted for a data-heavy workload")
- Business decisions (e.g. "freemium vs. paid-only launch strategy")
- Product decisions (e.g. "mobile-first vs. web-first MVP")
- Security decisions (e.g. "build vs. buy for SSO/identity")
- Engineering decisions (e.g. "REST vs. GraphQL for a public API")

Each benchmark entry records: `question`, `expected_research_dimensions[]`,
`known_evidence[]` (a small curated ground-truth set used for claim-verification
accuracy scoring), `expected_alternatives[]`, `evaluation_criteria[]`.

## 3. Canonical E2E test

"Should a startup use PostgreSQL + pgvector or a dedicated vector database?"
Asserted outputs: a non-empty research plan, ≥1 source per research dimension,
extracted claims, evidence items linked to sources, a populated decision matrix
with rationale per score, a non-empty risk list, resolvable citations throughout,
and a `confidence` value with a supporting explanation. This is the fixture used
in `backend/tests/integration/test_e2e_workflow.py` (Phase 8).

## 3a. Implementation status (Phase 9)

The benchmark dataset and harness described above are implemented:
`backend/app/evaluation/benchmark.py` (22 questions across all 7
categories), `backend/app/evaluation/metrics.py` (every metric family in
§1 as pure functions), `backend/app/evaluation/runner.py`
(`run_benchmark()`), `backend/scripts/evaluate_system.py` (CLI), and
`GET /api/v1/evaluation/latest` (`backend/app/api/evaluation.py`) plus
`frontend/src/app/evaluation/page.tsx` for the dashboard mentioned in §4.
See `CHANGELOG.md`'s Phase 9 entry for details and known scope limits
(e.g. `consistency` is a pure function callers invoke across their own
re-runs — the harness itself stays single-pass).

## 4. Evaluation harness

`scripts/evaluate_system.py` (Phase 9) runs the full benchmark set against the
live system, computes the metrics above, and writes a report consumed by an
evaluation dashboard page in the frontend (§19 page 10 / system settings area
extension). CI does not block on absolute metric thresholds in Phase 9 (no
tuned baseline exists yet); it blocks on the harness executing successfully and
metrics being computed for every benchmark question — thresholds are set once a
baseline run establishes realistic numbers.
