/**
 * TypeScript mirrors of backend/app/schemas/state.py (docs/state-schema.md).
 * Keep in sync with the Pydantic models -- this is the single source of
 * truth for shapes returned by the API; components should import from here
 * rather than redeclaring inline types.
 */

export type ResearchMode = "auto" | "assisted" | "manual";

export type DecisionType =
  | "technology_selection"
  | "architecture"
  | "vendor"
  | "build_vs_buy"
  | "strategic"
  | "other";

export type Priority = "high" | "medium" | "low";

export interface ResearchRequest {
  id: string;
  question: string;
  constraints: string[];
  alternatives_hint: string[];
  criteria_hint: string[];
  mode: ResearchMode;
  requested_by: string;
  created_at: string;
}

export type ScoringMethod = "weighted_score" | "threshold" | "cost_benefit";
export type Direction = "maximize" | "minimize";

export interface DecisionCriteria {
  name: string;
  description: string;
  weight: number;
  direction: Direction;
  scoring_method: ScoringMethod;
}

export interface ResearchQuestion {
  id: string;
  text: string;
  dimension: string;
  priority: Priority;
}

export interface ResearchPlan {
  objective: string;
  decision_type: DecisionType;
  alternatives: string[];
  criteria: DecisionCriteria[];
  research_questions: ResearchQuestion[];
  required_evidence: string[];
  constraints: string[];
  assumptions: string[];
}

export type SourceType =
  | "official_docs"
  | "paper"
  | "government"
  | "standard"
  | "vendor_docs"
  | "blog"
  | "forum"
  | "news"
  | "internal_kb"
  | string;

export interface RetrievedDocument {
  source_id: string;
  title: string;
  url: string | null;
  source_type: SourceType;
  retrieved_at: string;
  relevant_passage: string;
  claims: string[];
  relevance_score: number;
}

export interface Source {
  id: string;
  title: string;
  url: string | null;
  publisher: string | null;
  author: string | null;
  published_at: string | null;
  retrieved_at: string;
  source_type: SourceType;
  credibility_score: number;
  content_hash: string;
}

export interface Claim {
  id: string;
  text: string;
  source_id: string;
  research_question_id: string;
}

export type ClaimStatus =
  | "VERIFIED"
  | "PARTIALLY_VERIFIED"
  | "CONTRADICTED"
  | "UNSUPPORTED"
  | "OUTDATED";

export interface ClaimVerification {
  claim_id: string;
  status: ClaimStatus;
  supporting_sources: string[];
  contradicting_sources: string[];
  confidence: number;
  explanation: string;
}

export type EvidenceType =
  | "quantitative"
  | "qualitative"
  | "benchmark"
  | "documentation"
  | "expert_analysis"
  | "empirical_observation"
  | "policy_regulatory"
  | "user_provided";

export type EvidenceStrength = "strong" | "moderate" | "weak";

export interface EvidenceItem {
  id: string;
  claim_id: string;
  evidence_text: string;
  source_id: string;
  evidence_type: EvidenceType;
  strength: EvidenceStrength;
  confidence: number;
  limitations: string | null;
}

export type ConflictType =
  | "genuine"
  | "context_mismatch"
  | "version_mismatch"
  | "temporal"
  | "workload_mismatch"
  | "environment_mismatch";

export type ResolutionStatus =
  | "unresolved"
  | "resolved_context"
  | "resolved_favor_a"
  | "resolved_favor_b"
  | "irreconcilable";

export interface Conflict {
  id: string;
  claim_a_id: string;
  claim_b_id: string;
  conflict_type: ConflictType;
  explanation: string;
  resolution_status: ResolutionStatus;
}

export type AssumptionOrigin =
  | "user_provided"
  | "evidence_backed"
  | "inferred"
  | "hypothetical";

export interface Assumption {
  id: string;
  text: string;
  origin: AssumptionOrigin;
  affects: string[];
}

export type RiskCategory =
  | "technical"
  | "financial"
  | "security"
  | "operational"
  | "regulatory"
  | "vendor"
  | "scalability"
  | "execution"
  | "unknown";

export type RiskLevel = "low" | "medium" | "high";

export interface Risk {
  id: string;
  category: RiskCategory;
  description: string;
  probability: RiskLevel;
  impact: RiskLevel;
  severity: number;
  mitigation: string;
  evidence_ids: string[];
}

export interface AlternativeScore {
  alternative: string;
  criterion: string;
  score: number;
  rationale: string;
  evidence_ids: string[];
}

export interface SensitivityResult {
  criterion: string;
  weight_delta: number;
  recommendation_changed: boolean;
  new_recommended: string | null;
}

export interface DecisionMatrix {
  criteria: DecisionCriteria[];
  scores: AlternativeScore[];
  weighted_totals: Record<string, number>;
  recommended: string;
  sensitivity: SensitivityResult[];
}

export type DebateRole = "advocate" | "critic";

export interface DebateNote {
  id: string;
  role: DebateRole;
  alternative: string | null;
  claim: string;
  rationale: string;
  evidence_ids: string[];
  target_note_id: string | null;
}

export interface VerificationResult {
  cycle: number;
  passed: boolean;
  failed_checks: string[];
  routed_to: string | null;
}

export interface AgentRunMeta {
  agent_name: string;
  trace_id: string;
  start_time: string;
  end_time: string;
  latency_ms: number;
  tokens: number;
  model: string;
  tool_calls: string[];
  errors: string[];
  confidence: number | null;
}

export type SessionStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export interface ExecutionMetadata {
  trace_id: string;
  session_id: string;
  started_at: string;
  completed_at: string | null;
  status: SessionStatus;
  agent_runs: AgentRunMeta[];
  total_tokens: number;
  total_cost_usd: number;
  verification_cycles_used: number;
}

export interface FinalReport {
  executive_summary: string;
  research_question: string;
  decision_context: string;
  alternatives: string[];
  criteria: DecisionCriteria[];
  key_findings: string[];
  evidence: EvidenceItem[];
  contradictions: Conflict[];
  comparative_analysis: DecisionMatrix;
  risk_analysis: Risk[];
  assumptions: Assumption[];
  decision_rationale: string;
  confidence: number;
  limitations: string[];
  sources: Source[];
  citations: Record<string, string>;
}
