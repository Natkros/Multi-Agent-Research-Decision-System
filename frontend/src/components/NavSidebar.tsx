"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { authApi, isAuthenticated } from "@/lib/auth";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/new", label: "New Research" },
  { href: "/history", label: "History" },
  { href: "/evaluation", label: "Evaluation" },
  { href: "/settings", label: "Settings" },
];

export function NavSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  // Read the client-only auth state after mount (avoids an SSR/client
  // hydration mismatch: the server always renders as "logged out").
  const [authed, setAuthed] = useState(false);
  useEffect(() => setAuthed(isAuthenticated()), [pathname]);

  function handleLogout() {
    authApi.logout();
    router.push("/login");
  }

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-surface-border bg-surface-raised p-4">
      <div className="mb-6 px-2">
        <div className="text-sm font-semibold text-white">Research &amp; Decision</div>
        <div className="text-xs text-slate-500">Multi-Agent System</div>
      </div>
      <nav className="flex flex-col gap-1">
        {LINKS.map((link) => {
          const active = pathname === link.href;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`rounded-md px-3 py-2 text-sm ${
                active
                  ? "bg-blue-500/10 text-blue-300"
                  : "text-slate-400 hover:bg-surface-border hover:text-slate-200"
              }`}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
      {authed && (
        <button
          type="button"
          onClick={handleLogout}
          className="mt-auto rounded-md px-3 py-2 text-left text-sm text-slate-400 hover:bg-surface-border hover:text-slate-200"
        >
          Sign out
        </button>
      )}
    </aside>
  );
}
