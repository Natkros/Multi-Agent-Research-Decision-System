"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Card, EmptyState } from "@/components/Card";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { formatDate, titleCase } from "@/lib/format";
import type { Source } from "@/types";

export function SourceExplorer({ researchId }: { researchId: string }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [sortDesc, setSortDesc] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .getSources(researchId)
      .then((res) => {
        if (!cancelled) setSources(res.sources);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Failed to load sources");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [researchId]);

  const sorted = [...sources].sort((a, b) =>
    sortDesc ? b.credibility_score - a.credibility_score : a.credibility_score - b.credibility_score,
  );

  const columns: DataTableColumn<Source>[] = [
    {
      key: "title",
      header: "Title",
      cell: (s) =>
        s.url ? (
          <a href={s.url} target="_blank" rel="noreferrer" className="font-medium text-blue-300 hover:underline">
            {s.title}
          </a>
        ) : (
          <span className="font-medium text-slate-200">{s.title}</span>
        ),
      className: "max-w-md",
    },
    { key: "type", header: "Type", cell: (s) => <span className="text-xs text-slate-400">{titleCase(s.source_type)}</span> },
    { key: "publisher", header: "Publisher", cell: (s) => <span className="text-xs text-slate-400">{s.publisher ?? "-"}</span> },
    { key: "published", header: "Published", cell: (s) => <span className="text-xs text-slate-400">{s.published_at ? formatDate(s.published_at) : "-"}</span> },
    {
      key: "credibility",
      header: (
        <button onClick={() => setSortDesc((v) => !v)} className="flex items-center gap-1 hover:text-slate-200">
          Credibility {sortDesc ? "↓" : "↑"}
        </button>
      ),
      cell: (s) => <ConfidenceBar value={s.credibility_score} showLabel={false} />,
      className: "w-40",
    },
  ];

  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-slate-400">{sources.length} source(s) used in this research run.</p>
      </Card>
      {error ? (
        <EmptyState message={`Could not load sources: ${error}`} />
      ) : isLoading ? (
        <EmptyState message="Loading sources..." />
      ) : (
        <DataTable columns={columns} rows={sorted} keyFor={(s) => s.id} emptyMessage="No sources recorded." />
      )}
    </div>
  );
}
