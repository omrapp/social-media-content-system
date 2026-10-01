/**
 * Editor top bar: save state, undo/redo, proxy progress, version history, export.
 *
 * Export always renders a NEW media row and repoints the existing post at it,
 * so the button copy says "Export" rather than "Save" — the reel the queue is
 * holding is replaced, not mutated in place.
 *
 * History lives here rather than as a sixth inspector tab: the 288 px aside
 * cannot carry six tabs legibly, and picking a version is a document-level
 * action like save/export, not a property of the selected clip.
 */

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle, ArrowLeft, Check, History, Loader2, RefreshCw, RotateCcw,
  Rocket, Redo2, Undo2,
} from "lucide-react";

import { api } from "@/lib/api";
import { MAX_TOTAL_S, type EditorVersionsResponse, type EditorVersion } from "@/types/editor";
import type { ExportPhase } from "@/hooks/useEditor";

export interface ExportBarProps {
  mediaId: string;
  approx: boolean;
  dirty: boolean;
  savedVersion: number;
  totalDuration: number;
  overLength: boolean;
  canUndo: boolean;
  canRedo: boolean;
  proxyProgress: { done: number; total: number } | null;
  exportPhase: ExportPhase;
  exportMessage: string;
  onUndo: () => void;
  onRedo: () => void;
  onSave: () => void;
  onRebuildProxies: () => void;
  onExport: () => void;
  onLoadVersion: (version: number) => void;
  onRevertToOriginal: () => void;
}

/** "3m ago" / "2d ago" — good enough for a picker, and avoids pulling a date
 *  library into the lazy-loaded editor chunk. */
