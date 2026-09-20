"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { authApi } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "register") {
        await authApi.register(email, password);
      }
      await authApi.login(email, password);
      router.push("/");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-24 max-w-sm">
      <h1 className="mb-1 text-xl font-semibold text-slate-900">
        {mode === "login" ? "Sign in" : "Create an account"}
      </h1>
      <p className="mb-6 text-sm text-slate-500">
        Research runs require an account (Phase 8 authentication).
      </p>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
        >
          {busy ? "Please wait..." : mode === "login" ? "Sign in" : "Create account and sign in"}
        </button>
      </form>
      <button
        type="button"
        onClick={() => setMode(mode === "login" ? "register" : "login")}
        className="mt-4 text-sm text-blue-600 hover:underline"
      >
        {mode === "login" ? "Need an account? Register" : "Already have an account? Sign in"}
      </button>
    </div>
  );
}
