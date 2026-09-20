"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { FinalReport } from "@/types";

interface UseReportResult {
  report: FinalReport | null;
  error: string | null;
  isLoading: boolean;
}

/** Fetches the FinalReport once (not polled -- a report is immutable once
 * `status == completed`, per docs/state-schema.md's append-only invariant). */
export function useReport(researchId: string | undefined): UseReportResult {
  const [report, setReport] = useState<FinalReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!researchId) return;
    let cancelled = false;
    setIsLoading(true);
    api
      .getReport(researchId)
      .then((res) => {
        if (cancelled) return;
        setReport(res.report);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load report");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [researchId]);

  return { report, error, isLoading };
}
