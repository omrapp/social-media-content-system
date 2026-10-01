import { useState } from "react";

const MAX_RECENT = 7;

/**
 * MRU list of picked items, persisted to localStorage under `key`.
 * Dedupes by `id`, newest first, capped at MAX_RECENT.
 */
export function useRecentPicks<T extends { id: string }>(key: string) {
  const [recent, setRecent] = useState<T[]>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T[]) : [];
    } catch {
      return [];
    }
  });

  const pushRecent = (item: T) => {
    setRecent((prev) => {
      const next = [item, ...prev.filter((r) => r.id !== item.id)].slice(0, MAX_RECENT);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // localStorage unavailable (private mode, quota) — recent list stays in-memory only
      }
      return next;
    });
  };

  return { recent, pushRecent };
}
