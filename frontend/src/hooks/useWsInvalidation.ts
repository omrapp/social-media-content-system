import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { onWsEvent } from "@/lib/ws";

/**
 * Central WS → cache invalidation.
 * Mounted once in ProtectedRoutes (App.tsx) — maps WS events to query key prefixes.
 *
 * Uses prefix matching via queryKey[1]?.startsWith() so a "post_status" event
 * invalidates "/posts?limit=100", "/posts?media_id=…", etc. regardless of params.
 */
export function useWsInvalidation() {
  const queryClient = useQueryClient();

  useEffect(() => {
    const unsubs: (() => void)[] = [];

    // post_status → any query whose path starts with "/posts"
    unsubs.push(
      onWsEvent("post_status", () => {
        queryClient.invalidateQueries({
          predicate: (q) => {
            const key = q.queryKey as unknown[];
            return key[0] === "api" && typeof key[1] === "string" && key[1].startsWith("/posts");
          },
        });
      })
    );

    // pipeline_* → /pipeline/runs
    const pipelineEvents = ["pipeline_start", "pipeline_stage_start", "pipeline_stage_complete", "pipeline_complete"] as const;
    for (const event of pipelineEvents) {
      unsubs.push(
        onWsEvent(event, () => {
          queryClient.invalidateQueries({
            predicate: (q) => {
              const key = q.queryKey as unknown[];
              return key[0] === "api" && typeof key[1] === "string" && key[1].startsWith("/pipeline");
            },
          });
        })
      );
    }

    // edit_complete → /posts (preview page post state)
    unsubs.push(
      onWsEvent("edit_complete", () => {
        queryClient.invalidateQueries({
          predicate: (q) => {
            const key = q.queryKey as unknown[];
            return key[0] === "api" && typeof key[1] === "string" && key[1].startsWith("/posts");
          },
        });
      })
    );

    return () => unsubs.forEach((fn) => fn());
  }, [queryClient]);
}
