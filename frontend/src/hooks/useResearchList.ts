"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ResearchListItem } from "@/types";

interface UseResearchListResult {
  items: ResearchListItem[];
  error: string | null;
  isLoading: boolean;
  refetch: () => void;
}

/** Dashboard data source: GET /research, with a light auto-refresh so
 * in-flight sessions' status/stage update without a manual reload. */
export function useResearchList(
  { limit = 50, refreshMs }: { limit?: number; refreshMs?: number } = {},
): UseResearchListResult {
  const [items, setItems] = useState<ResearchListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const result = await api.listResearch(limit);
      setItems(result.items);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load research sessions");
    } finally {
      setIsLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    load();
    if (!refreshMs) return;
    const id = setInterval(load, refreshMs);
    return () => clearInterval(id);
  }, [load, refreshMs]);

  return { items, error, isLoading, refetch: load };
}
