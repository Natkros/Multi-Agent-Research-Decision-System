# Shared State Schema

All inter-agent communication flows through one typed `ResearchState` object.
No agent receives or returns a bare `dict`. LangGraph nodes take `ResearchState`
in, return a partial `ResearchState` update (merged by the graph runtime).

These are the Phase 0 schema *contracts*; concrete Pydantic classes are
implemented in `backend/app/models/state.py` in Phase 1-4 as each section
becomes relevant, but the shapes below are fixed now so every later phase
builds against a stable contract.

```python
class ResearchRequest(BaseModel):
    id: UUID
    question: str
    constraints: list[str] = []
    alternatives_hint: list[str] = []       # user-supplied, planner may extend
    criteria_hint: list[str] = []           # user-supplied, planner may extend
    mode: Literal["auto", "assisted", "manual"] = "auto"
    requested_by: str
    created_at: datetime


class ResearchPlan(BaseModel):
    objective: str
    decision_type: Literal["technology_selection", "architecture", "vendor",
                            "build_vs_buy", "strategic", "other"]
    alternatives: list[str]
    criteria: list["DecisionCriteria"]
    research_questions: list["ResearchQuestion"]
    required_evidence: list[str]
    constraints: list[str]
    assumptions: list[str]                  # planner-stated, not evidence-backed


class ResearchQuestion(BaseModel):
    id: str
    text: str
    dimension: str                          # e.g. "cost", "security"
    priority: Literal["high", "medium", "low"]


class RetrievedDocument(BaseModel):
    source_id: str
    title: str
    url: str | None
    source_type: Literal["official_docs", "paper", "government", "standard",
                          "vendor_docs", "blog", "forum", "news", "internal_kb"]
    retrieved_at: datetime
    relevant_passage: str
    claims: list[str]                       # extracted claim strings
    relevance_score: float                  # 0-1


class Source(BaseModel):
    id: str
    title: str
    url: str | None
    publisher: str | None
    author: str | None
    published_at: datetime | None
    retrieved_at: datetime
    source_type: str
    credibility_score: float                # from Source Evaluator
    content_hash: str                       # dedup key


class Claim(BaseModel):
    id: str
    text: str
    source_id: str
    research_question_id: str


class ClaimVerification(BaseModel):
    claim_id: str
    status: Literal["VERIFIED", "PARTIALLY_VERIFIED", "CONTRADICTED",
                     "UNSUPPORTED", "OUTDATED"]
    supporting_sources: list[str]
    contradicting_sources: list[str]
    confidence: float
    explanation: str


class EvidenceItem(BaseModel):
    id: str
    claim_id: str
    evidence_text: str
    source_id: str
    evidence_type: Literal["quantitative", "qualitative", "benchmark",
                            "documentation", "expert_analysis",
                            "empirical_observation", "policy_regulatory",
                            "user_provided"]
    strength: Literal["strong", "moderate", "weak"]
    confidence: float
    limitations: str | None


class Conflict(BaseModel):
    id: str
    claim_a_id: str
    claim_b_id: str
    conflict_type: Literal["genuine", "context_mismatch", "version_mismatch",
                            "temporal", "workload_mismatch", "environment_mismatch"]
    explanation: str
    resolution_status: Literal["unresolved", "resolved_context",
                                "resolved_favor_a", "resolved_favor_b", "irreconcilable"]


class Assumption(BaseModel):
    id: str
    text: str
    origin: Literal["user_provided", "evidence_backed", "inferred", "hypothetical"]
    affects: list[str]                      # criteria/alternatives it influences


class Risk(BaseModel):
    id: str
    category: Literal["technical", "financial", "security", "operational",
                       "regulatory", "vendor", "scalability", "execution", "unknown"]
    description: str
    probability: Literal["low", "medium", "high"]
    impact: Literal["low", "medium", "high"]
    severity: float                         # derived probability x impact
    mitigation: str
    evidence_ids: list[str]


class DecisionCriteria(BaseModel):
    name: str
    description: str
    weight: float                           # normalized 0-1, sums to 1 across set
    direction: Literal["maximize", "minimize"]
    scoring_method: Literal["weighted_score", "threshold", "cost_benefit"]


class AlternativeScore(BaseModel):
    alternative: str
    criterion: str
    score: float                            # 0-10
    rationale: str
    evidence_ids: list[str]


class DecisionMatrix(BaseModel):
    criteria: list[DecisionCriteria]
    scores: list[AlternativeScore]
    weighted_totals: dict[str, float]        # alternative -> total
    recommended: str
    sensitivity: list["SensitivityResult"]


class SensitivityResult(BaseModel):
    criterion: str
    weight_delta: float                      # e.g. +0.20
    recommendation_changed: bool
    new_recommended: str | None


class VerificationResult(BaseModel):
    cycle: int
    passed: bool
    failed_checks: list[str]
    routed_to: str | None                    # which agent the retry targets


class ExecutionMetadata(BaseModel):
    trace_id: str
    session_id: UUID
    started_at: datetime
    completed_at: datetime | None
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    agent_runs: list["AgentRunMeta"]
    total_tokens: int
    total_cost_usd: float
    verification_cycles_used: int


class AgentRunMeta(BaseModel):
    agent_name: str
    trace_id: str
    start_time: datetime
    end_time: datetime
    latency_ms: int
    tokens: int
    model: str
    tool_calls: list[str]
    errors: list[str]
    confidence: float | None


class FinalReport(BaseModel):
    executive_summary: str
    research_question: str
    decision_context: str
    alternatives: list[str]
    criteria: list[DecisionCriteria]
    key_findings: list[str]
    evidence: list[EvidenceItem]
    contradictions: list[Conflict]
    comparative_analysis: DecisionMatrix
    risk_analysis: list[Risk]
    assumptions: list[Assumption]
    decision_rationale: str
    confidence: float
    limitations: list[str]
    sources: list[Source]
    citations: dict[str, str]               # "[S3]" -> source_id


class ResearchState(BaseModel):
    request: ResearchRequest
    plan: ResearchPlan | None = None
    retrieved_documents: list[RetrievedDocument] = []
    sources: list[Source] = []
    claims: list[Claim] = []
    evidence: list[EvidenceItem] = []
    verified_claims: list[ClaimVerification] = []
    contradictions: list[Conflict] = []
    assumptions: list[Assumption] = []
    risks: list[Risk] = []
    decision_matrix: DecisionMatrix | None = None
    draft_report: FinalReport | None = None
    verification_results: list[VerificationResult] = []
    final_report: FinalReport | None = None
    execution_metadata: ExecutionMetadata
```

## Invariants

- Every `EvidenceItem`, `Claim`, `Risk`, and `AlternativeScore` carries an id that
  traces back to a `Source`. The Verification Gate rejects a `draft_report` that
  cites a source id absent from `state.sources`.
- `ResearchState` is append-only within a run except for `verification_results`
  and `final_report`, which are the only fields a retry cycle may overwrite.
- Agents never receive the full `ResearchState`; each node's input is a narrowed
  view (see the "Reads" column in the responsibility matrix) constructed by the
  orchestration layer, so an agent cannot accidentally depend on — or leak —
  fields outside its contract.
