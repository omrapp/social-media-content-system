/**
 * Remotion composition driven directly by the EDL.
 *
 * This is a PREVIEW, not the renderer. It approximates the FFmpeg output well
 * enough to edit against; the exported reel is always produced by
 * merge_clips.render(). Known, deliberate gaps:
 *   - transitions are approximated by family (dissolve / wipe / slide / circle /
 *     fade-through-colour), not by xfade's exact easing.
 *   - the OpenMontage film grade (reel.grade.profile) is not previewed — only
 *     `eq` and the LUT are, via the WebGL shader in ColorVideo.
 *   - the music bed plays at its EDL volume but without the export's fades.
 *
 * Timing DOES match the export: each cut starts `duration - transition` after
 * the previous one, which is the same accounting reelDuration() uses, so the
 * player's length equals the exported reel's length.
 */

import { useMemo } from "react";
import {
  AbsoluteFill,
  Html5Audio,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  useCurrentFrame,
} from "remotion";

import { API_ORIGIN } from "@/lib/api";
import { ColorVideo, isIdentityEq, lutPreviewUrl } from "@/components/editor/ColorVideo";
import {
  cutDuration, type Cut, type EDL, type EqSpec, type ImageLayer, type ProxyMap,
  type TextLayer,
} from "@/types/editor";

/** Fade length for animation="fade" — must match editor_layers.FADE_S, or the
 *  preview and the burned-in text fade at different rates. */
const FADE_S = 0.3;

/** Fonts are served from the same directory the render reads them from, so a
 *  font that previews is a font that will burn in. */
function fontUrl(file: string): string {
  return `${API_ORIGIN}/static/assets/fonts/${encodeURIComponent(file)}`;
}

function fontFamilyFor(file: string): string {
  return file ? `edl-${file.replace(/[^a-zA-Z0-9]/g, "-")}` : "Georgia, serif";
}

/** ImageLayer.asset is ASSETS_DIR-relative (e.g. "stickers/pin.png") and the
 *  render resolves it under the same directory `/static/assets` serves, so a
 *  sticker that previews is a sticker that will composite. */
function assetUrl(asset: string): string {
  return `${API_ORIGIN}/static/assets/${asset.split("/").map(encodeURIComponent).join("/")}`;
}

export interface ReelCompositionProps {
  edl: EDL;
  proxies: ProxyMap;
  /** `editor.preview_lut` — off renders the plain proxy (eq still applies). */
  previewLut?: boolean;
}

/** Music lives under MUSIC_DIR; the picker hands back an already-served URL,
 *  while a hydrated EDL carries the MUSIC_DIR-relative path. Accept both. */
export function musicUrl(path: string | null): string | null {
  if (!path) return null;
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith("/")) return `${API_ORIGIN}${path}`;
  return `${API_ORIGIN}/static/assets/music/${path.split("/").map(encodeURIComponent).join("/")}`;
}

/** Style for the INCOMING cut during its `enter` window, approximating the
 *  xfade family the export will use. `t` runs 0→1 across the join. */
function enterStyle(name: string, t: number): React.CSSProperties {
  switch (name) {
    case "wipeleft":   return { clipPath: `inset(0 0 0 ${(1 - t) * 100}%)` };
    case "wiperight":  return { clipPath: `inset(0 ${(1 - t) * 100}% 0 0)` };
    case "wipeup":     return { clipPath: `inset(${(1 - t) * 100}% 0 0 0)` };
    case "wipedown":   return { clipPath: `inset(0 0 ${(1 - t) * 100}% 0)` };
    case "slideleft":  return { transform: `translateX(${(1 - t) * 100}%)` };
    case "slideright": return { transform: `translateX(${-(1 - t) * 100}%)` };
    case "slideup":    return { transform: `translateY(${(1 - t) * 100}%)` };
    case "slidedown":  return { transform: `translateY(${-(1 - t) * 100}%)` };
    case "smoothleft": return { clipPath: `inset(0 0 0 ${(1 - t) * 100}%)`, opacity: t };
    case "smoothright":return { clipPath: `inset(0 ${(1 - t) * 100}% 0 0)`, opacity: t };
    case "circleopen": return { clipPath: `circle(${t * 75}% at 50% 50%)` };
    case "circleclose":return { clipPath: `circle(${t * 75}% at 50% 50%)`, opacity: t };
    // fade / fadeblack / fadewhite / dissolve / pixelize all read as a
    // cross-dissolve at preview resolution.
    default:           return { opacity: t };
  }
}

/** Cut placement in composition frames. Exported so the timeline and the player
 *  agree on where the playhead sits inside a given cut. */
export interface PlacedCut {
  cut: Cut;
  index: number;
  /** Composition frame the cut becomes visible on. */
  fromFrame: number;
  durationInFrames: number;
  /** Frames of cross-dissolve at the head of this cut (the previous cut's
   *  transition). 0 for the first cut and for hard cuts. */
  enterFrames: number;
  /** xfade name of that incoming join, so the preview can match its family. */
  enterName: string;
}

