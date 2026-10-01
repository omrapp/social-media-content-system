import { useEffect, useRef, useState } from "react";
import { X, Play, Pause, Scissors, Loader2, AlertTriangle, Repeat, ZoomIn, Minus, Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { Track } from "@/types/audio";

// NOTE: wavesurfer.js is not installed yet (someone else runs `npm install wavesurfer.js`
// manually) — these two imports will fail module resolution until then. That's expected;
// see the report for details. API used below matches wavesurfer.js v7's documented
// Regions plugin usage (WaveSurfer.create({...}), ws.registerPlugin(RegionsPlugin.create())).
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.esm.js";

const MEDIA_ORIGIN = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/api\/?$/, "");
const audioSrc = (url: string | null) => (url ? (url.startsWith("http") ? url : `${MEDIA_ORIGIN}${url}`) : "");

const fmtTime = (sec: number) => {
  if (!Number.isFinite(sec)) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
};

interface Props {
  track: Track;
  onClose: () => void;
  onSaved: (track: Track) => void;
}

// Minimal shape of the region object the Regions plugin gives us back —
// avoids depending on wavesurfer's own types before the package is installed.
// `setOptions` is the real wavesurfer v7 Regions API for moving a region
// programmatically (e.g. from a typed numeric input, not just drag).
interface WsRegion {
  start: number;
  end: number;
  on: (event: string, cb: () => void) => void;
  setOptions: (opts: { start?: number; end?: number }) => void;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function WaveformTrimModal({ track, onClose, onSaved }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const regionRef = useRef<WsRegion | null>(null);
  const loopRef = useRef(false);
  const boundsRef = useRef({ start: 0, end: 0 });

  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(0);
  const [loop, setLoop] = useState(false);
  const [zoom, setZoom] = useState(50);
  const [fadeIn, setFadeIn] = useState(0);
  const [fadeOut, setFadeOut] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    boundsRef.current = { start, end };
  }, [start, end]);

  useEffect(() => {
    loopRef.current = loop;
  }, [loop]);

  useEffect(() => {
    if (!containerRef.current) return;

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: "#4b5563",
      progressColor: "#6366f1",
      cursorColor: "#e5e7eb",
      height: 72,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      url: audioSrc(track.url),
    });
    wsRef.current = ws;

    const regions = ws.registerPlugin(RegionsPlugin.create());

    ws.on("ready", () => {
      const dur = ws.getDuration();
      setDuration(dur);
      setReady(true);
      const region = regions.addRegion({
        start: 0,
        end: dur,
        color: "rgba(99,102,241,0.25)",
        drag: true,
        resize: true,
      }) as unknown as WsRegion;
      regionRef.current = region;
      setStart(region.start);
      setEnd(region.end);
      region.on("update-end", () => {
        setStart(regionRef.current?.start ?? 0);
        setEnd(regionRef.current?.end ?? dur);
      });
    });

    ws.on("play", () => setPlaying(true));
    ws.on("pause", () => setPlaying(false));
    ws.on("finish", () => setPlaying(false));
    ws.on("error", () => setLoadError("Could not load audio for this track"));
    // Fires continuously during playback (v7) — used to loop the selection
    // and to stop playback once it runs past the selected end.
    ws.on("audioprocess", (time: number) => {
      const { start: s, end: e } = boundsRef.current;
      if (time >= e) {
        if (loopRef.current) {
          ws.setTime(s);
        } else {
          ws.pause();
        }
      }
    });

    return () => {
      ws.destroy();
      wsRef.current = null;
      regionRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track.id]);

  const togglePlay = () => wsRef.current?.playPause();

  const applyRegion = (next: { start?: number; end?: number }) => {
    if (!regionRef.current) return;
    regionRef.current.setOptions(next);
    if (next.start !== undefined) setStart(next.start);
    if (next.end !== undefined) setEnd(next.end);
  };

  const setStartValue = (v: number) => applyRegion({ start: clamp(v, 0, end - 0.1) });
  const setEndValue = (v: number) => applyRegion({ end: clamp(v, start + 0.1, duration) });

  const onZoomChange = (v: number) => {
    setZoom(v);
    wsRef.current?.zoom(v);
  };

  const saveTrim = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const newTrack = await api.post<Track>(`/audio/${track.id}/trim`, {
        start_s: start,
        end_s: end,
        fade_in_s: fadeIn,
        fade_out_s: fadeOut,
      });
      onSaved(newTrack);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Trim failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.6)" }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-2xl p-5 space-y-4"
        style={{
          background: "linear-gradient(145deg, rgba(17,19,31,1) 0%, rgba(10,10,16,1) 100%)",
          border: "1px solid rgba(255,255,255,0.08)",
          boxShadow: "0 4px 32px rgba(0,0,0,0.5)",
        }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <Scissors size={14} className="text-indigo-400 shrink-0" />
            <span className="text-sm font-semibold text-white truncate" title={track.title}>
              Trim — {track.title}
            </span>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-gray-500 hover:text-gray-200 hover:bg-white/[0.06] transition-colors">
            <X size={16} />
          </button>
        </div>

        <div
          ref={containerRef}
          className="rounded-xl overflow-hidden"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", minHeight: 72 }}
        />

        {loadError && (
          <div className="flex items-center gap-2 text-xs text-red-400">
            <AlertTriangle size={13} /> {loadError}
          </div>
        )}

        <div className="flex items-center justify-between text-xs text-gray-500">
          <div className="flex items-center gap-2">
            <button
              onClick={togglePlay}
              disabled={!ready}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-gray-300 disabled:opacity-40 cursor-pointer transition-colors hover:bg-white/[0.06]"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
            >
              {playing ? <Pause size={12} /> : <Play size={12} />}
              {playing ? "Pause" : "Play"}
            </button>
            <button
              onClick={() => setLoop((v) => !v)}
              disabled={!ready}
              title="Loop selection"
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition-colors disabled:opacity-40 ${
                loop ? "text-indigo-300" : "text-gray-400 hover:text-gray-200"
              }`}
              style={{
                background: loop ? "rgba(99,102,241,0.15)" : "rgba(255,255,255,0.04)",
                border: loop ? "1px solid rgba(99,102,241,0.3)" : "1px solid rgba(255,255,255,0.08)",
              }}
            >
              <Repeat size={12} /> Loop selection
            </button>
          </div>
          <span className="tabular-nums font-mono">
            {fmtTime(start)} – {fmtTime(end)} <span className="text-gray-700">/ {fmtTime(duration)}</span>
          </span>
        </div>

        {/* Numeric start/end inputs with nudge buttons */}
        <div className="flex items-center gap-3 flex-wrap text-xs">
          <div className="flex items-center gap-1">
            <span className="text-gray-500">Start</span>
            <button
              onClick={() => setStartValue(start - 0.1)}
              disabled={!ready}
              className="p-1 rounded text-gray-400 hover:text-gray-200 disabled:opacity-40 cursor-pointer"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
              title="-0.1s"
            >
              <Minus size={10} />
            </button>
            <input
              type="number"
              step={0.1}
              min={0}
              max={Math.max(0, end - 0.1)}
              value={start.toFixed(1)}
              onChange={(e) => setStartValue(+e.target.value)}
              disabled={!ready}
              className="w-16 px-1.5 py-1 rounded text-center tabular-nums disabled:opacity-40"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#e5e7eb" }}
            />
            <button
              onClick={() => setStartValue(start + 0.1)}
              disabled={!ready}
              className="p-1 rounded text-gray-400 hover:text-gray-200 disabled:opacity-40 cursor-pointer"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
              title="+0.1s"
            >
              <Plus size={10} />
            </button>
          </div>

          <div className="flex items-center gap-1">
            <span className="text-gray-500">End</span>
            <button
              onClick={() => setEndValue(end - 0.1)}
              disabled={!ready}
              className="p-1 rounded text-gray-400 hover:text-gray-200 disabled:opacity-40 cursor-pointer"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
              title="-0.1s"
            >
              <Minus size={10} />
            </button>
            <input
              type="number"
              step={0.1}
              min={start + 0.1}
              max={duration}
              value={end.toFixed(1)}
              onChange={(e) => setEndValue(+e.target.value)}
              disabled={!ready}
              className="w-16 px-1.5 py-1 rounded text-center tabular-nums disabled:opacity-40"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#e5e7eb" }}
            />
            <button
              onClick={() => setEndValue(end + 0.1)}
              disabled={!ready}
              className="p-1 rounded text-gray-400 hover:text-gray-200 disabled:opacity-40 cursor-pointer"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
              title="+0.1s"
            >
              <Plus size={10} />
            </button>
          </div>
        </div>

        {/* Zoom */}
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <ZoomIn size={12} className="shrink-0" />
          <input
            type="range"
            min={10}
            max={200}
            step={1}
            value={zoom}
            onChange={(e) => onZoomChange(+e.target.value)}
            disabled={!ready}
            className="flex-1 cursor-pointer disabled:opacity-40"
          />
        </div>

        {/* Fade in/out */}
        <div className="flex items-center gap-4 flex-wrap text-xs text-gray-500">
          <div className="flex items-center gap-1.5">
            <span>Fade in</span>
            <input
              type="number"
              step={0.5}
              min={0}
              max={5}
              value={fadeIn}
              onChange={(e) => setFadeIn(clamp(+e.target.value, 0, 5))}
              className="w-14 px-1.5 py-1 rounded text-center tabular-nums"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#e5e7eb" }}
            />
            <span>s</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span>Fade out</span>
            <input
              type="number"
              step={0.5}
              min={0}
              max={5}
              value={fadeOut}
              onChange={(e) => setFadeOut(clamp(+e.target.value, 0, 5))}
              className="w-14 px-1.5 py-1 rounded text-center tabular-nums"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#e5e7eb" }}
            />
            <span>s</span>
          </div>
        </div>

        {saveError && <p className="text-xs text-red-400">{saveError}</p>}

        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            onClick={onClose}
            className="px-3 py-2 text-xs font-medium rounded-xl cursor-pointer transition-colors text-gray-400 hover:text-gray-200"
          >
            Cancel
          </button>
          <button
            onClick={() => void saveTrim()}
            disabled={!ready || saving}
            className="flex items-center gap-2 px-4 py-2 text-xs font-medium rounded-xl cursor-pointer transition-all disabled:opacity-40"
            style={{ background: "rgba(99,102,241,0.18)", border: "1px solid rgba(99,102,241,0.35)", color: "#c7d2fe" }}
          >
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Scissors size={13} />}
            Save as new track
          </button>
        </div>
      </div>
    </div>
  );
}
