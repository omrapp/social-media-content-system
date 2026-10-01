/**
 * Global task store — module singleton, survives React navigation.
 * Mirrors the @/lib/logger pattern: plain module state + subscribe/notify.
 *
 * Persisted to sessionStorage (key: "task_center_v1") so tasks survive
 * a full browser reload. Stale running tasks (>15 min old) are auto-marked
 * as "interrupted" on hydration so they never show a forever-spinning ghost.
 */

export type TaskType = "create" | "pipeline" | "edit" | "download" | "publish";
export type TaskStatus = "running" | "done" | "error";

export interface Task {
  /** Stable key: mediaId for create, postId for edit/publish, "pipeline:{stage}" for pipeline, "download:{type}" for downloads */
  id: string;
  type: TaskType;
  label: string;
  status: TaskStatus;
  /** Current sub-stage (pipeline / create) */
  stage?: string;
  /** Result summary or error message */
  detail?: string;
  mediaId?: string;
  postId?: string;
  startedAt: number;   // Date.now()
  finishedAt?: number;
}

// ── Module state ──────────────────────────────────────────────────────────────

const STORAGE_KEY = "task_center_v1";
const STALE_MS = 15 * 60 * 1000; // 15 min

type Listener = () => void;

let _tasks: Map<string, Task> = new Map();
const _listeners = new Set<Listener>();
let _snapshot: Task[] = [];
let _snapshotDirty = true;

// ── Hydrate from sessionStorage ───────────────────────────────────────────────

function hydrate() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const arr = JSON.parse(raw) as Task[];
    const now = Date.now();
    for (const t of arr) {
      // Mark stale running tasks as interrupted so they can't be ghost spinners
      if (t.status === "running" && now - t.startedAt > STALE_MS) {
        t.status = "error";
        t.detail = "Interrupted (reload)";
        t.finishedAt = now;
      }
      _tasks.set(t.id, t);
    }
  } catch {
    // Corrupt storage — start fresh
  }
}

hydrate();
_snapshotDirty = true; // force rebuild after hydration

// ── Persist to sessionStorage ─────────────────────────────────────────────────

function persist() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([..._tasks.values()]));
  } catch {
    // Storage full — ignore
  }
}

// ── Notify subscribers ────────────────────────────────────────────────────────

function notify() {
  _snapshotDirty = true;
  _listeners.forEach((l) => l());
}

// ── Public API ────────────────────────────────────────────────────────────────

/** Create or update a task. Partial — only provided fields are written. */
export function upsertTask(partial: Pick<Task, "id" | "type"> & Partial<Omit<Task, "id" | "type">>): void {
  const existing = _tasks.get(partial.id);
  const task: Task = {
    label: partial.type,      // default
    status: "running",        // default
    ...existing,              // preserve existing fields
    ...partial,               // caller wins for provided fields
    // startedAt is immutable once set — never let a partial update override it
    startedAt: existing?.startedAt ?? partial.startedAt ?? Date.now(),
  };
  _tasks.set(task.id, task);
  persist();
  notify();
}

/** Mark a task as done or error, record finishedAt. */
export function finishTask(id: string, status: "done" | "error", detail?: string): void {
  const existing = _tasks.get(id);
  if (!existing) return;
  const updated: Task = { ...existing, status, detail, finishedAt: Date.now() };
  _tasks.set(id, updated);
  persist();
  notify();
}

/** Remove a single task from the store. */
export function removeTask(id: string): void {
  _tasks.delete(id);
  persist();
  notify();
}

/** Remove all finished (done / error) tasks. */
export function clearFinished(): void {
  for (const [id, t] of _tasks) {
    if (t.status !== "running") _tasks.delete(id);
  }
  persist();
  notify();
}

// ── useSyncExternalStore surface ──────────────────────────────────────────────

export function subscribe(listener: Listener): () => void {
  _listeners.add(listener);
  return () => _listeners.delete(listener);
}

/** Return stable sorted snapshot (running first, then by startedAt desc). Same reference until store mutates. */
export function getSnapshot(): Task[] {
  if (_snapshotDirty) {
    _snapshot = [..._tasks.values()].sort((a, b) => {
      if (a.status === "running" && b.status !== "running") return -1;
      if (b.status === "running" && a.status !== "running") return 1;
      return b.startedAt - a.startedAt;
    });
    _snapshotDirty = false;
  }
  return _snapshot;
}
