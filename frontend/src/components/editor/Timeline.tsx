/**
 * Editor timeline: ruler, video track, layer lanes, playhead, zoom.
 *
 * The timeline is laid out in RENDERED time (cut durations minus the xfade
 * overlaps), the same accounting reelDuration() and ReelComposition use, so a
 * cut's box on the ruler is the moment it is on screen in the player.
 */

import { useCallback, useMemo, useRef } from "react";
import { Image as ImageIcon, Music2, Type, ZoomIn, ZoomOut } from "lucide-react";

import { Playhead } from "./Playhead";
import { TrackVideo } from "./TrackVideo";
import { LayerRow, type LayerItem } from "./LayerRow";
import { placeCuts } from "./ReelComposition";
import { cutDuration, reelDuration, type EDL, type ProxyMap } from "@/types/editor";

const LABEL_W = 96;
const GAP = 8;
const OFFSET = LABEL_W + GAP;

export const MIN_PX_PER_S = 12;
export const MAX_PX_PER_S = 240;

/** Scrub snapping: within this many px of a cut boundary, land on it exactly. */
const SNAP_PX = 6;

export interface TimelineProps {
  edl: EDL;
  proxies: ProxyMap;
  currentTimeS: number;
  pxPerSecond: number;
  selectedCutId: string | null;
  /** One id across both layer lanes — the inspector tab says which lane owns it,
   *  which is why the two select callbacks are separate: each also switches the
   *  inspector to its own tab. */
  selectedLayerId?: string | null;
  onSelectLayer?: (id: string) => void;
  onSelectImageLayer?: (id: string) => void;
  onZoom: (pxPerSecond: number) => void;
  onSeek: (timeS: number) => void;
  onSelect: (id: string) => void;
  onReorder: (from: number, to: number) => void;
  onTrim: (id: string, inS: number, outS: number) => void;
  onSplit: (id: string) => void;
  onDelete: (id: string) => void;
  onDuplicate: (id: string) => void;
}

function tickStep(pxPerSecond: number): number {
  // Keep ticks ~60px apart whatever the zoom.
  for (const step of [0.5, 1, 2, 5, 10, 30, 60]) {
    if (step * pxPerSecond >= 60) return step;
  }
  return 60;
}

