import { titleCase } from "@/lib/format";

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-slate-700/40 text-slate-300 border-slate-600",
  running: "bg-blue-500/10 text-blue-300 border-blue-500/40 animate-pulse",
  completed: "bg-emerald-500/10 text-emerald-300 border-emerald-500/40",
  failed: "bg-red-500/10 text-red-300 border-red-500/40",
  cancelled: "bg-amber-500/10 text-amber-300 border-amber-500/40",
};

export function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? "bg-slate-700/40 text-slate-300 border-slate-600";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${style}`}
    >
      {titleCase(status)}
    </span>
  );
}
