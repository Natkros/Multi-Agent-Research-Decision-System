# Database Schema (PostgreSQL)

## ER Diagram

```
users
  id (PK, uuid)
  email
  role
  created_at

research_sessions
  id (PK, uuid)
  user_id (FK -> users.id)
  question
  mode                 -- auto | assisted | manual
  status                -- pending|running|completed|failed|cancelled
  created_at
  completed_at
  trace_id

research_plans
  id (PK, uuid)
  session_id (FK -> research_sessions.id, unique)
  objective
  decision_type
  constraints (jsonb)
  assumptions (jsonb)
  created_at

alternatives
  id (PK, uuid)
  plan_id (FK -> research_plans.id)
  name
  description

criteria
  id (PK, uuid)
  plan_id (FK -> research_plans.id)
  name
  description
  weight
  direction            -- maximize | minimize
  scoring_method

agents
  id (PK, uuid)
  name                  -- e.g. "research_planner", "fact_checker"
  version
  config (jsonb)         -- tool allowlist, budgets, model tier

agent_runs
  id (PK, uuid)
  session_id (FK -> research_sessions.id)
  agent_id (FK -> agents.id)
  trace_id
  parent_run_id (FK -> agent_runs.id, nullable)   -- for fan-out children
  start_time
  end_time
  latency_ms
  tokens
  model
  status                -- success | failed | timeout | retried
  input_snapshot (jsonb)
  output_snapshot (jsonb)
  error (text, nullable)
  confidence (float, nullable)

sources
  id (PK, uuid)
  title
  url
  publisher
  author
  published_at
  retrieved_at
  source_type
  credibility_score
  content_hash (unique)  -- dedup

documents
  id (PK, uuid)
  source_id (FK -> sources.id)
  session_id (FK -> research_sessions.id)
  relevant_passage (text)
  relevance_score
  research_question_id

claims
  id (PK, uuid)
  session_id (FK -> research_sessions.id)
  source_id (FK -> sources.id)
  research_question_id
  text
  status                -- VERIFIED|PARTIALLY_VERIFIED|CONTRADICTED|UNSUPPORTED|OUTDATED
  verification_confidence
  verification_explanation

evidence
  id (PK, uuid)
  claim_id (FK -> claims.id)
  source_id (FK -> sources.id)
  evidence_text
  evidence_type
  strength
  confidence
  limitations

contradictions
  id (PK, uuid)
  session_id (FK -> research_sessions.id)
  claim_a_id (FK -> claims.id)
  claim_b_id (FK -> claims.id)
  conflict_type
  explanation
  resolution_status

assumptions
  id (PK, uuid)
  session_id (FK -> research_sessions.id)
  text
  origin                -- user_provided|evidence_backed|inferred|hypothetical
  affects (jsonb)

risks
  id (PK, uuid)
  session_id (FK -> research_sessions.id)
  category
  description
  probability
  impact
  severity
  mitigation
  evidence_ids (jsonb)

decision_scores
  id (PK, uuid)
  session_id (FK -> research_sessions.id)
  alternative_id (FK -> alternatives.id)
  criterion_id (FK -> criteria.id)
  score
  rationale
  evidence_ids (jsonb)

reports
  id (PK, uuid)
  session_id (FK -> research_sessions.id, unique)
  version
  content (jsonb)         -- full FinalReport
  confidence
  created_at

citations
  id (PK, uuid)
  report_id (FK -> reports.id)
  marker                 -- "[S3]"
  source_id (FK -> sources.id)

audit_logs
  id (PK, uuid)
  session_id (FK -> research_sessions.id)
  actor                  -- agent name or user id
  action
  payload (jsonb)
  created_at
```

## Relationships

- `research_sessions 1—1 research_plans`
- `research_plans 1—N alternatives`, `1—N criteria`
- `research_sessions 1—N agent_runs`, `agent_runs` self-references via `parent_run_id`
  for fan-out (e.g. multiple Researcher runs spawned by the Planner run)
- `sources 1—N documents`, `sources 1—N claims`, `sources 1—N evidence`
- `claims 1—N evidence`, `claims N—N contradictions` (via `claim_a_id`/`claim_b_id`)
- `research_sessions 1—1 reports`, `reports 1—N citations`, `citations N—1 sources`
- `research_sessions 1—N audit_logs`

## Indexing

- `research_sessions(user_id, status)`, `research_sessions(trace_id)`
- `agent_runs(session_id, agent_id)`, `agent_runs(trace_id)`
- `sources(content_hash)` unique — dedup guard
- `claims(session_id, status)`
- `evidence(claim_id)`
- `contradictions(session_id, resolution_status)`
- `audit_logs(session_id, created_at)`

## Conventions

- All primary keys are UUIDv4.
- All tables carry `created_at`; mutable tables carry `updated_at`.
- Large free-form/structured blobs (`config`, snapshots, `content`) use `jsonb`
  so PostgreSQL can still index/query into them (e.g. GIN index on `reports.content`
  for full-text search across past reports) without a schema migration per field.
- Qdrant holds vector embeddings for document chunks only (see
  [architecture.md](architecture.md) RAG pipeline); PostgreSQL remains the single
  system of record for everything structured, so Qdrant can be rebuilt from
  PostgreSQL + the ingestion pipeline at any time.
