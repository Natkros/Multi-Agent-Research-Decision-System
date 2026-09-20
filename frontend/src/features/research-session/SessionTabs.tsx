"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { suffix: "", label: "Overview" },
  { suffix: "/report", label: "Report" },
  { suffix: "/evidence", label: "Evidence" },
  { suffix: "/sources", label: "Sources" },
  { suffix: "/decision", label: "Decision Matrix" },
  { suffix: "/trace", label: "Agent Trace" },
];

export function SessionTabs({ researchId }: { researchId: string }) {
  const pathname = usePathname();
  const base = `/research/${researchId}`;

  return (
    <div className="mb-6 flex gap-1 border-b border-surface-border">
      {TABS.map((tab) => {
        const href = `${base}${tab.suffix}`;
        const active = pathname === href;
        return (
          <Link
            key={tab.suffix}
            href={href}
            className={`border-b-2 px-3 py-2 text-sm ${
              active
                ? "border-blue-500 text-blue-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
