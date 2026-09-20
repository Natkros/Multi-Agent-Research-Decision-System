"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Card, EmptyState } from "@/components/Card";
import { ConfidenceBar } from "@/components/ConfidenceBar";
import { formatDate, formatDuration, titleCase } from "@/lib/format";
import { PIPELINE_STAGES, STAGE_LABELS } from "@/types";
import type { AgentRunMeta, ExecutionMetadata } from "@/types";

interface TraceNode {
  stageName: string;
  label: string;
  runs: AgentRunMeta[];
}

export function AgentTraceView({ researchId }: { researchId: string }) {
  const [metadata, setMetadata] = useState<ExecutionMetadata | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [selected, setSelected] = useState<AgentRunMeta | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getTrace(researchId)
      .then((res) => {
        if (!cancelled) setMetadata(res.execution_metadata);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Failed to load trace");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [researchId]);

  const nodes: TraceNode[] = useMemo(() => {
    if (!metadata) return [];
    return PIPELINE_STAGES.filter((s) => s !== "verification_gate").map((stage) => ({
      stageName: stage,
      label: STAGE_LABELS[stage] ?? titleCase(stage),
      runs: metadata.agent_runs.filter((r) => r.agent_name === stage),
    }));
  }, [metadata]);

  if (isLoading) return <EmptyState message="Loading agent trace..." />;
  if (error) return <EmptyState message={`Could not load trace: ${error}`} />;
  if (!metadata) return <EmptyState message="No trace available." />;

  return (
    <div className="space-y-6">
      <Card title="Execution Summary">
        <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <div className="text-xs text-slate-500">Total Agent Runs</div>
            <div className="font-mono text-slate-200">{metadata.agent_runs.length}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Total Tokens</div>
            <div className="font-mono text-slate-200">{metadata.total_tokens.toLocaleString()}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Verification Cycles Used</div>
            <div className="font-mono text-slate-200">{metadata.verification_cycles_used}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Status</div>
            <div className="font-mono text-slate-200">{titleCase(metadata.status)}</div>
          </div>
        </div>
      </Card>

      <Card title="Pipeline Graph">
        <p className="mb-4 text-xs text-slate-500">
          Planner → Researcher (×N, fanned out per research question) → Source Evaluator → Evidence Analyst → Fact
          Checker → Contradiction Detector → Debate → Assumption Analyst → Decision Analyst → Risk Analyst →
          Synthesizer → Verification Gate. Click a node to inspect its run metadata.
        </p>
        <div className="flex flex-wrap items-stretch gap-3">
          {nodes.map((node) => (
            <div key={node.stageName} className="flex flex-col gap-1">
              <div className="text-center text-[10px] uppercase tracking-wide text-slate-500">{node.label}</div>
              <div className="flex flex-wrap gap-1">
                {node.runs.length === 0 ? (
                  <div className="rounded-md border border-dashed border-surface-border px-3 py-2 text-xs text-slate-600">
                    not run
                  </div>
                ) : (
                  node.runs.map((run, i) => (
                    <button
                      key={`${run.agent_name}-${i}-${run.start_time}`}
                      onClick={() => setSelected(run)}
                      className={`rounded-md border px-3 py-2 text-left text-xs transition ${
                        selected === run
                          ? "border-blue-500 bg-blue-500/10 text-blue-200"
                          : run.errors.length > 0
                            ? "border-red-500/40 bg-red-500/5 text-red-300 hover:bg-red-500/10"
                            : "border-surface-border bg-surface text-slate-300 hover:border-blue-500/40 hover:bg-surface-raised"
                      }`}
                    >
                      <div className="font-medium">{node.runs.length > 1 ? `run ${i + 1}` : "run"}</div>
                      <div className="mt-0.5 font-mono text-[10px] text-slate-500">{formatDuration(run.latency_ms)}</div>
                    </button>
                  ))
                )}
              </div>
            </div>
          ))}
          <div className="flex flex-col gap-1">
            <div className="text-center text-[10px] uppercase tracking-wide text-slate-500">Verification Gate</div>
            <div className="rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-slate-300">
              {metadata.verification_cycles_used} cycle(s)
            </div>
          </div>
        </div>
      </Card>

      {selected && (
        <Card title={`Run Detail: ${STAGE_LABELS[selected.agent_name] ?? selected.agent_name}`}>
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
            <Detail label="Agent" value={selected.agent_name} />
            <Detail label="Model" value={selected.model} />
            <Detail label="Trace ID" value={selected.trace_id} mono />
            <Detail label="Started" value={formatDate(selected.start_time)} />
            <Detail label="Ended" value={formatDate(selected.end_time)} />
            <Detail label="Latency" value={formatDuration(selected.latency_ms)} />
            <Detail label="Tokens" value={selected.tokens.toLocaleString()} />
            <Detail
              label="Tool Calls"
              value={selected.tool_calls.length > 0 ? selected.tool_calls.join(", ") : "none"}
            />
            <div>
              <div className="text-xs text-slate-500">Confidence</div>
              {selected.confidence != null ? (
                <ConfidenceBar value={selected.confidence} showLabel={false} />
              ) : (
                <span className="text-slate-500">n/a</span>
              )}
            </div>
          </div>
          {selected.errors.length > 0 && (
            <div className="mt-3 rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">
              <div className="mb-1 text-xs font-medium uppercase tracking-wide">Errors</div>
              <ul className="list-disc space-y-1 pl-5">
                {selected.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="mt-3 text-xs text-slate-600">
            Note: per-agent prompt/response payloads are not persisted in `AgentRunMeta` today, so only run metadata
            (latency, tokens, tools, confidence, errors) is shown here -- not literal input/output text.
          </p>
        </Card>
      )}
    </div>
  );
}

function Detail({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-slate-200 ${mono ? "font-mono text-xs" : ""}`}>{value}</div>
    </div>
  );
}
