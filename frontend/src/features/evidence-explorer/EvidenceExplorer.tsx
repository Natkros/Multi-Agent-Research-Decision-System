"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Card, EmptyState } from "@/components/Card";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { titleCase } from "@/lib/format";
import type { EvidenceItem, EvidenceType, Source } from "@/types";

const EVIDENCE_TYPES: EvidenceType[] = [
  "quantitative",
  "qualitative",
  "benchmark",
  "documentation",
  "expert_analysis",
  "empirical_observation",
  "policy_regulatory",
  "user_provided",
];

const STRENGTH_STYLE: Record<string, string> = {
  strong: "text-emerald-300",
  moderate: "text-amber-300",
  weak: "text-red-300",
};

export function EvidenceExplorer({ researchId }: { researchId: string }) {
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [sources, setSources] = useState<Record<string, Source>>({});
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [minConfidence, setMinConfidence] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    Promise.all([
      api.getEvidence(researchId, {
        evidence_type: typeFilter || undefined,
        min_confidence: minConfidence > 0 ? minConfidence : undefined,
      }),
      api.getSources(researchId),
    ])
      .then(([evidenceRes, sourcesRes]) => {
        if (cancelled) return;
        setEvidence(evidenceRes.evidence);
        const map: Record<string, Source> = {};
        sourcesRes.sources.forEach((s) => (map[s.id] = s));
        setSources(map);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Failed to load evidence");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [researchId, typeFilter, minConfidence]);

  const columns: DataTableColumn<EvidenceItem>[] = useMemo(
    () => [
      {
        key: "evidence",
        header: "Evidence",
        cell: (e) => (
          <div>
            <p className="text-slate-200">{e.evidence_text}</p>
            {e.limitations && <p className="mt-1 text-xs text-amber-300/80">Limitation: {e.limitations}</p>}
          </div>
        ),
        className: "max-w-xl",
      },
      { key: "type", header: "Type", cell: (e) => <span className="text-xs text-slate-400">{titleCase(e.evidence_type)}</span> },
      {
        key: "strength",
        header: "Strength",
        cell: (e) => <span className={`text-xs font-medium ${STRENGTH_STYLE[e.strength]}`}>{titleCase(e.strength)}</span>,
      },
      { key: "confidence", header: "Confidence", cell: (e) => <ConfidenceBar value={e.confidence} showLabel={false} />, className: "w-32" },
      {
        key: "source",
        header: "Source",
        cell: (e) =>
          sources[e.source_id] ? (
            sources[e.source_id]!.url ? (
              <a href={sources[e.source_id]!.url!} target="_blank" rel="noreferrer" className="text-blue-300 hover:underline">
                {sources[e.source_id]!.title}
              </a>
            ) : (
              <span>{sources[e.source_id]!.title}</span>
            )
          ) : (
            <span className="text-slate-500">{e.source_id}</span>
          ),
      },
    ],
    [sources],
  );

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <label className="mb-1 block text-xs text-slate-500">Evidence Type</label>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="rounded-md border border-surface-border bg-surface px-2 py-1.5 text-sm text-slate-200"
            >
              <option value="">All types</option>
              {EVIDENCE_TYPES.map((t) => (
                <option key={t} value={t}>{titleCase(t)}</option>
              ))}
            </select>
          </div>
          <div className="min-w-[220px] flex-1">
            <label className="mb-1 block text-xs text-slate-500">
              Min. Confidence: {minConfidence.toFixed(2)}
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={minConfidence}
              onChange={(e) => setMinConfidence(Number(e.target.value))}
              className="w-full"
            />
          </div>
          <div className="text-xs text-slate-500">{evidence.length} item(s)</div>
        </div>
      </Card>

      {error ? (
        <EmptyState message={`Could not load evidence: ${error}`} />
      ) : isLoading ? (
        <EmptyState message="Loading evidence..." />
      ) : (
        <DataTable columns={columns} rows={evidence} keyFor={(e) => e.id} emptyMessage="No evidence matches the current filters." />
      )}
    </div>
  );
}
