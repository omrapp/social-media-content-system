/**
 * EDL v1 — TypeScript mirror of `backend/pipeline/editor_edl.py`.
 *
 * This file is the contract between the editor UI and the render pipeline.
 * The backend pydantic models are AUTHORITATIVE: if a field is added, renamed
 * or re-clamped there, change it here in the same commit. A silent divergence
 * does not throw — `PUT /api/editor/{id}` simply rejects the doc, or worse,
 * coerces it and the exported reel differs from what the preview showed.
 *
 * Coordinates (x/y/w/h) are NORMALIZED 0–1 so the browser preview and the
 * FFmpeg render agree without a scale factor.
 *
 * Phases 3–5 extend this file rather than inventing parallel types:
 *   Phase 3 (text overlays)  -> TextLayer
 *   Phase 4 (colour + audio) -> GradeSpec, EqSpec, MusicSpec, Cut.speed,
 *                               Cut.transition
 *   Phase 5 (extras)         -> ImageLayer, ScreenSpec
 */

// ── Limits (mirror editor_edl.py; enforce client-side so the UI can't build a
// doc the backend will reject) ───────────────────────────────────────────────
export const EDL_VERSION = 1;
export const MIN_CUT_S = 0.2;
export const MAX_CUT_S = 30.0;
export const MAX_TOTAL_S = 180.0;
export const MIN_JOIN_S = 0.02; // ~1 frame at 30fps (hard cut)
export const MAX_JOIN_S = 1.5;
export const MAX_TEXT_CHARS = 500;

/** Transition names accepted by FFmpeg xfade; anything else is coerced to "fade". */
export const XFADE_TRANSITIONS = [
  "fade", "fadeblack", "fadewhite", "dissolve", "wipeleft", "wiperight",
  "wipeup", "wipedown", "slideleft", "slideright", "slideup", "slidedown",
  "smoothleft", "smoothright", "circleopen", "circleclose", "pixelize",
] as const;
export type TransitionName = (typeof XFADE_TRANSITIONS)[number];

/** OpenMontage film-grade profiles (mirrors merge_clips._GRADE_PROFILES). An
 *  unknown name is REJECTED by compile(), not coerced — keep this in sync. */
export const GRADE_PROFILES = [
  "cinematic_warm", "cinematic_cool", "moody_dark", "bright_clean",
  "vintage_film", "high_contrast", "neutral", "teal_orange", "golden_hour",
  "vivid_pop",
] as const;

// ── Core ─────────────────────────────────────────────────────────────────────

export interface Canvas {
  w: number; // 1080
  h: number; // 1920
  fps: number; // 30
}

export interface KenBurnsSpec {
  enabled: boolean;
  direction: "in" | "out";
  /** 1/3 = horizontal drift, 0/2 = centered. */
  drift: number;
}

export interface TransitionSpec {
  name: string;
  /** Applies to the join with the NEXT cut; ignored on the last cut. */
  duration_s: number;
}

export interface Cut {
  id: string;
  src_media_id: string;
  in_s: number;
  out_s: number;
  /** <1.0 = slow motion. Speed-up is rejected by the backend: it shortens the
   *  segment and every xfade offset is computed from probed durations. */
  speed: number;
  smooth_slowmo: boolean;
  ken_burns: KenBurnsSpec;
  transition: TransitionSpec;
}

// ── Reel-level look ──────────────────────────────────────────────────────────

export interface GradeSpec {
  /** "" = no film grade, which leaves the downstream LUT in play. */
  profile: string;
  deband: boolean;
  grain: boolean;
  vignette: boolean;
}

export interface EqSpec {
  /** FFmpeg `eq` semantics, NOT CSS: brightness is ADDITIVE in [-1,1] while CSS
   *  brightness() is multiplicative. The preview shader must use this formula. */
  brightness: number;
  contrast: number;
  saturation: number;
}

export interface MusicSpec {
  /** MUSIC_DIR-relative; the backend validates containment. */
  path: string | null;
  volume: number;
  fade_s: number;
  /** null = let the backend detect the track's first strong onset. */
  start_offset_s: number | null;
  /** Bed level while narration plays; null = the global
   *  `voiceover.music_duck_volume` setting. */
  duck_volume: number | null;
}

export interface ScreenSpec {
  enabled: boolean;
}

export interface Reel {
  grade: GradeSpec;
  /** LUTS_DIR-relative .cube; handed to video_edit, not to the merge render. */
  lut: string | null;
  eq: EqSpec;
  audio_mode: "music" | "original";
  music: MusicSpec;
  voiceover: boolean;
  branding: boolean;
  intro: ScreenSpec;
  cast: ScreenSpec;
  loop_friendly: boolean;
}

// ── Layers (rendered by video_edit, not by the merge render) ──────────────────

