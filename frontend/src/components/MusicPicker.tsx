import { useRef, useState, useEffect } from "react";
import { useApi } from "@/hooks/useApi";
import { useRecentPicks } from "@/hooks/useRecentPicks";
import { api } from "@/lib/api";
import { Music, Upload, RefreshCw, ChevronDown, Play, Square, Search, Clock } from "lucide-react";
import { CATEGORIES } from "@/constants/media";

const MEDIA_ORIGIN = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/api\/?$/, "");
const audioSrc = (url: string) => (url.startsWith("http") ? url : `${MEDIA_ORIGIN}${url}`);

// Canonical category taxonomy (mirrors constants/media.ts) for the filter row.
const FILTER_CATEGORIES = CATEGORIES.filter((c) => c !== "all");

const fmtTime = (sec: number) => {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
};

interface Track {
  id: string;
  title: string;
  duration?: number;
  source: "local";
  category?: string;
  shared?: boolean;
  url: string;
}

interface MusicResponse {
  music: Track[];
}

interface RecentTrack {
  id: string;
  title: string;
  url: string;
}

interface Props {
  value: string;
  onChange: (id: string, url: string, startSec?: number, endSec?: number) => void;
  /** Current media category for re-fetch — optional, defaults to "hidden_gem" */
  category?: string;
  /** Current media tags for re-fetch — optional */
  tags?: string[];
}

