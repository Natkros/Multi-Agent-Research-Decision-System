"use client";

/**
 * Phase 8: the backend now requires a Bearer JWT on every research
 * endpoint. This is a lightweight client-side gate -- not a security
 * boundary (the backend already enforces auth on every request) -- so an
 * unauthenticated visit to any page other than /login redirects there
 * instead of rendering pages that will just 401 on their first fetch.
 */

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { isAuthenticated } from "@/lib/auth";

const PUBLIC_PATHS = new Set(["/login"]);

export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (PUBLIC_PATHS.has(pathname)) {
      setReady(true);
      return;
    }
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [pathname, router]);

  if (!ready && !PUBLIC_PATHS.has(pathname)) {
    return null;
  }
  return <>{children}</>;
}
