import { useSyncExternalStore } from "react";
import { subscribe, getSnapshot, type Task } from "@/lib/taskStore";

/** All tasks sorted: running first, then by startedAt desc. */
export function useTasks(): Task[] {
  return useSyncExternalStore(subscribe, getSnapshot);
}

/** Only tasks with status === "running". */
export function useActiveTasks(): Task[] {
  return useTasks().filter((t) => t.status === "running");
}

/** Only tasks that have finished (done or error), most recent first. */
export function useRecentTasks(): Task[] {
  return useTasks().filter((t) => t.status !== "running");
}
