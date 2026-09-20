"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ResearchStatusResponse } from "@/types";

const TERMINAL_STATUSES = new Set(["completed", "failed"]);

interface UseResearchStatusResult {
  status: ResearchStatusResponse | null;
  error: string | null;
  isLoading: boolean;
  refetch: () => void;
}

/**
 * Polling-based live progress hook. The backend has no SSE stream
 * (docs/api.md's `/stream` endpoint is not implemented), so this polls
 * GET /research/{id} on an interval and stops once the run reaches a
 * terminal status.
 */
export function useResearchStatus(
  researchId: string | undefined,
  { intervalMs = 2000 }: { intervalMs?: number } = {},
): UseResearchStatusResult {
  const [status, setStatus] = useState<ResearchStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  // Holds the latest `fetchOnce` so the setTimeout callbacks below can call
  // it without closing over `fetchOnce` itself (a self-reference the React
  // Compiler-aware lint rules flag, since it can't prove the closure only
  // runs after the const binding settles).
  const fetchOnceRef = useRef<() => void>(() => {});

  const fetchOnce = useCallback(async () => {
    if (!researchId) return;
    try {
      const result = await api.getResearchStatus(researchId);
      if (!mountedRef.current) return;
      setStatus(result);
      setError(null);
      setIsLoading(false);
      if (!TERMINAL_STATUSES.has(result.status)) {
        timerRef.current = setTimeout(() => fetchOnceRef.current(), intervalMs);
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err instanceof ApiError ? err.message : "Failed to load research status");
      setIsLoading(false);
      // keep polling even on a transient error, in case the backend recovers
      timerRef.current = setTimeout(() => fetchOnceRef.current(), intervalMs * 2);
    }
  }, [researchId, intervalMs]);

  useEffect(() => {
    fetchOnceRef.current = fetchOnce;
  }, [fetchOnce]);

  useEffect(() => {
    mountedRef.current = true;
    setIsLoading(true);
    fetchOnce();
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [fetchOnce]);

  const refetch = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    fetchOnce();
  }, [fetchOnce]);

  return { status, error, isLoading, refetch };
}
