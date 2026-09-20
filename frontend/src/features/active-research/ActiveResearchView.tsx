"use client";

import Link from "next/link";
import { useResearchStatus } from "@/hooks/useResearchStatus";
import { StageIndicator } from "@/components/StageIndicator";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, EmptyState } from "@/components/Card";
import { STAGE_LABELS } from "@/types";
import { titleCase } from "@/lib/format";

export function ActiveResearchView({ researchId }: { researchId: string }) {
  const { status, error, isLoading } = useResearchStatus(researchId);

  if (isLoading && !status) {
    return <EmptyState message="Loading research status..." />;
  }
  if (error && !status) {
    return <EmptyState message={`Could not load status: ${error}`} />;
  }
  if (!status) {
    return <EmptyState message="Research session not found." />;
  }

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-slate-400">Question</div>
            <div className="mt-1 text-lg font-medium text-white">{status.question ?? "-"}</div>
          </div>
          <StatusBadge status={status.status} />
        </div>
      </Card>

      <Card title="Pipeline Progress">
        <StageIndicator currentStage={status.stage} status={status.status} />
        {status.progress && (
          <p className="mt-3 text-xs text-slate-500">
            {status.progress.completed_stages} / {status.progress.total_stages} stages complete
            {status.stage && status.status === "running" && (
              <> — currently: {STAGE_LABELS[status.stage] ?? titleCase(status.stage)}</>
            )}
          </p>
        )}
      </Card>

      {status.status === "failed" && (
        <Card title="Error">
          <p className="text-sm text-red-300">{status.error ?? "The research run failed."}</p>
        </Card>
      )}

      {status.status === "completed" && (
        <Card title="Report Ready">
          <p className="mb-3 text-sm text-slate-400">
            The research run finished. View the full report, evidence, sources, and decision matrix.
          </p>
          <div className="flex flex-wrap gap-2">
            <Link href={`/research/${researchId}/report`} className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500">
              View Report
            </Link>
            <Link href={`/research/${researchId}/trace`} className="rounded-md border border-surface-border px-4 py-2 text-sm text-slate-300 hover:bg-surface-border">
              Agent Trace
            </Link>
          </div>
        </Card>
      )}

      {(status.status === "pending" || status.status === "running") && (
        <p className="text-xs text-slate-500">Auto-refreshing every 2 seconds...</p>
      )}
    </div>
  );
}
