import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 30s fresh window — back/forward navigation = instant cache hit
      staleTime: 30_000,
      // Keep unused data 5 min
      gcTime: 5 * 60_000,
      // One retry covers transient blips; auth/validation errors shouldn't retry
      retry: 1,
      // App is WebSocket-driven; focus-refetch would be redundant noise
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
    },
  },
});