export function MusicPicker({ value, onChange, category = "hidden_gem", tags }: Props) {
  const { data, loading, refetch } = useApi<MusicResponse>("/assets/music");
  const tracks = data?.music ?? [];
  const { recent, pushRecent } = useRecentPicks<RecentTrack>("music_picker_recent");
  const fileRef = useRef<HTMLInputElement>(null);
  const dropRef = useRef<HTMLDivElement>(null);
  const trackBarRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");   // search filter for the track list
  const [categoryFilter, setCategoryFilter] = useState<string[]>([]);  // OR-combined category chips
  const [sharedOnly, setSharedOnly] = useState(false);  // AND filter — tracks tagged to multiple categories
  const [uploading, setUploading] = useState(false);
  const [refetching, setRefetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Playback position
  const [currentTime, setCurrentTime] = useState(0);
  const [audioDuration, setAudioDuration] = useState(0);

  // Trim — refs for audio callbacks (no stale closure), state for render
  const startSecRef = useRef(0);
  const endSecRef = useRef<number | null>(null);
  const [startSec, setStartSecState] = useState(0);
  const [endSec, setEndSecState] = useState<number | null>(null);
  const dragTarget = useRef<"start" | "end" | null>(null);

  const setStartSec = (v: number) => { startSecRef.current = v; setStartSecState(v); };
  const setEndSec = (v: number | null) => { endSecRef.current = v; setEndSecState(v); };

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => () => { audioRef.current?.pause(); }, []);

  const selectedTrack = tracks.find((t) => t.id === value);
  const q = query.trim().toLowerCase();
  const toggleCategory = (c: string) =>
    setCategoryFilter((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  // Text search (contains, case-insensitive) AND category chips (OR across checked).
  const filteredTracks = tracks.filter((t) => {
    const matchText = !q || `${t.title} ${t.category ?? ""}`.toLowerCase().includes(q);
    const matchCategory = categoryFilter.length === 0 || (!!t.category && categoryFilter.includes(t.category));
    const matchShared = !sharedOnly || !!t.shared;
    return matchText && matchCategory && matchShared;
  });

  const togglePlay = (t: Track) => {
    if (playingId === t.id) {
      audioRef.current?.pause();
      setPlayingId(null);
      return;
    }
    if (!audioRef.current) audioRef.current = new Audio();
    const audio = audioRef.current;
    audio.pause();
    audio.src = audioSrc(t.url);
    audio.currentTime = startSecRef.current;
    audio.ontimeupdate = () => {
      setCurrentTime(audio.currentTime);
      const stop = endSecRef.current ?? audio.duration;
      if (stop && audio.currentTime >= stop) {
        audio.pause();
        setPlayingId(null);
      }
    };
    audio.onloadedmetadata = () => {
      setAudioDuration(audio.duration);
      if (endSecRef.current === null) setEndSec(audio.duration);
    };
    audio.onended = () => setPlayingId(null);
    audio.play().then(() => setPlayingId(t.id)).catch(() => setPlayingId(null));
  };

  const applyPick = (id: string, url: string) => {
    setStartSec(0);
    setEndSec(null);
    setAudioDuration(0);
    setCurrentTime(0);
    onChange(id, url, 0, undefined);
    setOpen(false);
  };

  const selectTrack = (t: Track) => {
    applyPick(t.id, t.url);
    pushRecent({ id: t.id, title: t.title, url: t.url });
  };

  const quickSelect = (r: RecentTrack) => {
    applyPick(r.id, r.url);
    pushRecent(r);
  };

  // Bar drag helpers
  const getTotal = () => audioDuration || selectedTrack?.duration || 100;

  const getPct = (e: React.MouseEvent | React.PointerEvent) => {
    const rect = trackBarRef.current!.getBoundingClientRect();
    return Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
  };

  const handleBarClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    const sec = (getPct(e) / 100) * getTotal();
    if (audioRef.current) audioRef.current.currentTime = sec;
    setCurrentTime(sec);
  };

  const startDrag = (e: React.PointerEvent, target: "start" | "end") => {
    e.preventDefault();
    e.stopPropagation();
    dragTarget.current = target;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!dragTarget.current) return;
    const total = getTotal();
    const sec = (getPct(e) / 100) * total;
    if (dragTarget.current === "start") {
      const v = Math.max(0, Math.min(sec, (endSecRef.current ?? total) - 0.5));
      setStartSec(v);
    } else {
      const v = Math.max(startSecRef.current + 0.5, Math.min(sec, total));
      setEndSec(v);
    }
  };

  const handlePointerUp = () => {
    if (dragTarget.current && value && selectedTrack) {
      onChange(value, selectedTrack.url, startSecRef.current, endSecRef.current ?? undefined);
    }
    dragTarget.current = null;
  };

  const updateStart = (sec: number) => {
    const total = getTotal();
    const v = Math.max(0, Math.min(sec, (endSecRef.current ?? total) - 1));
    setStartSec(v);
    if (value && selectedTrack) onChange(value, selectedTrack.url, v, endSecRef.current ?? undefined);
  };

  const updateEnd = (sec: number) => {
    const v = Math.max(startSecRef.current + 1, Math.min(sec, getTotal()));
    setEndSec(v);
    if (value && selectedTrack) onChange(value, selectedTrack.url, startSecRef.current, v);
  };

  const total = getTotal();
  const startPct = (startSec / total) * 100;
  const endPct = ((endSec ?? total) / total) * 100;
  const currentPct = Math.min(100, (currentTime / total) * 100);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(
        `${(import.meta.env.VITE_API_BASE_URL ?? "/api")}/assets/music/upload`,
        { method: "POST", body: form, credentials: "include" }
      );
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail?.detail ?? `Upload failed (${res.status})`);
      }
      const json = await res.json();
      const track: Track = json.track;
      await refetch();
      onChange(track.id, track.url, 0, undefined);
      pushRecent({ id: track.id, title: track.title, url: track.url });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleRefetch = async () => {
    setRefetching(true);
    setError(null);
    try {
      const params = new URLSearchParams({ category });
      (tags ?? []).forEach((t) => params.append("tags", t));
      if (value) params.set("avoid_id", value);
      const res = await api.get(`/assets/music/refetch?${params}`);
      const track: Track = (res as { track: Track }).track;
      await refetch();
      onChange(track.id, track.url, 0, undefined);
      pushRecent({ id: track.id, title: track.title, url: track.url });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refetch failed");
    } finally {
      setRefetching(false);
    }
  };

  if (loading) return <p className="text-xs text-gray-500">Loading music…</p>;

  return (
    <div className="space-y-2">
      {/* Recent picks — quick re-select, last 7 */}
      {recent.length > 0 && (
        <div className="flex items-center gap-1 flex-wrap">
          <Clock size={10} className="shrink-0 text-gray-500" />
          {recent.map((r) => (
            <button
              key={r.id}
              type="button"
              title={r.title}
              onClick={() => quickSelect(r)}
              className={`max-w-[7rem] truncate text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                value === r.id
                  ? "bg-blue-600 border-blue-500 text-white"
                  : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500"
              }`}
            >
              {r.title}
            </button>
          ))}
        </div>
      )}

      {/* Custom dropdown */}
      <div ref={dropRef} className="relative">
        {/* Trigger — div[role=button] so play <button> inside is valid HTML */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => setOpen((o) => !o)}
          onKeyDown={(e) => e.key === "Enter" && setOpen((o) => !o)}
          className="w-full flex items-center gap-2 px-3 py-2 rounded bg-gray-800 border border-gray-700 text-xs text-left hover:border-gray-600 transition-colors cursor-pointer"
        >
          <Music size={11} className="shrink-0 text-gray-500" />
          <span className="flex-1 truncate text-gray-200">
            {selectedTrack?.title ?? "No track selected"}
          </span>
          {selectedTrack?.duration && !audioDuration && (
            <span className="shrink-0 text-gray-500">{selectedTrack.duration}s</span>
          )}
          {selectedTrack && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); togglePlay(selectedTrack); }}
              title={playingId === selectedTrack.id ? "Stop" : "Play"}
              className="shrink-0 text-gray-400 hover:text-white p-0.5"
            >
              {playingId === selectedTrack.id ? <Square size={12} /> : <Play size={12} />}
            </button>
          )}
          <ChevronDown
            size={11}
            className={`shrink-0 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
          />
        </div>

        {open && (
          <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-gray-800 border border-gray-700 rounded shadow-xl max-h-56 overflow-hidden flex flex-col">
            {/* Search + category filter */}
            <div className="sticky top-0 bg-gray-800 border-b border-gray-700 p-1.5 space-y-1.5">
              <div className="relative">
                <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none" />
                <input
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  onMouseDown={(e) => e.stopPropagation()}
                  onKeyDown={(e) => e.stopPropagation()}
                  placeholder="Search tracks…"
                  className="w-full pl-7 pr-2 py-1 bg-gray-900 border border-gray-700 rounded text-xs text-gray-200 focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div className="flex flex-wrap gap-1">
                {FILTER_CATEGORIES.map((c) => {
                  const on = categoryFilter.includes(c);
                  return (
                    <button
                      key={c}
                      type="button"
                      onClick={(e) => { e.stopPropagation(); toggleCategory(c); }}
                      className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                        on
                          ? "bg-blue-600 border-blue-500 text-white"
                          : "bg-gray-900 border-gray-700 text-gray-400 hover:border-gray-500"
                      }`}
                    >
                      {c.replace("_", " ")}
                    </button>
                  );
                })}
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setSharedOnly((v) => !v); }}
                  title="Tracks tagged to more than one category"
                  className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                    sharedOnly
                      ? "bg-purple-600 border-purple-500 text-white"
                      : "bg-gray-900 border-gray-700 text-gray-400 hover:border-gray-500"
                  }`}
                >
                  shared
                </button>
              </div>
            </div>
            <div className="overflow-y-auto">
            {tracks.length === 0 ? (
              <p className="px-3 py-2 text-xs text-gray-500">No tracks cached — use Re-fetch to download one</p>
            ) : filteredTracks.length === 0 ? (
              <p className="px-3 py-2 text-xs text-gray-500">No tracks match your filters</p>
            ) : (
              filteredTracks.map((t) => (
                <div
                  key={t.id}
                  className={`flex items-center gap-2 px-3 py-2 text-xs transition-colors ${
                    value === t.id ? "bg-blue-700 text-white" : "hover:bg-gray-700 text-gray-300"
                  }`}
                >
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); togglePlay(t); }}
                    title={playingId === t.id ? "Stop" : "Play"}
                    className="shrink-0 text-gray-400 hover:text-white"
                  >
                    {playingId === t.id ? <Square size={11} /> : <Play size={11} />}
                  </button>
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={() => selectTrack(t)}
                    onKeyDown={(e) => e.key === "Enter" && selectTrack(t)}
                    className="flex-1 truncate cursor-pointer"
                  >
                    {t.title}
                  </span>
                  {t.duration && <span className="shrink-0 text-gray-400">{t.duration}s</span>}
                  {t.shared ? (
                    <span className="text-xs px-1 rounded shrink-0 bg-purple-700 text-purple-100">shared</span>
                  ) : t.category && (
                    <span className="text-xs px-1 rounded shrink-0 bg-gray-600 text-gray-300">{t.category}</span>
                  )}
                </div>
              ))
            )}
            </div>
          </div>
        )}
      </div>

      {/* Seek + trim bar — shown whenever a track is selected */}
      {selectedTrack && (
        <div className="space-y-1">
          {/* Bar */}
          <div
            ref={trackBarRef}
            className="relative h-7 select-none cursor-pointer"
            onClick={handleBarClick}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
          >
            {/* Track background */}
            <div className="absolute top-2.5 inset-x-0 h-2 bg-gray-700 rounded-full pointer-events-none" />
            {/* Trim region */}
            <div
              className="absolute top-2.5 h-2 bg-blue-500/50 rounded pointer-events-none"
              style={{ left: `${startPct}%`, right: `${100 - endPct}%` }}
            />
            {/* Playhead */}
            <div
              className="absolute top-1 h-5 w-0.5 bg-white/80 pointer-events-none"
              style={{ left: `${currentPct}%`, transform: "translateX(-50%)" }}
            />
            {/* Start handle (green) */}
            <div
              className="absolute top-1 w-2 h-5 bg-green-400 rounded-sm cursor-ew-resize"
              style={{ left: `${startPct}%`, transform: "translateX(-50%)" }}
              onPointerDown={(e) => startDrag(e, "start")}
            />
            {/* End handle (red) */}
            <div
              className="absolute top-1 w-2 h-5 bg-red-400 rounded-sm cursor-ew-resize"
              style={{ left: `${endPct}%`, transform: "translateX(-50%)" }}
              onPointerDown={(e) => startDrag(e, "end")}
            />
          </div>

          {/* Time labels */}
          <div className="flex justify-between text-[10px] text-gray-500 px-0.5">
            <span>{fmtTime(currentTime)}</span>
            <span>{fmtTime(audioDuration || selectedTrack.duration || 0)}</span>
          </div>

          {/* Trim inputs */}
          <div className="flex items-center gap-1 flex-wrap text-xs">
            <span className="text-gray-500">Start</span>
            <input
              type="number"
              min={0}
              max={Math.max(0, (endSec ?? (audioDuration || (selectedTrack.duration ?? 999))) - 1)}
              step={1}
              value={Math.round(startSec)}
              onChange={(e) => updateStart(+e.target.value)}
              className="w-14 px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded text-center text-xs"
            />
            <span className="text-gray-500">s</span>
            <button
              type="button"
              onClick={() => updateStart(Math.floor(currentTime))}
              className="text-[10px] px-1.5 py-0.5 bg-gray-700 hover:bg-gray-600 rounded text-gray-300"
            >
              ◂ Mark
            </button>
            <span className="text-gray-500 ml-1">End</span>
            <input
              type="number"
              min={startSec + 1}
              max={audioDuration || (selectedTrack.duration ?? 999)}
              step={1}
              value={Math.round(endSec ?? (audioDuration || (selectedTrack.duration ?? 0)))}
              onChange={(e) => updateEnd(+e.target.value)}
              className="w-14 px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded text-center text-xs"
            />
            <span className="text-gray-500">s</span>
            <button
              type="button"
              onClick={() => updateEnd(Math.ceil(currentTime))}
              className="text-[10px] px-1.5 py-0.5 bg-gray-700 hover:bg-gray-600 rounded text-gray-300"
            >
              Mark ▸
            </button>
          </div>
        </div>
      )}

      {/* Actions row */}
      <div className="flex gap-2 flex-wrap">
        <button
          disabled={uploading}
          onClick={() => fileRef.current?.click()}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40"
        >
          <Upload size={11} />
          {uploading ? "Uploading…" : "Upload track"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".mp3,.m4a,.wav"
          className="hidden"
          onChange={handleUpload}
        />

        <button
          disabled={refetching}
          onClick={handleRefetch}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40"
        >
          <RefreshCw size={11} className={refetching ? "animate-spin" : ""} />
          {refetching ? "Fetching…" : "Re-fetch track"}
        </button>
      </div>

      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}
