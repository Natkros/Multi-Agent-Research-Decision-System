/**
 * TypeScript mirrors of backend/app/schemas/api.py -- the actual request/
 * response envelopes exposed by the FastAPI routes in
 * backend/app/api/research.py. Kept separate from types/state.ts, which
 * mirrors the underlying ResearchState building blocks.
 */

import type {
  Claim,
  ClaimVerification,
  DecisionMatrix,
  EvidenceItem,
  ExecutionMetadata,
  FinalReport,
  ResearchMode,
  SessionStatus,
  Source,
} from "./state";

// Pipeline stages in execution order -- mirrors PIPELINE_STAGES in
// backend/app/schemas/api.py. Used to drive the stage indicator and the
// Agent Trace UI's node list without recomputing it from agent runs.
export const PIPELINE_STAGES = [
  "research_planner",
  "researcher",
  "source_evaluator",
  "evidence_analyst",
  "fact_checker",
  "contradiction_detector",
  "debate",
  "assumption_analyst",
  "decision_analyst",
  "risk_analyst",
  "final_synthesizer",
  "verification_gate",
] as const;

export type PipelineStage = (typeof PIPELINE_STAGES)[number];

export const STAGE_LABELS: Record<string, string> = {
  pending: "Pending",
  research_planner: "Planning",
  researcher: "Researching",
  source_evaluator: "Evaluating Sources",
  evidence_analyst: "Analyzing Evidence",
  fact_checker: "Fact Checking",
  contradiction_detector: "Detecting Contradictions",
  debate: "Debate (Advocate/Critic)",
  assumption_analyst: "Analyzing Assumptions",
  decision_analyst: "Scoring Decision",
  risk_analyst: "Analyzing Risk",
  final_synthesizer: "Synthesizing Report",
  verification_gate: "Verifying",
  complete: "Complete",
  failed: "Failed",
};

export interface ResearchCreateRequest {
  question: string;
  constraints?: string[];
  alternatives?: string[];
  criteria?: string[];
  mode?: ResearchMode;
}

export interface ResearchCreateResponse {
  research_id: string;
  status: "pending";
}

export interface ResearchProgress {
  completed_stages: number;
  total_stages: number;
}

export interface ResearchStatusResponse {
  research_id: string;
  status: Extract<SessionStatus, "pending" | "running" | "completed" | "failed">;
  error: string | null;
  report: FinalReport | null;
  stage: string | null;
  progress: ResearchProgress | null;
  question: string | null;
  created_at: string | null;
}

export interface ResearchListItem {
  research_id: string;
  question: string;
  status: Extract<SessionStatus, "pending" | "running" | "completed" | "failed">;
  mode: ResearchMode;
  created_at: string;
  completed_at: string | null;
  stage: string | null;
  confidence: number | null;
  num_sources: number;
  num_risks: number;
}

export interface ResearchListResponse {
  items: ResearchListItem[];
}

export interface SourcesResponse {
  sources: Source[];
}

export interface ClaimWithVerification {
  claim: Claim;
  verification: ClaimVerification | null;
}

export interface ClaimsResponse {
  claims: ClaimWithVerification[];
}

export interface EvidenceResponse {
  evidence: EvidenceItem[];
}

export interface DecisionResponse {
  decision_matrix: DecisionMatrix;
}

export interface TraceResponse {
  execution_metadata: ExecutionMetadata;
  stages: string[];
}

export interface ErrorDetail {
  code: string;
  message: string;
  trace_id: string | null;
}

export interface ErrorResponse {
  error: ErrorDetail;
}

// -- Phase 9 evaluation report (backend/app/evaluation/runner.py) --

export interface EvaluationQuestionResult {
  question_id: string;
  category: string;
  question: string;
  status: string;
  error: string | null;
  metrics: Record<string, unknown>;
}

export interface EvaluationReport {
  generated_at: string;
  provider: string;
  search_provider: string;
  num_questions: number;
  results: EvaluationQuestionResult[];
  aggregate: Record<string, unknown>;
}
