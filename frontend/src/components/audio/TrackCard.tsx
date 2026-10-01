import { useEffect, useRef, useState } from "react";
import { Play, Square, Star, Trash2, Scissors, Loader2, AlertTriangle, Tag } from "lucide-react";
import { api } from "@/lib/api";
import { WaveformTrimModal } from "@/components/audio/WaveformTrimModal";
import type { Track } from "@/types/audio";

const CARD_STYLE = {
  background: "linear-gradient(145deg, rgba(17,19,31,1) 0%, rgba(10,10,16,1) 100%)",
  border: "1px solid rgba(255,255,255,0.06)",
  boxShadow: "0 4px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)",
} as const;

export const fmtTime = (sec?: number) => {
  if (!sec || !Number.isFinite(sec)) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
};

export const fmtLastUsed = (iso: string | null) => {
  if (!iso) return "never used";
  const d = new Date(iso);
  return `used ${d.toLocaleDateString()}`;
};

/**
 * Small click-outside multi-select popover for tagging a track's categories.
 * `wrapRef` must point at an ancestor that also contains the trigger button
 * (mirrors MusicPicker.tsx's dropRef) — otherwise a click on the trigger
 * itself is seen as "outside", closing the popover on mousedown and then
 * immediately reopening it on the trigger's own click handler.
 */