export function placeCuts(cuts: Cut[], fps: number): PlacedCut[] {
  const placed: PlacedCut[] = [];
  let cursorS = 0;
  cuts.forEach((cut, index) => {
    const durS = cutDuration(cut);
    const prev = cuts[index - 1];
    const enterS = index === 0 ? 0 : (prev?.transition?.duration_s ?? 0);
    placed.push({
      cut,
      index,
      fromFrame: Math.round(cursorS * fps),
      durationInFrames: Math.max(1, Math.round(durS * fps)),
      enterFrames: Math.round(enterS * fps),
      enterName: index === 0 ? "fade" : (prev?.transition?.name ?? "fade"),
    });
    const outS = index === cuts.length - 1 ? 0 : (cut.transition?.duration_s ?? 0);
    cursorS += Math.max(0, durS - outS);
  });
  return placed;
}

function KenBurns({ spec, durationInFrames, children }: {
  spec: Cut["ken_burns"];
  durationInFrames: number;
  children: React.ReactNode;
}) {
  const frame = useCurrentFrame();
  if (!spec?.enabled) return <>{children}</>;

  // Mirrors the gentle zoompan push/pull the merge render applies: ~6% over the
  // segment, direction "in" = push.
  const [a, b] = spec.direction === "out" ? [1.06, 1.0] : [1.0, 1.06];
  const scale = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [a, b], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  // drift 1/3 = horizontal pan, 0/2 = centred (matches KenBurnsSpec.drift).
  const horizontal = spec.drift === 1 || spec.drift === 3;
  const shift = horizontal
    ? interpolate(frame, [0, Math.max(1, durationInFrames - 1)],
        spec.drift === 1 ? [-2, 2] : [2, -2],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 0;

  return (
    <AbsoluteFill style={{ transform: `scale(${scale}) translateX(${shift}%)` }}>
      {children}
    </AbsoluteFill>
  );
}

function CutFrame({ placed, src, muted, eq, lutUrl }: {
  placed: PlacedCut;
  src?: string;
  muted: boolean;
  eq: EqSpec;
  lutUrl: string | null;
}) {
  const frame = useCurrentFrame();
  const t = placed.enterFrames > 0
    ? interpolate(frame, [0, placed.enterFrames], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 1;
  const style = placed.enterFrames > 0 && t < 1 ? enterStyle(placed.enterName, t) : undefined;

  // <1.0 = slow motion. The merge render's slow-mo is duration-preserving
  // (setpts + trim), so the segment keeps its timeline length and simply
  // consumes less source — which is exactly what playbackRate does here.
  const rate = placed.cut.speed > 0 ? placed.cut.speed : 1;
  const graded = !isIdentityEq(eq) || Boolean(lutUrl);

  return (
    <AbsoluteFill style={style}>
      <KenBurns spec={placed.cut.ken_burns} durationInFrames={placed.durationInFrames}>
        {src ? (
          graded ? (
            <ColorVideo src={src} muted={muted} playbackRate={rate} eq={eq} lutUrl={lutUrl} />
          ) : (
            <OffthreadVideo
              src={src}
              muted={muted}
              playbackRate={rate}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          )
        ) : (
          <ProxyPending index={placed.index} />
        )}
      </KenBurns>
    </AbsoluteFill>
  );
}

/** Placeholder shown until the 480p proxy for this cut finishes encoding. */
function ProxyPending({ index }: { index: number }) {
  return (
    <AbsoluteFill
      style={{
        background: "linear-gradient(135deg,#111827,#1f2937)",
        alignItems: "center",
        justifyContent: "center",
        color: "#6b7280",
        fontSize: 48,
        fontFamily: "ui-sans-serif, system-ui",
      }}
    >
      Clip {index + 1} · preparing…
    </AbsoluteFill>
  );
}

/** One burned-in text layer. Geometry mirrors editor_layers._position_exprs:
 *  y always centres the box, x depends on the anchor. */
function TextLayerView({ layer, fps, totalFrames }: {
  layer: TextLayer;
  fps: number;
  totalFrames: number;
}) {
  const frame = useCurrentFrame();
  const t = frame / fps;
  const endS = layer.end_s > layer.start_s ? layer.end_s : totalFrames / fps;
  if (t < layer.start_s || t > endS) return null;

  const opacity = layer.animation === "fade"
    ? Math.max(0, Math.min(1, Math.min((t - layer.start_s) / FADE_S, (endS - t) / FADE_S)))
    : 1;

  const translateX = layer.anchor === "center" ? "-50%"
    : layer.anchor === "right" ? "-100%" : "0";

  return (
    <div
      style={{
        position: "absolute",
        left: `${layer.x * 100}%`,
        top: `${layer.y * 100}%`,
        transform: `translate(${translateX}, -50%)`,
        fontFamily: fontFamilyFor(layer.font),
        fontSize: layer.size,
        color: layer.color,
        opacity,
        whiteSpace: "pre",
        textShadow: "2px 2px 0 rgba(0,0,0,0.5)",
        lineHeight: 1.15,
      }}
    >
      {layer.content}
    </div>
  );
}

/** One image/sticker overlay layer.
 *
 *  Geometry mirrors the FFmpeg `overlay` the backend emits: x/y are NORMALIZED
 *  CENTRE coordinates, so the box is placed at (x%, y%) and pulled back by half
 *  its own size. w/h are fractions of the canvas; a null dimension is derived
 *  from the other one (aspect preserved), and both null means native size. */
function ImageLayerView({ layer, fps, totalFrames }: {
  layer: ImageLayer;
  fps: number;
  totalFrames: number;
}) {
  const frame = useCurrentFrame();
  const t = frame / fps;
  // Same "end_s <= start_s means hold to the end" rule as the text lane.
  const endS = layer.end_s > layer.start_s ? layer.end_s : totalFrames / fps;
  if (t < layer.start_s || t > endS) return null;

  return (
    <Img
      src={assetUrl(layer.asset)}
      style={{
        position: "absolute",
        left: `${layer.x * 100}%`,
        top: `${layer.y * 100}%`,
        transform: "translate(-50%, -50%)",
        width: layer.w !== null ? `${layer.w * 100}%` : "auto",
        height: layer.h !== null ? `${layer.h * 100}%` : "auto",
        opacity: Math.max(0, Math.min(1, layer.opacity)),
      }}
    />
  );
}

/** @font-face for every font the doc references, so the preview measures text
 *  with the same face the render will. */
function FontFaces({ fonts }: { fonts: string[] }) {
  if (fonts.length === 0) return null;
  const css = fonts
    .map((f) => `@font-face{font-family:'${fontFamilyFor(f)}';src:url('${fontUrl(f)}');font-display:block;}`)
    .join("\n");
  return <style>{css}</style>;
}

export function ReelComposition({ edl, proxies, previewLut = true }: ReelCompositionProps) {
  const placed = useMemo(() => placeCuts(edl.cuts, edl.canvas.fps), [edl.cuts, edl.canvas.fps]);
  const muted = edl.reel.audio_mode === "music";
  const totalFrames = placed.length
    ? placed[placed.length - 1].fromFrame + placed[placed.length - 1].durationInFrames
    : 0;
  const fonts = useMemo(
    () => [...new Set(edl.layers.text.map((l) => l.font).filter(Boolean))],
    [edl.layers.text],
  );
  // Sorted, not sliced in place — the doc's own order is the user's layer list.
  const images = useMemo(
    () => [...edl.layers.image].sort((a, b) => a.z - b.z),
    [edl.layers.image],
  );

  // A film grade baked in by merge_clips makes video_edit skip the LUT, so the
  // preview must skip it too or the editor would show a double grade.
  const lutUrl = useMemo(() => {
    if (!previewLut || !edl.reel.lut || edl.reel.grade.profile) return null;
    return lutPreviewUrl(API_ORIGIN, edl.reel.lut);
  }, [previewLut, edl.reel.lut, edl.reel.grade.profile]);

  const bed = musicUrl(edl.reel.audio_mode === "music" ? edl.reel.music.path : null);

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {placed.map((p) => (
        <Sequence
          key={p.cut.id}
          from={p.fromFrame}
          durationInFrames={p.durationInFrames}
          // Overlapping sequences are what makes the cross-dissolve visible;
          // without this the incoming cut would be clipped to its own layer.
          layout="none"
        >
          <CutFrame placed={p} src={proxies[p.cut.id]} muted={muted}
                    eq={edl.reel.eq} lutUrl={lutUrl} />
        </Sequence>
      ))}

      {bed && (
        // trimBefore mirrors the export's `-ss <enter_offset_s>` on the bed. The
        // export's afade in/out is not reproduced — it would only mislead about
        // where the track actually sits.
        <Html5Audio
          src={bed}
          volume={Math.max(0, Math.min(2, edl.reel.music.volume))}
          trimBefore={Math.round((edl.reel.music.start_offset_s ?? 0) * edl.canvas.fps)}
        />
      )}

      <FontFaces fonts={fonts} />
      {edl.layers.text.map((layer) => (
        <TextLayerView key={layer.id} layer={layer} fps={edl.canvas.fps} totalFrames={totalFrames} />
      ))}

      {/* Images composite AFTER text, matching the order video_edit chains its
          overlay filters: a sticker placed over a caption covers it in the
          export, so it must cover it here too. Sorted by z ascending, which is
          the order compile() emits them in. */}
      {images.map((layer) => (
        <ImageLayerView key={layer.id} layer={layer} fps={edl.canvas.fps} totalFrames={totalFrames} />
      ))}
    </AbsoluteFill>
  );
}
