"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Card, EmptyState } from "@/components/Card";
import type { DecisionMatrix } from "@/types";

function weightBar(weight: number) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-border">
        <div className="h-full rounded-full bg-blue-500" style={{ width: `${weight * 100}%` }} />
      </div>
      <span className="font-mono text-xs text-slate-400">{(weight * 100).toFixed(0)}%</span>
    </div>
  );
}

export function DecisionMatrixView({ researchId }: { researchId: string }) {
  const [matrix, setMatrix] = useState<DecisionMatrix | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .getDecision(researchId)
      .then((res) => {
        if (!cancelled) setMatrix(res.decision_matrix);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError && err.status === 404
              ? "Decision matrix not available yet for this session."
              : err instanceof ApiError
                ? err.message
                : "Failed to load decision matrix",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [researchId]);

  if (isLoading) return <EmptyState message="Loading decision matrix..." />;
  if (error) return <EmptyState message={error} />;
  if (!matrix) return <EmptyState message="No decision matrix available." />;

  const alternatives = Object.keys(matrix.weighted_totals);
  const maxTotal = Math.max(...Object.values(matrix.weighted_totals), 1);

  return (
    <div className="space-y-6">
      <Card title="Criteria Weights">
        <ul className="space-y-2">
          {matrix.criteria.map((c) => (
            <li key={c.name} className="flex items-center justify-between text-sm">
              <span className="text-slate-200">
                {c.name} <span className="text-xs text-slate-500">({c.direction}, {c.scoring_method.replace("_", " ")})</span>
              </span>
              {weightBar(c.weight)}
            </li>
          ))}
        </ul>
      </Card>

      <Card title="Weighted Scores Matrix">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-border text-left text-xs uppercase text-slate-500">
                <th className="py-1.5 pr-3">Alternative</th>
                {matrix.criteria.map((c) => (
                  <th key={c.name} className="py-1.5 pr-3">{c.name}</th>
                ))}
                <th className="py-1.5 pr-3">Weighted Total</th>
              </tr>
            </thead>
            <tbody>
              {alternatives.map((alt) => {
                const isRecommended = alt === matrix.recommended;
                const total = matrix.weighted_totals[alt] ?? 0;
                return (
                  <tr key={alt} className={`border-b border-surface-border/60 ${isRecommended ? "bg-emerald-500/5" : ""}`}>
                    <td className="py-1.5 pr-3 font-medium text-slate-100">
                      {alt}
                      {isRecommended && (
                        <span className="ml-2 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-300">Recommended</span>
                      )}
                    </td>
                    {matrix.criteria.map((c) => {
                      const score = matrix.scores.find((s) => s.alternative === alt && s.criterion === c.name);
                      return (
                        <td key={c.name} className="py-1.5 pr-3" title={score?.rationale}>
                          <span className="font-mono text-slate-300">{score ? score.score.toFixed(1) : "-"}</span>
                        </td>
                      );
                    })}
                    <td className="py-1.5 pr-3">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-border">
                          <div
                            className={`h-full rounded-full ${isRecommended ? "bg-emerald-500" : "bg-slate-500"}`}
                            style={{ width: `${(total / maxTotal) * 100}%` }}
                          />
                        </div>
                        <span className="font-mono font-semibold text-slate-100">{total.toFixed(2)}</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-slate-500">Hover a score to see its rationale.</p>
      </Card>

      <Card title="Sensitivity Analysis">
        {matrix.sensitivity.length === 0 ? (
          <p className="text-sm text-slate-500">No sensitivity results recorded.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border text-left text-xs uppercase text-slate-500">
                  <th className="py-1.5 pr-3">Criterion</th>
                  <th className="py-1.5 pr-3">Weight Delta</th>
                  <th className="py-1.5 pr-3">Recommendation Changes?</th>
                  <th className="py-1.5">New Recommendation</th>
                </tr>
              </thead>
              <tbody>
                {matrix.sensitivity.map((s, i) => (
                  <tr key={i} className={`border-b border-surface-border/60 ${s.recommendation_changed ? "bg-amber-500/5" : ""}`}>
                    <td className="py-1.5 pr-3 text-slate-200">{s.criterion}</td>
                    <td className="py-1.5 pr-3 font-mono text-slate-300">
                      {s.weight_delta > 0 ? "+" : ""}
                      {(s.weight_delta * 100).toFixed(0)}%
                    </td>
                    <td className="py-1.5 pr-3">
                      {s.recommendation_changed ? (
                        <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-xs text-amber-300">Sensitive</span>
                      ) : (
                        <span className="rounded-full bg-surface-border px-2 py-0.5 text-xs text-slate-400">Stable</span>
                      )}
                    </td>
                    <td className="py-1.5 text-slate-300">{s.new_recommended ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-3 text-xs text-slate-500">
              Rows marked &ldquo;Sensitive&rdquo; show which criteria, if reweighted, would flip the recommendation away from{" "}
              <span className="text-slate-300">{matrix.recommended}</span>.
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}
