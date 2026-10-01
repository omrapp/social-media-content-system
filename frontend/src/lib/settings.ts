import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";

export type SettingsGroup =
  | "approval"
  | "schedule"
  | "ai"
  | "telegram"
  | "music"
  | "taxonomy"
  | "platforms"
  | "analytics"
  | "storage"
  | "branding"
  | "intro"
  | "cast"
  | "color"
  | "monetize"
  | "decaption"
  | "editor";

export interface SettingsResponse {
  settings: Record<string, Record<string, unknown>>;
  secrets_set: Record<string, boolean>;
}

const SETTINGS_KEY = ["api", "/settings"] as const;

/**
 * Drop-in replacement for the old useSettings hook.
 * Backed by TanStack Query for caching + dedup.
 * Return shape is identical: {data, loading, error, saving, save, refetch}.
 */
export function useSettings() {
  const queryClient = useQueryClient();
  const [saving, setSaving] = useState<SettingsGroup | null>(null);

  const { data, isPending, error, refetch } = useQuery<SettingsResponse>({
    queryKey: SETTINGS_KEY,
    queryFn: () => api.get<SettingsResponse>("/settings"),
  });

  const save = useCallback(
    async (group: SettingsGroup, value: Record<string, unknown>) => {
      setSaving(group);
      try {
        const updated = await api.put<{ group: SettingsGroup; value: Record<string, unknown> }>(
          "/settings",
          { group, value }
        );
        // Optimistic local merge — matches previous behaviour
        queryClient.setQueryData<SettingsResponse>(SETTINGS_KEY, (prev) =>
          prev
            ? { ...prev, settings: { ...prev.settings, [group]: updated.value } }
            : prev
        );
        toast.success(`${group} settings saved`);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Failed to save settings");
      } finally {
        setSaving(null);
      }
    },
    [queryClient]
  );

  return {
    data: data ?? null,
    loading: isPending,
    error: error ? (error as Error).message : null,
    saving,
    save,
    refetch: () => { void refetch(); },
  };
}
