import { formatPercent } from "@/lib/format";

function colorFor(value: number): string {
  if (value >= 0.75) return "bg-emerald-500";
  if (value >= 0.5) return "bg-amber-500";
  return "bg-red-500";
}

export function ConfidenceBar({
  value,
  label = "Confidence",
  showLabel = true,
}: {
  value: number;
  label?: string;
  showLabel?: boolean;
}) {
  const pct = Math.max(0, Math.min(1, value));
  return (
    <div className="flex items-center gap-2">
      {showLabel && (
        <span className="w-24 shrink-0 text-xs text-slate-400">{label}</span>
      )}
      <div className="h-1.5 w-full min-w-[60px] overflow-hidden rounded-full bg-surface-border">
        <div
          className={`h-full rounded-full ${colorFor(pct)}`}
          style={{ width: `${pct * 100}%` }}
        />
      </div>
      <span className="w-10 shrink-0 text-right text-xs font-mono text-slate-300">
        {formatPercent(pct)}
      </span>
    </div>
  );
}