function relativeTime(iso: string): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function VersionPanel({
  mediaId, savedVersion, currentVersion, onLoadVersion, onRevertToOriginal, onClose,
}: {
  mediaId: string;
  /** Bumped by every save — the refetch trigger, so a version the user just
   *  saved shows up without closing and reopening the panel. */
  savedVersion: number;
  /** The version the working doc actually IS, or null once it has diverged.
   *  Loading an older version leaves the doc dirty, so nothing is "current"
   *  until the next save — marking the newest row would be a lie. */
  currentVersion: number | null;
  onLoadVersion: (version: number) => void;
  onRevertToOriginal: () => void;
  onClose: () => void;
}) {
  const [versions, setVersions] = useState<EditorVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);

  // Lazy: the list is only fetched once the panel is actually mounted (i.e.
  // opened), then refetched on each save.
  useEffect(() => {
    let live = true;
    api.get<EditorVersionsResponse>(`/editor/${mediaId}/versions`)
      .then((res) => { if (live) { setVersions(res.versions ?? []); setError(null); } })
      .catch((e: Error) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [mediaId, savedVersion]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);

  // Newest first — the backend's ordering is not part of the contract.
  const rows = [...(versions ?? [])].sort((a, b) => b.version - a.version);

  return (
    <div
      ref={ref}
      className="absolute right-0 top-full mt-1 z-50 w-80 rounded-xl bg-gray-900
                 ring-1 ring-white/10 shadow-xl p-3 space-y-2"
    >
      <h3 className="text-xs font-semibold text-gray-200">Version history</h3>

      {error && <p className="text-[11px] text-rose-300">{error}</p>}
      {!versions && !error && (
        <div className="flex items-center gap-2 text-[11px] text-gray-500">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
        </div>
      )}
      {versions && rows.length === 0 && (
        <p className="text-[11px] text-gray-500">
          Nothing saved yet. “Save version” snapshots the current edit list.
        </p>
      )}

      {rows.length > 0 && (
        <div className="max-h-64 overflow-y-auto space-y-1 -mx-1 px-1">
          {rows.map((v) => (
            <div
              key={v.id}
              className={`flex items-center gap-2 rounded px-2 py-1.5 ring-1 ${
                v.version === currentVersion
                  ? "bg-indigo-500/10 ring-indigo-400/30"
                  : "bg-white/[0.03] ring-white/5"
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[11px] text-gray-200">v{v.version}</span>
                  {v.approx && (
                    <span
                      title="Reconstructed from how the reel rendered, not from a stored plan"
                      className="text-[9px] px-1 rounded bg-amber-500/10 text-amber-300 ring-1 ring-amber-400/30"
                    >
                      approx
                    </span>
                  )}
                  {v.version === currentVersion && (
                    <span className="text-[9px] text-indigo-300">current</span>
                  )}
                </div>
                <div className="text-[10px] text-gray-500 truncate" title={v.label ?? ""}>
                  {v.label || "no label"} · {relativeTime(v.created_at)}
                </div>
              </div>
              <button
                onClick={() => { onLoadVersion(v.version); onClose(); }}
                className="shrink-0 px-2 py-1 rounded text-[10px] bg-white/5 hover:bg-white/10
                           text-gray-200 ring-1 ring-white/10"
              >
                Load
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="pt-2 border-t border-white/5 space-y-1.5">
        <button
          onClick={() => { onRevertToOriginal(); onClose(); }}
          className="w-full px-2 py-1.5 rounded text-[11px] bg-white/5 hover:bg-white/10
                     text-gray-200 ring-1 ring-white/10 inline-flex items-center justify-center gap-1.5"
        >
          <RotateCcw className="w-3 h-3" /> Revert to original
        </button>
        <p className="text-[10px] text-gray-600">
          Rebuilds the edit list from how the reel was actually rendered, ignoring
          every saved version. Nothing is deleted — loading or reverting is just
          an edit, and saving afterwards creates a new version on top.
        </p>
      </div>
    </div>
  );
}

export function ExportBar({
  mediaId, approx, dirty, savedVersion, totalDuration, overLength,
  canUndo, canRedo, proxyProgress, exportPhase, exportMessage,
  onUndo, onRedo, onSave, onRebuildProxies, onExport,
  onLoadVersion, onRevertToOriginal,
}: ExportBarProps) {
  const exporting = exportPhase === "running";
  const [historyOpen, setHistoryOpen] = useState(false);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <Link
          to={`/preview/${mediaId}`}
          className="p-2 rounded-lg hover:bg-white/10 text-gray-400"
          title="Back to preview"
        >
          <ArrowLeft className="w-4 h-4" />
        </Link>

        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-gray-100 truncate">Reel editor</h1>
          <p className="text-[11px] text-gray-500 truncate">
            {mediaId} · {totalDuration.toFixed(1)}s
            {savedVersion > 0 && <span> · v{savedVersion}</span>}
          </p>
        </div>

        <span
          className={`text-[11px] px-2 py-0.5 rounded-full ring-1 ${
            dirty
              ? "text-amber-300 bg-amber-500/10 ring-amber-400/30"
              : "text-emerald-300 bg-emerald-500/10 ring-emerald-400/30"
          }`}
        >
          {dirty ? "Unsaved" : "Saved"}
        </span>

        <div className="flex-1" />

        <button
          onClick={onUndo} disabled={!canUndo} title="Undo (⌘Z)"
          className="p-2 rounded-lg hover:bg-white/10 text-gray-400 disabled:opacity-30"
        >
          <Undo2 className="w-4 h-4" />
        </button>
        <button
          onClick={onRedo} disabled={!canRedo} title="Redo (⇧⌘Z)"
          className="p-2 rounded-lg hover:bg-white/10 text-gray-400 disabled:opacity-30"
        >
          <Redo2 className="w-4 h-4" />
        </button>
        <button
          onClick={onRebuildProxies}
          title="Re-cut preview proxies for the current trims"
          className="p-2 rounded-lg hover:bg-white/10 text-gray-400"
        >
          <RefreshCw className="w-4 h-4" />
        </button>

        <div className="relative">
          <button
            onClick={() => setHistoryOpen((v) => !v)}
            title="Version history"
            className={`p-2 rounded-lg hover:bg-white/10 ${
              historyOpen ? "bg-white/10 text-gray-200" : "text-gray-400"
            }`}
          >
            <History className="w-4 h-4" />
          </button>
          {historyOpen && (
            <VersionPanel
              mediaId={mediaId}
              savedVersion={savedVersion}
              currentVersion={dirty ? null : savedVersion}
              onLoadVersion={onLoadVersion}
              onRevertToOriginal={onRevertToOriginal}
              onClose={() => setHistoryOpen(false)}
            />
          )}
        </div>

        <button
          onClick={onSave} disabled={!dirty || overLength}
          className="px-3 py-1.5 rounded-lg text-xs bg-white/5 hover:bg-white/10
                     text-gray-200 ring-1 ring-white/10 disabled:opacity-40"
        >
          Save version
        </button>

        <button
          onClick={onExport} disabled={exporting || overLength}
          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 hover:bg-indigo-500
                     text-white inline-flex items-center gap-1.5 disabled:opacity-40"
        >
          {exporting
            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : exportPhase === "done" ? <Check className="w-3.5 h-3.5" /> : <Rocket className="w-3.5 h-3.5" />}
          {exporting ? "Exporting…" : "Export reel"}
        </button>
      </div>

      {approx && (
        <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 ring-1 ring-amber-400/30 px-3 py-2">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <p className="text-[11px] text-amber-200">
            This reel predates the editor, so its edit list was reconstructed from
            what the merge recorded. Per-cut slow-mo, Ken Burns, cleanup filters and
            the music offset were never stored — exporting produces a close, but not
            identical, reel.
          </p>
        </div>
      )}

      {overLength && (
        <div className="rounded-lg bg-rose-500/10 ring-1 ring-rose-400/30 px-3 py-2 text-[11px] text-rose-200">
          Reel is {totalDuration.toFixed(1)}s — over the {MAX_TOTAL_S}s limit. Trim or
          delete cuts before saving or exporting.
        </div>
      )}

      {proxyProgress && (
        <div className="flex items-center gap-2 text-[11px] text-gray-400">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Preparing previews {proxyProgress.done}/{proxyProgress.total}
        </div>
      )}

      {exportMessage && exportPhase !== "idle" && (
        <div
          className={`text-[11px] ${
            exportPhase === "error" ? "text-rose-300"
              : exportPhase === "done" ? "text-emerald-300" : "text-gray-400"
          }`}
        >
          {exportMessage}
        </div>
      )}
    </div>
  );
}
