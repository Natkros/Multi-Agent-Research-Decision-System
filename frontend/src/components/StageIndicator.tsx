import { PIPELINE_STAGES, STAGE_LABELS } from "@/types";

interface StageIndicatorProps {
  currentStage: string | null;
  status: string;
}

/** Horizontal step indicator for the Active Research page, driven by the
 * fixed pipeline order (mirrors orchestration/graph.py's node sequence). */
export function StageIndicator({ currentStage, status }: StageIndicatorProps) {
  const currentIndex = currentStage ? PIPELINE_STAGES.indexOf(currentStage as (typeof PIPELINE_STAGES)[number]) : -1;
  const isComplete = status === "completed";
  const isFailed = status === "failed";

  return (
    <div className="flex flex-wrap gap-2">
      {PIPELINE_STAGES.map((stage, i) => {
        const done = isComplete || i < currentIndex;
        const active = !isComplete && i === currentIndex;
        let style = "border-surface-border bg-surface-raised text-slate-500";
        if (done) style = "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
        if (active) style = isFailed
          ? "border-red-500/40 bg-red-500/10 text-red-300"
          : "border-blue-500/40 bg-blue-500/10 text-blue-300 animate-pulse";
        return (
          <div
            key={stage}
            className={`rounded-full border px-3 py-1 text-xs font-medium ${style}`}
          >
            {STAGE_LABELS[stage] ?? stage}
          </div>
        );
      })}
    </div>
  );
}
