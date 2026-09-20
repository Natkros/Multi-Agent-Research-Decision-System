/**
 * Minimal client-side auth for the now-authenticated backend (Phase 8).
 * Token lives in localStorage only -- there is no server-rendered auth
 * state in this app, so every page that calls `api` already runs client
 * components (see the `features/*` hooks), matching how `api.ts` itself
 * only ever runs in the browser (`fetch` against `NEXT_PUBLIC_API_URL`).
 */

import { API_BASE_URL } from "@/lib/api";

const TOKEN_KEY = "research_app_access_token";

export interface AuthUser {
  id: string;
  email: string;
  role: string;
  created_at: string;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
  user: AuthUser;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // localStorage can throw in a private-browsing/blocked-storage context;
    // the user simply has to log in again next visit, not a crash.
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // see setToken
  }
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

async function authRequest<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const data = await response.json();
      message = data?.detail?.error?.message ?? data?.detail ?? message;
    } catch {
      // non-JSON error body -- fall back to the generic message
    }
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return (await response.json()) as T;
}

export const authApi = {
  async login(email: string, password: string): Promise<LoginResult> {
    const result = await authRequest<LoginResult>("/auth/login", { email, password });
    setToken(result.access_token);
    return result;
  },

  async register(email: string, password: string): Promise<AuthUser> {
    return authRequest<AuthUser>("/auth/register", { email, password });
  },

  logout(): void {
    clearToken();
  },
};
