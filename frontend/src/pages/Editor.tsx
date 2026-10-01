/**
 * /editor/:mediaId — CapCut-style reel editor shell (v2.0.0 Phase 2).
 *
 * Thin orchestrator over useEditor, matching the Preview page's container-hook
 * split: no fetching, no mutation logic here — only layout, the player wiring
 * and the keyboard map.
 *
 * Lazy-loaded from App.tsx: @remotion/player is ~400 kB and must not land in
 * the main bundle for the 95% of sessions that never open the editor.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Player, type PlayerRef } from "@remotion/player";
import { Loader2, MonitorSmartphone } from "lucide-react";

import { API_ORIGIN } from "@/lib/api";
import { useEditor } from "@/hooks/useEditor";
import { useSettings } from "@/lib/settings";
import { AudioPanel } from "@/components/editor/AudioPanel";
import { ColorPanel } from "@/components/editor/ColorPanel";
import { ExportBar } from "@/components/editor/ExportBar";
import { ImageLayerPanel } from "@/components/editor/ImageLayerPanel";
import { PropertyPanel } from "@/components/editor/PropertyPanel";
import { TextLayerPanel } from "@/components/editor/TextLayerPanel";
import { Timeline, MAX_PX_PER_S, MIN_PX_PER_S } from "@/components/editor/Timeline";
import { ReelComposition, placeCuts } from "@/components/editor/ReelComposition";
import type { Cut, ProxyMap } from "@/types/editor";

const DEFAULT_PX_PER_S = 60;

/** Editing needs the timeline, the player and the inspector side by side; below
 *  this the layout stops being usable rather than merely cramped. */
const MIN_EDITOR_WIDTH = 1024;

