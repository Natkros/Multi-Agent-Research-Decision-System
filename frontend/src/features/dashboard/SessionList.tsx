"use client";

import Link from "next/link";
import { useResearchList } from "@/hooks/useResearchList";
import { StatusBadge } from "@/components/StatusBadge";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { EmptyState } from "@/components/Card";
import { formatDate, titleCase } from "@/lib/format";
import type { ResearchListItem } from "@/types";

function destinationFor(item: ResearchListItem): string {
  return item.status === "completed" ? `/research/${item.research_id}/report` : `/research/${item.research_id}`;
}

export function SessionList() {
  const { items, error, isLoading, refetch } = useResearchList({ refreshMs: 5000 });

  if (error) {
    return (
      <EmptyState message={`Could not load research sessions: ${error}`} />
    );
  }
  if (isLoading && items.length === 0) {
    return <EmptyState message="Loading research sessions..." />;
  }
  if (items.length === 0) {
    return <EmptyState message="No research sessions yet. Start one from New Research." />;
  }

  const columns: DataTableColumn<ResearchListItem>[] = [
    {
      key: "question",
      header: "Question",
      cell: (row) => (
        <Link href={destinationFor(row)} className="font-medium text-slate-100 hover:text-blue-300">
          {row.question}
        </Link>
      ),
      className: "max-w-md",
    },
    { key: "status", header: "Status", cell: (row) => <StatusBadge status={row.status} /> },
    { key: "stage", header: "Stage", cell: (row) => <span className="text-xs text-slate-400">{row.stage ? titleCase(row.stage) : "-"}</span> },
    { key: "mode", header: "Mode", cell: (row) => <span className="text-xs text-slate-400">{titleCase(row.mode)}</span> },
    {
      key: "confidence",
      header: "Confidence",
      cell: (row) => (row.confidence != null ? <ConfidenceBar value={row.confidence} showLabel={false} /> : <span className="text-xs text-slate-600">-</span>),
      className: "w-40",
    },
    { key: "sources", header: "Sources", cell: (row) => <span className="font-mono text-xs">{row.num_sources}</span> },
    { key: "risks", header: "Risks", cell: (row) => <span className="font-mono text-xs">{row.num_risks}</span> },
    { key: "created", header: "Created", cell: (row) => <span className="text-xs text-slate-400">{formatDate(row.created_at)}</span> },
  ];

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button
          onClick={refetch}
          className="rounded-md border border-surface-border px-3 py-1 text-xs text-slate-300 hover:bg-surface-border"
        >
          Refresh
        </button>
      </div>
      <DataTable columns={columns} rows={items} keyFor={(row) => row.research_id} />
    </div>
  );
}
