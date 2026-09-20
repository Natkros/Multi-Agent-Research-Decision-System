# API Specification (Phase 0 draft)

Base path: `/api/v1`. All endpoints require an `Authorization: Bearer <token>`
header except health checks. Responses are JSON; streaming endpoints use SSE
(`text/event-stream`).

## POST /api/v1/research

Start a research run.

Request:
```json
{
  "question": "Should a startup build its own vector database or use a managed service?",
  "constraints": ["budget < $5k/mo", "team of 3 engineers"],
  "alternatives": [],
  "criteria": [],
  "mode": "auto"
}
```
`alternatives`/`criteria` are hints; the Research Planner may extend them.
`mode` is one of `auto | assisted | manual` (§37).

Response `202 Accepted`:
```json
{ "research_id": "b3f1...", "status": "pending" }
```

## GET /api/v1/research/{id}

Returns current `ResearchState` summary + status.
```json
{
  "research_id": "...",
  "status": "running",
  "stage": "verifying",
  "progress": { "completed_stages": 4, "total_stages": 9 },
  "confidence": null
}
```

## GET /api/v1/research/{id}/stream (SSE)

Emits one event per stage transition and per agent completion:
```
event: stage
data: {"stage": "researching", "agent": "researcher", "index": 2, "of": 4}

event: agent_complete
data: {"agent": "fact_checker", "latency_ms": 1820, "confidence": 0.81}

event: complete
data: {"research_id": "...", "status": "completed"}
```

## GET /api/v1/research/{id}/sources
List of `Source` objects used in the run, each with `credibility_score`.

## GET /api/v1/research/{id}/claims
List of `Claim` + their `ClaimVerification` status.

## GET /api/v1/research/{id}/evidence
List of `EvidenceItem`, filterable via `?evidence_type=` and `?min_confidence=`.

## GET /api/v1/research/{id}/decision
Returns the `DecisionMatrix` including per-criterion scores, weighted totals,
recommendation, and sensitivity analysis results.

## GET /api/v1/research/{id}/trace
Returns `ExecutionMetadata` — ordered `AgentRunMeta[]` with latency/tokens/tool
calls/errors per agent, suitable for the Agent Trace UI.

## GET /api/v1/research/{id}/report
Returns the `FinalReport` (only once `status == completed`).

## POST /api/v1/research/{id}/cancel
Cancels a running research session; in-flight agent calls are allowed to finish
their current step, then the graph halts and status becomes `cancelled`.

## POST /api/v1/research/{id}/approve  (assisted/manual modes only)
Body: `{"stage": "plan" | "evidence" | "criteria" | "weights" | "report", "decision": "approve" | "revise", "notes": "..."}`
Used by human-in-the-loop mode (§37) to unblock a paused graph node.

## GET /api/v1/research/{id}/replay
Returns the full reproducibility bundle (§38): prompts, model/version/temperature,
tool calls, retrieved sources, per-agent outputs, timestamps — enough to
re-render the original execution in the UI without re-running the LLMs.

## Error model

All errors follow:
```json
{ "error": { "code": "RESEARCH_NOT_FOUND", "message": "...", "trace_id": "..." } }
```
Standard codes: `VALIDATION_ERROR`, `RESEARCH_NOT_FOUND`, `RATE_LIMITED`,
`PROVIDER_UNAVAILABLE`, `VERIFICATION_FAILED_MAX_CYCLES`, `INTERNAL_ERROR`.

## Auth & rate limiting

- Bearer JWT, validated per request; user id attached to `research_sessions.user_id`.
- Rate limits enforced per user at the API layer (Redis token bucket): research
  creation is the expensive endpoint and gets the tightest limit.
