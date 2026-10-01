import { useEffect } from "react";
import { onWsEvent } from "@/lib/ws";
import { upsertTask, finishTask } from "@/lib/taskStore";

/**
 * Mounted ONCE in ProtectedRoutes (App.tsx).
 * Translates every backend WS event into task store mutations.
 *
 * Event payload shapes (confirmed from backend/api/ws.py + routes):
 *   pipeline_start         {stage}
 *   pipeline_stage_start   {stage, result:{}}
 *   pipeline_stage_complete{stage, result:{processed,failed,...}}
 *   pipeline_complete      {stage,result}  OR  {media_id,source}  ← disambiguate
 *   pipeline_failed        {media_id,error}
 *   edit_dispatched        {post_id,stages,params}
 *   edit_complete          {post_id,result}
 *   edit_failed            {post_id,error}
 *   download_start         {type}
 *   download_complete      {type,result?}
 *   post_status            {post_id,status,...}
 */
export function useTaskTracker() {
  useEffect(() => {
    const unsubs: (() => void)[] = [];

    // ── Pipeline: individual stage trigger ────────────────────────────────────
    unsubs.push(
      onWsEvent("pipeline_start", (data) => {
        const stage = String(data.stage ?? "");
        if (!stage) return;
        upsertTask({
          id: `pipeline:${stage}`,
          type: "pipeline",
          label: `Pipeline: ${stage}`,
          status: "running",
          stage,
        });
      })
    );

    // ── Pipeline: orchestrator sub-stages ─────────────────────────────────────
    unsubs.push(
      onWsEvent("pipeline_stage_start", (data) => {
        const stage = String(data.stage ?? "");
        // Update create task's stage if one is running, otherwise update/create pipeline task
        upsertTask({
          id: `pipeline:orchestrator`,
          type: "pipeline",
          label: "Pipeline: orchestrator",
          status: "running",
          stage,
        });
      })
    );

    unsubs.push(
      onWsEvent("pipeline_stage_complete", (data) => {
        const stage = String(data.stage ?? "");
        const result = data.result as Record<string, unknown> | undefined;
        const processed = Number(result?.processed ?? result?.uploaded ?? result?.edited ?? result?.downloaded ?? result?.rendered ?? 0);
        const failed = Number(result?.failed ?? result?.errors ?? 0);
        upsertTask({
          id: `pipeline:orchestrator`,
          type: "pipeline",
          label: "Pipeline: orchestrator",
          status: "running",
          stage: `${stage} ✓`,
          detail: `${processed} ok${failed ? `, ${failed} fail` : ""}`,
        });
      })
    );

    // ── Pipeline: completion — two shapes ─────────────────────────────────────
    unsubs.push(
      onWsEvent("pipeline_complete", (data) => {
        const mediaId = data.media_id as string | undefined;
        const stage = data.stage as string | undefined;

        if (mediaId) {
          // Create-video completion (posts.py broadcasts {media_id, source})
          finishTask(mediaId, "done", "Video created successfully");
        } else if (stage) {
          // Individual stage or orchestrator completion
          const id = `pipeline:${stage}`;
          const result = data.result as Record<string, unknown> | undefined;
          const processed = Number(result?.processed ?? result?.uploaded ?? result?.edited ?? result?.downloaded ?? 0);
          const failed = Number(result?.failed ?? result?.errors ?? 0);
          finishTask(id, "done", `${processed} ok${failed ? `, ${failed} fail` : ""}`);
          // Also finish orchestrator task if this was its final event
          finishTask("pipeline:orchestrator", "done", `${processed} ok${failed ? `, ${failed} fail` : ""}`);
        }
      })
    );

    // ── Pipeline: create-video failure ────────────────────────────────────────
    unsubs.push(
      onWsEvent("pipeline_failed", (data) => {
        const mediaId = data.media_id as string | undefined;
        const error = String(data.error ?? "Pipeline failed");
        if (mediaId) {
          finishTask(mediaId, "error", error);
        }
        // Also clear any stuck orchestrator task
        finishTask("pipeline:orchestrator", "error", error);
      })
    );

    // ── Edit dispatch/complete/fail ───────────────────────────────────────────
    unsubs.push(
      onWsEvent("edit_dispatched", (data) => {
        const postId = String(data.post_id ?? "");
        if (!postId) return;
        upsertTask({
          id: `edit:${postId}`,
          type: "edit",
          label: "AI Edit",
          status: "running",
          postId,
        });
      })
    );

    unsubs.push(
      onWsEvent("edit_complete", (data) => {
        const postId = String(data.post_id ?? "");
        if (postId) finishTask(`edit:${postId}`, "done", "Edit complete");
      })
    );

    unsubs.push(
      onWsEvent("edit_failed", (data) => {
        const postId = String(data.post_id ?? "");
        const error = String(data.error ?? "Edit failed");
        if (postId) finishTask(`edit:${postId}`, "error", error);
      })
    );

    // ── Downloads ─────────────────────────────────────────────────────────────
    unsubs.push(
      onWsEvent("download_start", (data) => {
        const type = String(data.type ?? "");
        upsertTask({
          id: `download:${type}`,
          type: "download",
          label: `Download ${type}`,
          status: "running",
        });
      })
    );

    unsubs.push(
      onWsEvent("download_complete", (data) => {
        const type = String(data.type ?? "");
        const result = data.result as Record<string, unknown> | undefined;
        const downloaded = Number(result?.downloaded ?? result?.posts ?? 0);
        finishTask(`download:${type}`, "done", downloaded ? `${downloaded} items` : "Done");
      })
    );

    // ── Publish (post_status) ─────────────────────────────────────────────────
    unsubs.push(
      onWsEvent("post_status", (data) => {
        const postId = String(data.post_id ?? "");
        const status = String(data.status ?? "");
        if (!postId) return;

        if (status === "publishing") {
          upsertTask({
            id: `publish:${postId}`,
            type: "publish",
            label: "Publishing post",
            status: "running",
            postId,
          });
        } else if (status === "posted") {
          finishTask(`publish:${postId}`, "done", "Posted");
        } else if (status === "error") {
          finishTask(`publish:${postId}`, "error", "Publish failed");
        }
      })
    );

    return () => unsubs.forEach((fn) => fn());
  }, []);
}
