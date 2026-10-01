import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Drop-in replacement for the old useState/useEffect fetch hook.
 * Backed by TanStack Query — auto-caches, dedupes, and survives StrictMode.
 * Return shape is identical to the original: {data, loading, error, refetch, setData}.
 */
export function useApi<T>(path: string | null, autoFetch = true, options?: { staleTime?: number }) {
  const queryClient = useQueryClient();

  const { data, isPending, error, refetch } = useQuery<T>({
    // ["api", path] — path string is already a stable primitive key
    queryKey: ["api", path],
    queryFn: () => api.get<T>(path!),
    enabled: !!path && autoFetch,
    ...(options?.staleTime !== undefined && { staleTime: options.staleTime }),
  });

  return {
    data: data ?? null,
    loading: isPending && !!path && autoFetch,
    error: error ? (error as Error).message : null,
    refetch: () => { void refetch(); },
    setData: (value: T | null) => {
      queryClient.setQueryData(["api", path], value);
    },
  };
}