export function CategoryEditor({
  track, categories, wrapRef, onClose, onSave,
}: {
  track: Track;
  categories: string[];
  wrapRef: React.RefObject<HTMLDivElement>;
  onClose: () => void;
  onSave: (next: string[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>(track.categories ?? []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        onSave(selected);
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const toggle = (p: string) =>
    setSelected((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));

  return (
    <div
      className="absolute z-40 top-full left-0 mt-1 p-2 rounded-xl flex flex-wrap gap-1 w-48"
      style={{ background: "rgba(20,20,28,0.98)", border: "1px solid rgba(255,255,255,0.1)", boxShadow: "0 8px 24px rgba(0,0,0,0.5)" }}
    >
      {categories.map((p) => {
        const on = selected.includes(p);
        return (
          <button
            key={p}
            type="button"
            onClick={() => toggle(p)}
            className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
              on ? "bg-indigo-600 border-indigo-500 text-white" : "bg-gray-900 border-gray-700 text-gray-400 hover:border-gray-500"
            }`}
          >
            {p.replace("_", " ")}
          </button>
        );
      })}
    </div>
  );
}

export function TrackCard({
  track, categories, playingId, currentTime, duration, onTogglePlay, onChanged,
}: {
  track: Track;
  categories: string[];
  playingId: string | null;
  /** Live playback position/duration of the shared parent <audio> element —
   * only meaningful when `playingId === track.id`. */
  currentTime: number;
  duration: number;
  onTogglePlay: (t: Track) => void;
  onChanged: (updated: Track | null, removedId?: string) => void;
}) {
  const [favSaving, setFavSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [categoryMenuOpen, setCategoryMenuOpen] = useState(false);
  const categoryWrapRef = useRef<HTMLDivElement>(null);
  const [trimOpen, setTrimOpen] = useState(false);
  const [rowErr, setRowErr] = useState<string | null>(null);

  const toggleFavourite = async () => {
    setFavSaving(true);
    setRowErr(null);
    try {
      const updated = await api.put<Track>(`/audio/${track.id}`, { favourite: !track.favourite });
      onChanged(updated);
    } catch (e) {
      setRowErr(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setFavSaving(false);
    }
  };

  const saveCategories = async (next: string[]) => {
    if (next.join(",") === (track.categories ?? []).join(",")) return;
    try {
      const updated = await api.put<Track>(`/audio/${track.id}`, { categories: next });
      onChanged(updated);
    } catch (e) {
      setRowErr(e instanceof Error ? e.message : "Failed to update tags");
    }
  };

  const del = async () => {
    if (!confirm(`Delete "${track.title}"? This removes the file from disk.`)) return;
    setDeleting(true);
    try {
      await api.delete(`/audio/${track.id}`);
      onChanged(null, track.id);
    } catch (e) {
      setRowErr(e instanceof Error ? e.message : "Delete failed");
      setDeleting(false);
    }
  };

  const isPlaying = playingId === track.id;

  return (
    <div className="rounded-2xl p-4 flex flex-col gap-3" style={CARD_STYLE}>
      <div className="flex items-start gap-3">
        <button
          onClick={() => onTogglePlay(track)}
          disabled={!track.url}
          title={!track.url ? "File not found on disk" : isPlaying ? "Stop" : "Play"}
          className="shrink-0 w-9 h-9 rounded-full flex items-center justify-center cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ background: "rgba(99,102,241,0.15)", border: "1px solid rgba(99,102,241,0.3)", color: "#c7d2fe" }}
        >
          {isPlaying ? <Square size={13} /> : <Play size={13} />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white truncate" title={track.title}>{track.title}</span>
            <button
              onClick={() => void toggleFavourite()}
              disabled={favSaving}
              title={track.favourite ? "Unfavourite" : "Favourite"}
              className="shrink-0 cursor-pointer disabled:opacity-40"
            >
              {favSaving ? (
                <Loader2 size={13} className="animate-spin text-gray-500" />
              ) : (
                <Star size={13} className={track.favourite ? "text-amber-400 fill-amber-400" : "text-gray-600 hover:text-amber-300"} />
              )}
            </button>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-gray-600 mt-0.5">
            {isPlaying ? (
              <span className="tabular-nums font-mono">{fmtTime(currentTime)} / {fmtTime(duration || track.duration)}</span>
            ) : (
              <span className="tabular-nums font-mono">{fmtTime(track.duration)}</span>
            )}
            <span>·</span>
            <span className="capitalize">{track.source}</span>
            {track.license && (<><span>·</span><span className="truncate">{track.license}</span></>)}
          </div>
          {isPlaying && (
            <div className="mt-1.5 h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
              <div
                className="h-full rounded-full"
                style={{ width: `${duration ? Math.min(100, (currentTime / duration) * 100) : 0}%`, background: "#6366f1" }}
              />
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 text-[11px] text-gray-500">
        <span className="flex items-center gap-1">
          <span className="px-1.5 py-0.5 rounded font-mono" style={{ background: "rgba(255,255,255,0.05)" }}>
            {track.usage_count} use{track.usage_count === 1 ? "" : "s"}
          </span>
        </span>
        <span className="truncate">{fmtLastUsed(track.last_used_at)}</span>
        {track.mood && <span className="capitalize truncate">· {track.mood}</span>}
      </div>

      <div ref={categoryWrapRef} className="relative flex items-center gap-1.5 flex-wrap">
        <button
          onClick={() => setCategoryMenuOpen((o) => !o)}
          className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border border-dashed border-gray-700 text-gray-500 hover:border-gray-500 hover:text-gray-300 cursor-pointer transition-colors"
        >
          <Tag size={10} /> Tag
        </button>
        {(track.categories ?? []).map((p) => (
          <span key={p} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">{p.replace("_", " ")}</span>
        ))}
        {categoryMenuOpen && (
          <CategoryEditor
            track={track}
            categories={categories}
            wrapRef={categoryWrapRef}
            onClose={() => setCategoryMenuOpen(false)}
            onSave={(next) => void saveCategories(next)}
          />
        )}
      </div>

      {rowErr && (
        <div className="flex items-center gap-1.5 text-[11px] text-red-400">
          <AlertTriangle size={11} className="shrink-0" /> <span className="truncate">{rowErr}</span>
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-1 border-t border-white/[0.05] mt-1">
        <button
          onClick={() => setTrimOpen(true)}
          disabled={!track.url}
          title={!track.url ? "File not found on disk" : "Trim"}
          className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg cursor-pointer transition-colors text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
        >
          <Scissors size={12} /> Trim
        </button>
        <button
          onClick={() => void del()}
          disabled={deleting}
          className="p-1.5 rounded-lg cursor-pointer transition-colors hover:bg-red-500/10 disabled:opacity-40"
          title="Delete"
        >
          {deleting ? <Loader2 size={13} className="animate-spin text-gray-500" /> : <Trash2 size={13} className="text-gray-600 hover:text-red-400" />}
        </button>
      </div>

      {trimOpen && (
        <WaveformTrimModal
          track={track}
          onClose={() => setTrimOpen(false)}
          onSaved={(newTrack) => { onChanged(newTrack); setTrimOpen(false); }}
        />
      )}
    </div>
  );
}