export interface TextLayer {
  id: string;
  content: string;
  /** Bare filename under FONTS_DIR; "" = default. */
  font: string;
  size: number;
  /** Must match /^#[0-9a-fA-F]{6}$/. */
  color: string;
  x: number;
  y: number;
  anchor: "left" | "center" | "right";
  start_s: number;
  end_s: number;
  animation: "none" | "fade";
}

export interface ImageLayer {
  id: string;
  /** ASSETS_DIR-relative; .png or .webp only. */
  asset: string;
  x: number;
  y: number;
  /** null = preserve aspect ratio from the other dimension. */
  w: number | null;
  h: number | null;
  start_s: number;
  end_s: number;
  opacity: number;
  /** Composite order, ascending. */
  z: number;
}

export interface Layers {
  text: TextLayer[];
  image: ImageLayer[];
}

// ── Document ─────────────────────────────────────────────────────────────────

export interface EDL {
  edl_version: number;
  source_media_id: string;
  /** True when hydrated from a pre-2.0.0 reel that has no persisted plan:
   *  per-cut slow-mo, Ken Burns, cleanup, join durations and music offset were
   *  never recorded, so exporting produces a close but NOT identical reel.
   *  Surface this in the UI — it is not a detail. */
  approx: boolean;
  canvas: Canvas;
  cuts: Cut[];
  reel: Reel;
  layers: Layers;
}

// ── API shapes ───────────────────────────────────────────────────────────────

export interface EditorDocResponse {
  media_id: string;
  edl: EDL;
  approx: boolean;
  /** 0 when the doc was hydrated rather than loaded from a saved version. */
  version: number;
  project_id: string | null;
  saved_at: string | null;
}

/** PUT /api/editor/{id} — note it returns the saved metadata, NOT the doc. */
export interface EditorSaveResponse {
  media_id: string;
  project_id: string;
  version: number;
  approx: boolean;
}

export interface EditorVersion {
  id: string;
  version: number;
  label: string | null;
  approx: boolean;
  created_at: string;
}

export interface EditorVersionsResponse {
  media_id: string;
  versions: EditorVersion[];
}

/** GET /api/editor/{id}/versions/{version} — one historical doc.
 *  Loading one is an EDIT, not a rollback: the doc replaces the working copy and
 *  the user still has to save, which mints a NEW version rather than rewinding
 *  history. Same for `GET /api/editor/{id}?fresh=1` (revert to original), which
 *  returns an `EditorDocResponse` re-hydrated from how the reel actually
 *  rendered, ignoring every saved version. */
export interface EditorVersionDocResponse {
  media_id: string;
  version: number;
  label: string | null;
  approx: boolean;
  created_at: string;
  edl: EDL;
}

/** GET /api/assets/stickers — image/sticker assets available to ImageLayer.
 *  `assets/stickers/` ships EMPTY: there is no built-in set, so the picker's
 *  empty state has to point at the upload button rather than look broken. */
export interface StickerAsset {
  id: string;
  name: string;
  /** Bare filename under assets/stickers/. */
  file: string;
  /** ASSETS_DIR-relative path — this, not `url`, is what ImageLayer.asset holds;
   *  the backend re-resolves it under ASSETS_DIR at compile time. */
  asset: string;
  /** `/static/assets/stickers/<file>` — join to API_ORIGIN before use. */
  url: string;
}

export interface StickerListResponse {
  stickers: StickerAsset[];
}

/** POST /api/assets/stickers/upload — multipart `file`, .png/.webp, 10 MB cap. */
export interface StickerUploadResponse {
  item: StickerAsset;
}

export interface SaveEDLRequest {
  edl: EDL;
  label?: string | null;
}

export interface ProxyStartResponse {
  media_id: string;
  status: "started" | "no_cuts";
  cuts?: number;
  proxies?: Record<string, string>;
}

/** cut id -> signed, Range-capable proxy URL. Never build these by hand; the
 *  backend signs them with a short-lived HMAC. */
export type ProxyMap = Record<string, string>;

export interface ExportStartResponse {
  media_id: string;
  status: string;
  merge_id?: string;
}

// ── Derived helpers ──────────────────────────────────────────────────────────

export function cutDuration(cut: Cut): number {
  return Math.max(0, cut.out_s - cut.in_s);
}

/** Rendered length: cut durations minus the xfade overlaps that join them.
 *  Mirrors the merge render's own accounting, so the timeline's total matches
 *  the exported reel rather than over-reporting by the sum of the joins. */
export function reelDuration(cuts: Cut[]): number {
  if (cuts.length === 0) return 0;
  const body = cuts.reduce((t, c) => t + cutDuration(c), 0);
  const overlap = cuts
    .slice(0, -1)
    .reduce((t, c) => t + (c.transition?.duration_s ?? 0), 0);
  return Math.max(0, body - overlap);
}
