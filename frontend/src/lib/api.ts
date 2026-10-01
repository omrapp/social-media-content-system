import { supabase } from "@/lib/supabase";
import { addLog } from "@/lib/logger";

// Dev: Vite proxy handles /api → localhost:8000 (no env var needed).
// Prod: set VITE_API_BASE_URL=https://social-media-cms.yourdomain.com/api
const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

/** Server origin without the trailing `/api`.
 *  Signed editor proxy URLs already carry their own `/api/...` prefix (they are
 *  built server-side and handed to a <video> element, which cannot send an
 *  Authorization header), so they must be joined to the origin, not to BASE. */
export const API_ORIGIN = BASE.replace(/\/api\/?$/, "");

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const method = options?.method ?? "GET";

  addLog("debug", "api", `${method} ${path}`);

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...options, headers });
  } catch (e) {
    addLog("error", "api", `${method} ${path} → network error`);
    throw e;
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    addLog("error", "api", `${res.status} ${method} ${path} → ${err.detail || res.statusText}`, err);
    throw new Error(err.detail || res.statusText);
  }

  const data = await res.json() as T;
  addLog("success", "api", `${res.status} ${method} ${path}`, data);
  return data;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