function useIsNarrow() {
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && window.innerWidth < MIN_EDITOR_WIDTH,
  );
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MIN_EDITOR_WIDTH - 1}px)`);
    const onChange = (e: MediaQueryListEvent) => setNarrow(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return narrow;
}

export function EditorPage() {
  const { mediaId } = useParams<{ mediaId: string }>();
  const navigate = useNavigate();
  const narrow = useIsNarrow();
  const ed = useEditor(mediaId);

  const playerRef = useRef<PlayerRef | null>(null);
  const [frame, setFrame] = useState(0);
  const [pxPerSecond, setPxPerSecond] = useState(DEFAULT_PX_PER_S);
  // Five tabs at text-[11px] inside the w-72 aside: 288 − 24 (p-3) − 16 (gaps)
  // = 248 px, ~49 px each, which fits "colour" with room to spare.
  const [inspectorTab, setInspectorTab] =
    useState<"clip" | "text" | "image" | "colour" | "audio">("clip");

  const { data: settingsData } = useSettings();
  const defaultDuck = Number(
    (settingsData?.settings?.voiceover as Record<string, unknown> | undefined)
      ?.music_duck_volume ?? 0.08,
  );

  const fps = ed.edl?.canvas.fps ?? 30;
  const durationInFrames = Math.max(1, Math.round(ed.totalDuration * fps));

  // Signed proxy URLs are built server-side with their own /api prefix, so they
  // are joined to the origin rather than to the API base.
  const proxies: ProxyMap = useMemo(() => {
    const out: ProxyMap = {};
    for (const [cutId, url] of Object.entries(ed.proxies)) {
      out[cutId] = url.startsWith("http") ? url : `${API_ORIGIN}${url}`;
    }
    return out;
  }, [ed.proxies]);

  // ── player clock ──────────────────────────────────────────────────────────
  useEffect(() => {
    const p = playerRef.current;
    if (!p) return;
    const onFrame = (e: { detail: { frame: number } }) => setFrame(e.detail.frame);
    p.addEventListener("frameupdate", onFrame);
    return () => p.removeEventListener("frameupdate", onFrame);
  }, [ed.edl]);

  const seekSeconds = useCallback((t: number) => {
    const f = Math.max(0, Math.min(durationInFrames - 1, Math.round(t * fps)));
    setFrame(f);
    playerRef.current?.seekTo(f);
  }, [durationInFrames, fps]);

  const selectedCut: Cut | null = useMemo(
    () => ed.edl?.cuts.find((c) => c.id === ed.selectedCutId) ?? null,
    [ed.edl, ed.selectedCutId],
  );
  const selectedIndex = useMemo(
    () => ed.edl?.cuts.findIndex((c) => c.id === ed.selectedCutId) ?? -1,
    [ed.edl, ed.selectedCutId],
  );

  /** Split a cut where the playhead currently sits.
   *
   *  The playhead is in rendered seconds; a cut's in/out are source seconds.
   *  Slow-mo in the merge render is duration-preserving (setpts + trim), so a
   *  segment's timeline length equals out_s − in_s and the mapping is 1:1.
   *  A playhead outside the cut is a no-op rather than a silent clamp. */
  const splitAtPlayhead = useCallback((cutId: string) => {
    if (!ed.edl) return;
    const placed = placeCuts(ed.edl.cuts, fps).find((p) => p.cut.id === cutId);
    if (!placed) return;
    const local = (frame - placed.fromFrame) / fps;
    if (local <= 0 || local >= placed.durationInFrames / fps) return;
    ed.splitCut(cutId, placed.cut.in_s + local);
  }, [ed, fps, frame]);

  const updateCut = useCallback((id: string, patch: Partial<Cut>) => {
    ed.commit((d) => {
      const i = d.cuts.findIndex((c) => c.id === id);
      if (i >= 0) d.cuts[i] = { ...d.cuts[i], ...patch };
    });
  }, [ed]);

  // ── keyboard map ──────────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      // Never steal keys from a field the user is typing in.
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;

      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) ed.redo(); else ed.undo();
        return;
      }
      if (meta) return;

      switch (e.key) {
        case " ":
          e.preventDefault();
          if (playerRef.current?.isPlaying()) playerRef.current.pause();
          else playerRef.current?.play();
          break;
        case "j": case "J":
          e.preventDefault(); seekSeconds(frame / fps - 1); break;
        case "k": case "K":
          e.preventDefault(); playerRef.current?.pause(); break;
        case "l": case "L":
          e.preventDefault(); playerRef.current?.play(); break;
        case "ArrowLeft":
          e.preventDefault(); seekSeconds((frame - 1) / fps); break;
        case "ArrowRight":
          e.preventDefault(); seekSeconds((frame + 1) / fps); break;
        case "s": case "S":
          if (ed.selectedCutId) { e.preventDefault(); splitAtPlayhead(ed.selectedCutId); }
          break;
        case "Delete": case "Backspace":
          if (ed.selectedCutId) { e.preventDefault(); ed.deleteCut(ed.selectedCutId); }
          break;
        case "+": case "=":
          e.preventDefault(); setPxPerSecond((z) => Math.min(MAX_PX_PER_S, z * 1.5)); break;
        case "-": case "_":
          e.preventDefault(); setPxPerSecond((z) => Math.max(MIN_PX_PER_S, z / 1.5)); break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ed, fps, frame, seekSeconds, splitAtPlayhead]);

  // ── warn before losing unsaved edits ──────────────────────────────────────
  useEffect(() => {
    if (!ed.dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [ed.dirty]);

  // Export replaces the reel the post points at, so the preview page is where
  // the result actually lives.
  useEffect(() => {
    if (ed.exportPhase !== "done") return;
    const t = setTimeout(() => navigate(`/preview/${mediaId}`), 1200);
    return () => clearTimeout(t);
  }, [ed.exportPhase, mediaId, navigate]);

  // ── render ────────────────────────────────────────────────────────────────
  if (narrow) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center p-6">
        <div className="max-w-sm text-center space-y-3">
          <MonitorSmartphone className="w-8 h-8 mx-auto text-gray-500" />
          <h2 className="text-sm font-semibold text-gray-200">Open the editor on desktop</h2>
          <p className="text-xs text-gray-500">
            The timeline needs a wider viewport than this one to be workable.
          </p>
          <Link to={`/preview/${mediaId}`} className="inline-block text-xs text-indigo-400 hover:underline">
            Back to preview
          </Link>
        </div>
      </div>
    );
  }

  if (ed.loading) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center text-gray-500">
        <Loader2 className="w-5 h-5 animate-spin" />
      </div>
    );
  }

  if (ed.error || !ed.edl) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <div className="max-w-md text-center space-y-2">
          <p className="text-sm text-rose-300">{ed.error ?? "This reel has no edit list."}</p>
          <button onClick={ed.refetch} className="text-xs text-indigo-400 hover:underline">
            Retry
          </button>
        </div>
      </div>
    );
  }

  const edl = ed.edl;

  return (
    <div className="p-4 space-y-4">
      <ExportBar
        mediaId={mediaId!}
        approx={ed.approx}
        dirty={ed.dirty}
        savedVersion={ed.savedVersion}
        totalDuration={ed.totalDuration}
        overLength={ed.overLength}
        canUndo={ed.canUndo}
        canRedo={ed.canRedo}
        proxyProgress={ed.proxyProgress}
        exportPhase={ed.exportPhase}
        exportMessage={ed.exportMessage}
        onUndo={ed.undo}
        onRedo={ed.redo}
        onSave={() => void ed.save()}
        onRebuildProxies={() => void ed.buildProxies()}
        onExport={() => void ed.startExport()}
        onLoadVersion={(v) => void ed.loadVersion(v)}
        onRevertToOriginal={() => void ed.revertToOriginal()}
      />

      <div className="flex gap-4 items-start">
        <div className="flex-1 min-w-0 flex justify-center">
          <div className="rounded-xl overflow-hidden ring-1 ring-white/10 bg-black">
            <Player
              ref={playerRef}
              component={ReelComposition}
              inputProps={{ edl, proxies, previewLut: ed.previewLut }}
              durationInFrames={durationInFrames}
              fps={fps}
              compositionWidth={edl.canvas.w}
              compositionHeight={edl.canvas.h}
              style={{ width: 270, height: 480 }}
              controls
              acknowledgeRemotionLicense
            />
          </div>
        </div>

        <aside className="w-72 shrink-0 rounded-xl bg-gray-900/60 ring-1 ring-white/10 p-3">
          <div className="flex gap-1 mb-3">
            {(["clip", "text", "image", "colour", "audio"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setInspectorTab(tab)}
                className={`flex-1 py-1 rounded text-[11px] capitalize ${
                  inspectorTab === tab
                    ? "bg-indigo-500/20 text-indigo-100 ring-1 ring-indigo-400/40"
                    : "text-gray-400 hover:bg-white/5"
                }`}
              >
                {tab}
              </button>
            ))}
          </div>

          {inspectorTab === "clip" ? (
            <PropertyPanel
              edl={edl}
              cut={selectedCut}
              index={selectedIndex}
              isLast={selectedIndex === edl.cuts.length - 1}
              onUpdateCut={updateCut}
              onUpdateReel={ed.updateReel}
            />
          ) : inspectorTab === "colour" ? (
            <ColorPanel reel={edl.reel} onUpdate={ed.updateReel} previewLut={ed.previewLut} />
          ) : inspectorTab === "audio" ? (
            <AudioPanel reel={edl.reel} onUpdate={ed.updateReel} defaultDuck={defaultDuck} />
          ) : inspectorTab === "image" ? (
            <ImageLayerPanel
              layers={edl.layers.image}
              selectedId={ed.selectedLayerId}
              totalDuration={ed.totalDuration}
              maxLayers={ed.maxImageLayers}
              onSelect={ed.setSelectedLayerId}
              onAdd={ed.addImageLayer}
              onUpdate={ed.updateImageLayer}
              onDelete={ed.deleteImageLayer}
            />
          ) : (
            <TextLayerPanel
              layers={edl.layers.text}
              selectedId={ed.selectedLayerId}
              totalDuration={ed.totalDuration}
              maxLayers={ed.maxTextLayers}
              onSelect={ed.setSelectedLayerId}
              onAdd={ed.addTextLayer}
              onUpdate={ed.updateTextLayer}
              onDelete={ed.deleteTextLayer}
            />
          )}
        </aside>
      </div>

      <Timeline
        edl={edl}
        proxies={proxies}
        currentTimeS={frame / fps}
        pxPerSecond={pxPerSecond}
        selectedCutId={ed.selectedCutId}
        selectedLayerId={ed.selectedLayerId}
        onSelectLayer={(id) => { ed.setSelectedLayerId(id); setInspectorTab("text"); }}
        onSelectImageLayer={(id) => { ed.setSelectedLayerId(id); setInspectorTab("image"); }}
        onZoom={setPxPerSecond}
        onSeek={seekSeconds}
        onSelect={ed.setSelectedCutId}
        onReorder={ed.reorderCuts}
        onTrim={ed.trimCut}
        onSplit={splitAtPlayhead}
        onDelete={ed.deleteCut}
        onDuplicate={ed.duplicateCut}
      />

      <p className="text-[10px] text-gray-600">
        Space play/pause · J/K/L shuttle · ←/→ frame · S split at playhead ·
        Del remove clip · ⌘Z undo · +/− zoom
      </p>
    </div>
  );
}

export default EditorPage;
