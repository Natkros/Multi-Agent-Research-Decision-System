"use client";

import { useMemo } from "react";
import { useReport } from "@/hooks/useReport";
import { Card, EmptyState } from "@/components/Card";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { renderTextWithCitations } from "@/components/CitationLink";
import { formatDate, titleCase } from "@/lib/format";
import type { Source } from "@/types";

const RESOLUTION_STYLES: Record<string, string> = {
  unresolved: "text-red-300",
  irreconcilable: "text-red-300",
  resolved_context: "text-emerald-300",
  resolved_favor_a: "text-emerald-300",
  resolved_favor_b: "text-emerald-300",
};

const SEVERITY_STYLE = (severity: number) => {
  if (severity >= 0.66) return "text-red-300";
  if (severity >= 0.33) return "text-amber-300";
  return "text-emerald-300";
};

export function ReportView({ researchId }: { researchId: string }) {
  const { report, error, isLoading } = useReport(researchId);

  const sourcesById = useMemo(() => {
    const map: Record<string, Source> = {};
    (report?.sources ?? []).forEach((s) => (map[s.id] = s));
    return map;
  }, [report]);

  if (isLoading) return <EmptyState message="Loading report..." />;
  if (error) return <EmptyState message={`Could not load report: ${error}`} />;
  if (!report) return <EmptyState message="Report not yet available -- the run may still be in progress." />;

  return (
    <div className="space-y-6">
      <Card title="Executive Summary">
        <p className="text-sm leading-relaxed text-slate-200">
          {renderTextWithCitations(report.executive_summary, report.citations, sourcesById)}
        </p>
        <div className="mt-4 grid grid-cols-2 gap-4 text-xs text-slate-400 sm:grid-cols-3">
          <div>
            <div className="text-slate-500">Question</div>
            <div className="mt-0.5 text-slate-300">{report.research_question}</div>
          </div>
          <div>
            <div className="text-slate-500">Decision Context</div>
            <div className="mt-0.5 text-slate-300">{report.decision_context}</div>
          </div>
          <div>
            <div className="text-slate-500">Overall Confidence</div>
            <ConfidenceBar value={report.confidence} showLabel={false} />
          </div>
        </div>
      </Card>

      <Card title="Alternatives & Criteria">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Alternatives</div>
            <ul className="space-y-1 text-sm text-slate-200">
              {report.alternatives.map((alt) => (
                <li key={alt} className="rounded border border-surface-border bg-surface px-2 py-1">{alt}</li>
              ))}
            </ul>
          </div>
          <div>
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Criteria (weighted)</div>
            <ul className="space-y-1 text-sm text-slate-200">
              {report.criteria.map((c) => (
                <li key={c.name} className="flex items-center justify-between rounded border border-surface-border bg-surface px-2 py-1">
                  <span>{c.name} <span className="text-xs text-slate-500">({c.direction})</span></span>
                  <span className="font-mono text-xs text-slate-400">{(c.weight * 100).toFixed(0)}%</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Card>

      <Card title="Key Findings">
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-200">
          {report.key_findings.map((f, i) => (
            <li key={i}>{renderTextWithCitations(f, report.citations, sourcesById)}</li>
          ))}
        </ul>
      </Card>

      <Card title={`Evidence (${report.evidence.length})`}>
        <div className="space-y-2">
          {report.evidence.map((e) => (
            <div key={e.id} className="rounded border border-surface-border bg-surface p-3 text-sm">
              <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
                <span>{titleCase(e.evidence_type)} &middot; {titleCase(e.strength)}</span>
                <a href={`#source-${e.source_id}`} className="text-blue-300 hover:underline">
                  {sourcesById[e.source_id]?.title ?? e.source_id}
                </a>
              </div>
              <p className="text-slate-200">{e.evidence_text}</p>
              {e.limitations && <p className="mt-1 text-xs text-amber-300/80">Limitation: {e.limitations}</p>}
              <ConfidenceBar value={e.confidence} showLabel={false} />
            </div>
          ))}
        </div>
      </Card>

      <Card title={`Contradictions (${report.contradictions.length})`}>
        {report.contradictions.length === 0 ? (
          <p className="text-sm text-slate-500">No contradictions detected.</p>
        ) : (
          <div className="space-y-2">
            {report.contradictions.map((c) => (
              <div key={c.id} className="rounded border border-surface-border bg-surface p-3 text-sm">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">{titleCase(c.conflict_type)}</span>
                  <span className={RESOLUTION_STYLES[c.resolution_status] ?? "text-slate-400"}>
                    {titleCase(c.resolution_status)}
                  </span>
                </div>
                <p className="mt-1 text-slate-200">{c.explanation}</p>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Comparative Analysis">
        <ComparativeTable report={report} />
      </Card>

      <Card title={`Risk Analysis (${report.risk_analysis.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-border text-left text-xs uppercase text-slate-500">
                <th className="py-1.5 pr-3">Category</th>
                <th className="py-1.5 pr-3">Description</th>
                <th className="py-1.5 pr-3">Probability</th>
                <th className="py-1.5 pr-3">Impact</th>
                <th className="py-1.5 pr-3">Severity</th>
                <th className="py-1.5">Mitigation</th>
              </tr>
            </thead>
            <tbody>
              {report.risk_analysis.map((r) => (
                <tr key={r.id} className="border-b border-surface-border/60 align-top">
                  <td className="py-1.5 pr-3 text-slate-300">{titleCase(r.category)}</td>
                  <td className="py-1.5 pr-3 text-slate-200">{r.description}</td>
                  <td className="py-1.5 pr-3 text-slate-300">{titleCase(r.probability)}</td>
                  <td className="py-1.5 pr-3 text-slate-300">{titleCase(r.impact)}</td>
                  <td className={`py-1.5 pr-3 font-mono ${SEVERITY_STYLE(r.severity)}`}>{r.severity.toFixed(2)}</td>
                  <td className="py-1.5 text-slate-400">{r.mitigation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title={`Assumptions (${report.assumptions.length})`}>
        <ul className="space-y-1.5 text-sm">
          {report.assumptions.map((a) => (
            <li key={a.id} className="flex items-start justify-between gap-3 rounded border border-surface-border bg-surface px-2 py-1.5">
              <span className="text-slate-200">{a.text}</span>
              <span className="shrink-0 rounded-full border border-surface-border px-2 py-0.5 text-xs text-slate-500">{titleCase(a.origin)}</span>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="Decision Rationale">
        <p className="text-sm leading-relaxed text-slate-200">
          {renderTextWithCitations(report.decision_rationale, report.citations, sourcesById)}
        </p>
      </Card>

      <Card title="Limitations">
        {report.limitations.length === 0 ? (
          <p className="text-sm text-slate-500">None noted.</p>
        ) : (
          <ul className="list-disc space-y-1 pl-5 text-sm text-amber-200/90">
            {report.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={`Sources (${report.sources.length})`}>
        <div className="space-y-2">
          {report.sources.map((s) => (
            <div key={s.id} id={`source-${s.id}`} className="rounded border border-surface-border bg-surface p-3 text-sm scroll-mt-6">
              <div className="flex items-center justify-between">
                {s.url ? (
                  <a href={s.url} target="_blank" rel="noreferrer" className="font-medium text-blue-300 hover:underline">
                    {s.title}
                  </a>
                ) : (
                  <span className="font-medium text-slate-200">{s.title}</span>
                )}
                <ConfidenceBar value={s.credibility_score} label="Credibility" />
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {titleCase(s.source_type)} {s.publisher ? `· ${s.publisher}` : ""} {s.published_at ? `· ${formatDate(s.published_at)}` : ""}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function ComparativeTable({ report }: { report: import("@/types").FinalReport }) {
  const matrix = report.comparative_analysis;
  const criteria = matrix.criteria;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-surface-border text-left text-xs uppercase text-slate-500">
            <th className="py-1.5 pr-3">Alternative</th>
            {criteria.map((c) => (
              <th key={c.name} className="py-1.5 pr-3">{c.name}</th>
            ))}
            <th className="py-1.5 pr-3">Weighted Total</th>
          </tr>
        </thead>
        <tbody>
          {report.alternatives.map((alt) => {
            const isRecommended = alt === matrix.recommended;
            return (
              <tr key={alt} className={`border-b border-surface-border/60 ${isRecommended ? "bg-emerald-500/5" : ""}`}>
                <td className="py-1.5 pr-3 font-medium text-slate-100">
                  {alt} {isRecommended && <span className="ml-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-300">Recommended</span>}
                </td>
                {criteria.map((c) => {
                  const score = matrix.scores.find((s) => s.alternative === alt && s.criterion === c.name);
                  return (
                    <td key={c.name} className="py-1.5 pr-3 font-mono text-slate-300">{score ? score.score.toFixed(1) : "-"}</td>
                  );
                })}
                <td className="py-1.5 pr-3 font-mono font-semibold text-slate-100">
                  {matrix.weighted_totals[alt]?.toFixed(2) ?? "-"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
