"use client";

import { useEffect, useState } from "react";
import { Card, EmptyState, PageHeader } from "@/components/Card";
import { api, ApiError } from "@/lib/api";
import type { EvaluationReport } from "@/types";

/**
 * Phase 9 evaluation dashboard (docs/evaluation.md §4, brief §24-25). Reads
 * the static report `backend/scripts/evaluate_system.py` last wrote via
 * `GET /evaluation/latest` -- a table is enough here (brief §39: prioritize
 * reliability over flashy UI), no live benchmark run happens from this page.
 */

function formatMetric(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function EvaluationPage() {
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .getLatestEvaluation()
      .then((r) => {
        if (!cancelled) setReport(r);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <PageHeader
        title="Evaluation"
        description="Benchmark run results from backend/scripts/evaluate_system.py (docs/evaluation.md)."
      />

      {isLoading && <EmptyState message="Loading evaluation report..." />}
      {!isLoading && error && <EmptyState message={`Could not load evaluation report: ${error}`} />}
      {!isLoading && !error && !report && (
        <EmptyState message="No evaluation report yet. Run `python scripts/evaluate_system.py` from backend/ to generate one." />
      )}

      {report && (
        <div className="space-y-4">
          <Card title="Run summary">
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div>
                <dt className="text-slate-500">Provider</dt>
                <dd className="font-mono text-slate-200">{report.provider} / {report.search_provider}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Questions</dt>
                <dd className="font-mono text-slate-200">{report.num_questions}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Generated</dt>
                <dd className="font-mono text-slate-200">{new Date(report.generated_at).toLocaleString()}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Success rate</dt>
                <dd className="font-mono text-slate-200">{formatMetric(report.aggregate.success_rate)}</dd>
              </div>
            </dl>
          </Card>

          <Card title="Aggregate metrics">
            <table className="w-full text-left text-sm">
              <tbody>
                {Object.entries(report.aggregate)
                  .filter(([key]) => key !== "success_rate")
                  .map(([key, value]) => (
                    <tr key={key} className="border-b border-surface-border/60 last:border-0">
                      <td className="py-1.5 pr-4 text-slate-400">{key}</td>
                      <td className="py-1.5 font-mono text-slate-200">{formatMetric(value)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </Card>

          <Card title="Per-question results">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-surface-border text-slate-500">
                    <th className="py-1.5 pr-4">ID</th>
                    <th className="py-1.5 pr-4">Category</th>
                    <th className="py-1.5 pr-4">Status</th>
                    <th className="py-1.5 pr-4">Question</th>
                  </tr>
                </thead>
                <tbody>
                  {report.results.map((r) => (
                    <tr key={r.question_id} className="border-b border-surface-border/60 last:border-0">
                      <td className="py-1.5 pr-4 font-mono text-xs text-slate-400">{r.question_id}</td>
                      <td className="py-1.5 pr-4 text-xs text-slate-400">{r.category}</td>
                      <td className="py-1.5 pr-4 text-xs">
                        <span className={r.status === "completed" ? "text-emerald-400" : "text-red-400"}>
                          {r.status}
                        </span>
                      </td>
                      <td className="py-1.5 pr-4 text-slate-200">{r.question}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
