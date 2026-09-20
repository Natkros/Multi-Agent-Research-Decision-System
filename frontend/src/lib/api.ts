/**
 * Typed fetch-based API client. This is the ONLY place in the frontend that
 * calls `fetch()` against the backend -- components/hooks must go through
 * these functions instead of scattering `fetch()` calls (per project rules).
 *
 * Base URL is configurable via NEXT_PUBLIC_API_URL, matching
 * backend/app/config/settings.py's `api_v1_prefix` (default `/api/v1`).
 */

import type {
  ClaimsResponse,
  DecisionResponse,
  ErrorResponse,
  EvaluationReport,
  EvidenceResponse,
  ResearchCreateRequest,
  ResearchCreateResponse,
  ResearchListResponse,
  ResearchStatusResponse,
  SourcesResponse,
  TraceResponse,
} from "@/types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;
  code: string | null;

  constructor(message: string, status: number, code: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function _authHeader(): Record<string, string> {
  // Deferred import avoided here (would create a lib<->lib circular import
  // with auth.ts, which itself imports API_BASE_URL from this module) --
  // read the token straight out of localStorage instead.
  if (typeof window === "undefined") return {};
  try {
    const token = window.localStorage.getItem("research_app_access_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ..._authHeader(),
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch (cause) {
    throw new ApiError(
      `Could not reach the research API at ${API_BASE_URL}. Is the backend running?`,
      0,
      "NETWORK_ERROR",
    );
  }

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    let code: string | null = null;
    try {
      const body = (await response.json()) as ErrorResponse;
      if (body?.error) {
        message = body.error.message ?? message;
        code = body.error.code ?? null;
      }
    } catch {
      // body wasn't JSON -- fall back to the generic message
    }
    if (response.status === 401 && typeof window !== "undefined") {
      // Expired/invalid/missing token: send the user back to log in rather
      // than leaving the page stuck on a failed fetch. This is a plain
      // fetch-wrapper module with no React component tree to call
      // useRouter() from, so a full navigation via window.location is the
      // correct primitive here, not a lint-flagged shortcut.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login");
    }
    throw new ApiError(message, response.status, code);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  /** POST /research -- submit a new research run. */
  createResearch(payload: ResearchCreateRequest): Promise<ResearchCreateResponse> {
    return request<ResearchCreateResponse>("/research", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /** GET /research -- list recent sessions for the Dashboard. */
  listResearch(limit = 50): Promise<ResearchListResponse> {
    return request<ResearchListResponse>(`/research?limit=${limit}`);
  },

  /** GET /research/{id} -- status/progress/report summary. Poll this for
   * live progress (no SSE endpoint exists on the backend yet). */
  getResearchStatus(researchId: string): Promise<ResearchStatusResponse> {
    return request<ResearchStatusResponse>(`/research/${researchId}`);
  },

  /** GET /research/{id}/report -- the full FinalReport, once completed. */
  getReport(researchId: string): Promise<ResearchStatusResponse> {
    return request<ResearchStatusResponse>(`/research/${researchId}/report`);
  },

  /** GET /research/{id}/sources */
  getSources(researchId: string): Promise<SourcesResponse> {
    return request<SourcesResponse>(`/research/${researchId}/sources`);
  },

  /** GET /research/{id}/claims */
  getClaims(researchId: string): Promise<ClaimsResponse> {
    return request<ClaimsResponse>(`/research/${researchId}/claims`);
  },

  /** GET /research/{id}/evidence, optionally filtered. */
  getEvidence(
    researchId: string,
    filters?: { evidence_type?: string; min_confidence?: number },
  ): Promise<EvidenceResponse> {
    const params = new URLSearchParams();
    if (filters?.evidence_type) params.set("evidence_type", filters.evidence_type);
    if (filters?.min_confidence !== undefined) {
      params.set("min_confidence", String(filters.min_confidence));
    }
    const qs = params.toString();
    return request<EvidenceResponse>(`/research/${researchId}/evidence${qs ? `?${qs}` : ""}`);
  },

  /** GET /research/{id}/decision */
  getDecision(researchId: string): Promise<DecisionResponse> {
    return request<DecisionResponse>(`/research/${researchId}/decision`);
  },

  /** GET /research/{id}/trace */
  getTrace(researchId: string): Promise<TraceResponse> {
    return request<TraceResponse>(`/research/${researchId}/trace`);
  },

  /** GET /evaluation/latest -- most recent benchmark run (Phase 9), or
   * `null` if `scripts/evaluate_system.py` hasn't been run yet (404). */
  async getLatestEvaluation(): Promise<EvaluationReport | null> {
    try {
      return await request<EvaluationReport>("/evaluation/latest");
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  },
};

export { API_BASE_URL };