export function Timeline({
  edl, proxies, currentTimeS, pxPerSecond, selectedCutId, selectedLayerId,
  onSelectLayer, onSelectImageLayer,
  onZoom, onSeek, onSelect, onReorder, onTrim, onSplit, onDelete, onDuplicate,
}: TimelineProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const totalS = useMemo(() => reelDuration(edl.cuts), [edl.cuts]);
  const widthPx = Math.max(320, totalS * pxPerSecond);

  /** Cut start times in rendered seconds — the snap targets. */
  const boundaries = useMemo(() => {
    const placed = placeCuts(edl.cuts, edl.canvas.fps);
    const starts = placed.map((p) => p.fromFrame / edl.canvas.fps);
    return [...starts, totalS];
  }, [edl.cuts, edl.canvas.fps, totalS]);

  const seekSnapped = useCallback((t: number) => {
    const snapS = SNAP_PX / pxPerSecond;
    const hit = boundaries.find((b) => Math.abs(b - t) <= snapS);
    onSeek(Math.min(totalS, Math.max(0, hit ?? t)));
  }, [boundaries, onSeek, pxPerSecond, totalS]);

  const step = tickStep(pxPerSecond);
  const ticks = useMemo(() => {
    const out: number[] = [];
    for (let t = 0; t <= totalS + 1e-6; t += step) out.push(Number(t.toFixed(3)));
    return out;
  }, [step, totalS]);

  // end_s === 0 means "hold to the end of the reel" (same convention as
  // editor_layers._enable_expr), so the lane draws it that way too.
  const textItems: LayerItem[] = edl.layers.text.map((l) => ({
    id: l.id,
    label: l.content || "(empty)",
    start_s: l.start_s,
    end_s: l.end_s > l.start_s ? l.end_s : totalS,
  }));
  const imageItems: LayerItem[] = edl.layers.image.map((l) => ({
    id: l.id,
    label: l.asset.split("/").pop() ?? l.asset,
    start_s: l.start_s,
    // Same end_s === 0 convention as the text lane — without this a sticker that
    // holds to the end of the reel drew as a zero-width sliver.
    end_s: l.end_s > l.start_s ? l.end_s : totalS,
  }));
  const musicItems: LayerItem[] = edl.reel.audio_mode === "music" && edl.reel.music.path
    ? [{ id: "music", label: edl.reel.music.path.split("/").pop() ?? "music",
         start_s: 0, end_s: totalS }]
    : [];

  return (
    <div className="rounded-xl bg-gray-900/60 ring-1 ring-white/10 p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs text-gray-400">
          {edl.cuts.length} cuts · {totalS.toFixed(1)}s
          {edl.cuts.length > 0 && (
            <span className="text-gray-600">
              {" "}· avg {(edl.cuts.reduce((t, c) => t + cutDuration(c), 0) / edl.cuts.length).toFixed(1)}s
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => onZoom(Math.max(MIN_PX_PER_S, pxPerSecond / 1.5))}
            title="Zoom out (−)"
            className="p-1.5 rounded hover:bg-white/10 text-gray-400"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <span className="text-[10px] text-gray-500 w-14 text-center">
            {Math.round(pxPerSecond)} px/s
          </span>
          <button
            onClick={() => onZoom(Math.min(MAX_PX_PER_S, pxPerSecond * 1.5))}
            title="Zoom in (+)"
            className="p-1.5 rounded hover:bg-white/10 text-gray-400"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="overflow-x-auto overflow-y-hidden">
        <div className="relative" style={{ width: OFFSET + widthPx }}>
          {/* Ruler — click anywhere on it to scrub. */}
          <div
            className="relative h-6 mb-1 cursor-pointer"
            style={{ marginLeft: OFFSET, width: widthPx }}
            onPointerDown={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              seekSnapped((e.clientX - rect.left) / pxPerSecond);
            }}
          >
            {ticks.map((t) => (
              <div key={t} className="absolute top-0 bottom-0" style={{ left: t * pxPerSecond }}>
                <div className="w-px h-2 bg-white/20" />
                <div className="text-[9px] text-gray-500 -translate-x-1/2 pl-px">
                  {t >= 60 ? `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, "0")}` : `${t}s`}
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-start gap-2 mb-2">
            <div className="w-24 shrink-0 pt-5 text-[11px] text-gray-400">Video</div>
            <div style={{ width: widthPx }}>
              <TrackVideo
                cuts={edl.cuts}
                pxPerSecond={pxPerSecond}
                selectedCutId={selectedCutId}
                proxies={proxies}
                onSelect={onSelect}
                onReorder={onReorder}
                onTrim={onTrim}
                onSplit={onSplit}
                onDelete={onDelete}
                onDuplicate={onDuplicate}
              />
            </div>
          </div>

          <div className="space-y-1">
            <LayerRow
              icon={Music2} name="Music" items={musicItems}
              pxPerSecond={pxPerSecond} widthPx={widthPx}
              accent="bg-emerald-500/20 text-emerald-200 ring-emerald-400/30"
              emptyHint={edl.reel.audio_mode === "original" ? "original clip audio" : "auto-picked at export"}
            />
            <LayerRow
              icon={Type} name="Text" items={textItems}
              pxPerSecond={pxPerSecond} widthPx={widthPx}
              accent="bg-indigo-500/20 text-indigo-200 ring-indigo-400/30"
              emptyHint="add one from the Text panel"
              selectedId={selectedLayerId}
              onSelectItem={onSelectLayer}
            />
            <LayerRow
              icon={ImageIcon} name="Images" items={imageItems}
              pxPerSecond={pxPerSecond} widthPx={widthPx}
              accent="bg-violet-500/20 text-violet-200 ring-violet-400/30"
              emptyHint="add one from the Image panel"
              selectedId={selectedLayerId}
              onSelectItem={onSelectImageLayer}
            />
          </div>

          <Playhead
            timeS={currentTimeS}
            pxPerSecond={pxPerSecond}
            durationS={totalS}
            onSeek={seekSnapped}
            offsetPx={OFFSET}
          />
        </div>
      </div>
    </div>
  );
}
