"""
Reel Editor — EDL v1 schema + hydrate/compile (v2.0.0).

Two documents live here, and keeping them apart is the whole point:

  EDL v1   the user's persisted, versioned edit document (`edit_projects.doc`).
           Asset names are relative to ASSETS_DIR/MUSIC_DIR/FONTS_DIR/LUTS_DIR,
           coordinates are normalized 0-1 (so the browser preview and the FFmpeg
           render agree with no scale factor), FX are *intent*
           ("speed: 0.85", "ken_burns.enabled"), and overlay layers are present.

  PLAN v1  the per-export compile artifact consumed by `merge_clips.render(plan)`.
           Paths are absolute and validated, FX are resolved decisions, joins are
           authoritative, and layers are ABSENT — they ride downstream into
           `video_edit` (a text-only edit must not force a full re-merge).

`compile()` is the security boundary. Everything a user can type — transition
names, grade profiles, font/sticker/LUT/music paths, colors, layer counts,
durations — is validated or rejected here, before any string reaches a
filtergraph. It is also where the export's identity is minted: a NEW merge_id,
always, so exporting never mutates the parent reel.

PLAN v1 must stay JSON-serializable. In particular `metrics` never carries the
`hist` key: `merge_clips._window_metrics` returns it as a numpy ndarray and
`json.dumps` would raise. Every metric is coerced with `float()`.
"""

import logging
import re
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.config import ASSETS_DIR, FONTS_DIR, LUTS_DIR, MUSIC_DIR
from backend.db import get_media_by_id, get_setting

log = logging.getLogger(__name__)

EDL_VERSION = 1
PLAN_VERSION = 1

# Hard bounds that do NOT come from settings (settings caps are DoS knobs; these
# are correctness bounds the renderer itself relies on).
MIN_CUT_S = 0.2          # below this a segment is shorter than a few frames
MAX_CUT_S = 30.0         # a single "cut" longer than this is not a montage cut
MAX_TOTAL_S = 180.0      # total reel length ceiling (Reels/Shorts are far under)
MIN_JOIN_S = 0.02        # ~1 frame at 30fps (hard cut)
MAX_JOIN_S = 1.5
MAX_TEXT_CHARS = 500

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_STICKER_EXTS = {".png", ".webp"}

# The 12 FX booleans merge_clips records in metadata.merge.fx — mirrored here so
# an editor export writes the same shape a normal merge does.
_FX_FLAG_KEYS = (
    "slow_motion", "ken_burns", "transition_variety", "adaptive_fx",
    "smart_select", "color_match", "deband", "hard_cuts_on_beat",
    "smooth_slowmo", "deblock", "strong_denoise", "sharpen",
)


class EDLError(ValueError):
    """Raised when an EDL cannot be compiled into a render PLAN."""


def _editor_settings() -> dict:
    """`editor` settings group merged over the caps this module enforces. Kept
    local (like merge_clips._DEFAULTS) so the pipeline never imports the route
    layer."""
    stored = get_setting("editor") or {}
    return {
        "enabled": True, "proxy_height": 480, "proxy_ttl_days": 7,
        "autosave_seconds": 15, "keep_versions": 20,
        "max_text_layers": 20, "max_image_layers": 10, "max_cuts": 40,
        "export_mode": "overwrite", "preview_lut": True,
        **(stored if isinstance(stored, dict) else {}),
    }


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ══════════════════════════════════════════════════════════════════════════
# EDL v1 — the persisted user document
# ══════════════════════════════════════════════════════════════════════════

class Canvas(BaseModel):
    """Composition size. Fixed to merge_clips' 1080x1920@30 in v1 — the renderer
    hardcodes those, so compile() forces them rather than trusting the doc."""
    w: int = 1080
    h: int = 1920
    fps: int = 30


class KenBurnsSpec(BaseModel):
    enabled: bool = False
    direction: Literal["in", "out"] = "in"
    drift: int = Field(default=0, ge=0, le=3)   # 1/3 = horizontal drift, 0/2 = centered


class TransitionSpec(BaseModel):
    """The join AFTER this cut. The last cut's transition is ignored (n cuts ⇒
    n-1 joins)."""
    name: str = "fade"
    duration_s: float = Field(default=0.35, ge=MIN_JOIN_S, le=MAX_JOIN_S)


class Cut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    src_media_id: str = Field(..., min_length=1, max_length=128)
    in_s: float = Field(..., ge=0.0)
    out_s: float = Field(..., gt=0.0)
    # <1.0 = slow motion (duration-preserving setpts+trim, same as merge_clips).
    # Speed-UP is not supported in v1: it would shorten the segment and every
    # xfade offset downstream is computed from the probed duration.
    speed: float = Field(default=1.0, ge=0.3, le=1.0)
    smooth_slowmo: bool = False
    ken_burns: KenBurnsSpec = Field(default_factory=KenBurnsSpec)
    transition: TransitionSpec = Field(default_factory=TransitionSpec)


class GradeSpec(BaseModel):
    profile: str = ""            # "" = no film grade (LUT stays in play downstream)
    deband: bool = True
    grain: bool = False
    vignette: bool = False


class EqSpec(BaseModel):
    """FFmpeg `eq` semantics, NOT the CSS shorthand: brightness is ADDITIVE
    [-1,1], contrast/saturation are multiplicative. Applied downstream in
    video_edit, never in the merge render."""
    brightness: float = Field(default=0.0, ge=-1.0, le=1.0)
    contrast: float = Field(default=1.0, ge=0.0, le=3.0)
    saturation: float = Field(default=1.0, ge=0.0, le=3.0)


class MusicSpec(BaseModel):
    path: str | None = None      # MUSIC_DIR-relative; validated in compile()
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    fade_s: float = Field(default=1.0, ge=0.0, le=5.0)
    # None = let the renderer detect the track's first strong onset ("the drop").
    # compile() resolves it to an explicit number so export is deterministic.
    start_offset_s: float | None = Field(default=None, ge=0.0)
    # Bed level while narration plays. None = fall back to the global
    # `voiceover.music_duck_volume` setting (the pre-editor behaviour).
    duck_volume: float | None = Field(default=None, ge=0.0, le=1.0)


class ScreenSpec(BaseModel):
    enabled: bool = False


class Reel(BaseModel):
    grade: GradeSpec = Field(default_factory=GradeSpec)
    lut: str | None = None       # LUTS_DIR-relative .cube; handed to video_edit
    eq: EqSpec = Field(default_factory=EqSpec)
    audio_mode: Literal["music", "original"] = "music"
    music: MusicSpec = Field(default_factory=MusicSpec)
    voiceover: bool = False
    branding: bool = True
    intro: ScreenSpec = Field(default_factory=ScreenSpec)
    cast: ScreenSpec = Field(default_factory=ScreenSpec)
    loop_friendly: bool = False


class TextLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    # Rendered via drawtext `textfile=` (never `text=`), so ':  % \ ,' and
    # newlines are structurally harmless. The cap here is DoS/render cost.
    content: str = Field(..., max_length=MAX_TEXT_CHARS)
    font: str = ""               # bare filename under FONTS_DIR; "" = default
    size: int = Field(default=64, ge=8, le=400)
    color: str = "#ffffff"
    x: float = Field(default=0.5, ge=0.0, le=1.0)
    y: float = Field(default=0.5, ge=0.0, le=1.0)
    anchor: Literal["left", "center", "right"] = "center"
    start_s: float = Field(default=0.0, ge=0.0)
    end_s: float = Field(default=0.0, ge=0.0)
    animation: Literal["none", "fade"] = "fade"

    @field_validator("color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not _HEX_COLOR_RE.match(v or ""):
            raise ValueError("color must be #RRGGBB")
        return v


class ImageLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    asset: str = Field(..., min_length=1, max_length=256)   # ASSETS_DIR-relative
    x: float = Field(default=0.5, ge=0.0, le=1.0)
    y: float = Field(default=0.5, ge=0.0, le=1.0)
    w: float | None = Field(default=None, gt=0.0, le=1.0)
    h: float | None = Field(default=None, gt=0.0, le=1.0)
    start_s: float = Field(default=0.0, ge=0.0)
    end_s: float = Field(default=0.0, ge=0.0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z: int = Field(default=0, ge=0, le=99)


# Structural parse-time ceilings. These are NOT the product caps (those live in
# the `editor` settings group and are enforced by check_caps/compile) — they
# exist so a hostile PUT can't make pydantic materialize an unbounded document
# before any of our own validation runs.
HARD_MAX_CUTS = 200
HARD_MAX_TEXT_LAYERS = 200
HARD_MAX_IMAGE_LAYERS = 100


class Layers(BaseModel):
    text: list[TextLayer] = Field(default_factory=list, max_length=HARD_MAX_TEXT_LAYERS)
    image: list[ImageLayer] = Field(default_factory=list, max_length=HARD_MAX_IMAGE_LAYERS)


class EDL(BaseModel):
    """The persisted, versioned edit document."""
    model_config = ConfigDict(extra="forbid")

    edl_version: int = EDL_VERSION
    source_media_id: str = Field(..., min_length=1, max_length=128)
    # True when this doc was hydrated lossily from a legacy metadata.merge that
    # predates the persisted plan — the UI banners it, and export still works.
    approx: bool = False
    canvas: Canvas = Field(default_factory=Canvas)
    cuts: list[Cut] = Field(default_factory=list, max_length=HARD_MAX_CUTS)
    reel: Reel = Field(default_factory=Reel)
    layers: Layers = Field(default_factory=Layers)


def check_caps(edl: EDL) -> None:
    """Enforce the `editor` settings caps (cuts / text layers / image layers).

    Called by compile() and by the save route, so a document that could never be
    exported can't be persisted either. Raises EDLError."""
    cfg = _editor_settings()
    for label, count, key, default in (
        ("cuts", len(edl.cuts), "max_cuts", 40),
        ("text layers", len(edl.layers.text), "max_text_layers", 20),
        ("image layers", len(edl.layers.image), "max_image_layers", 10),
    ):
        cap = int(cfg.get(key, default))
        if count > cap:
            raise EDLError(f"too many {label}: {count} > editor.{key} ({cap})")


# ══════════════════════════════════════════════════════════════════════════
# PLAN v1 — the per-export compile artifact (merge_clips.render consumes this)
# ══════════════════════════════════════════════════════════════════════════

class PlanVideo(BaseModel):
    crf: int = 20
    preset: str = "medium"


class PlanJoin(BaseModel):
    name: str
    duration_s: float


class PlanJoinPolicy(BaseModel):
    """How the renderer should DERIVE joins when `timeline.joins` is null
    (origin="auto"). When joins are present they are authoritative and only
    `clamp_to_min_seg` still applies."""
    transition: str | None = None
    duration_s: float | None = None
    variety: bool | None = None
    hard_cuts_on_beat: bool | None = None
    clamp_to_min_seg: bool = True


class PlanTimeline(BaseModel):
    n_target: int
    loop_friendly: bool = False
    joins: list[PlanJoin] | None = None      # len == n-1 when non-null
    join_policy: PlanJoinPolicy = Field(default_factory=PlanJoinPolicy)


class PlanCleanup(BaseModel):
    """Resolved per-segment cleanup filter fragments (deblock/denoise before the
    crop, white-balance/sharpen after). NEVER derived from user input — copied
    from the parent reel's persisted plan or left empty."""
    pre: str = ""
    post: str = ""


class PlanSlowMotion(BaseModel):
    factor: float
    smooth: bool = False


class PlanKenBurns(BaseModel):
    direction: Literal["in", "out"]
    drift: int = 0


class PlanFx(BaseModel):
    slow_motion: PlanSlowMotion | None = None
    ken_burns: PlanKenBurns | None = None


class PlanCut(BaseModel):
    order: int
    src_media_id: str
    src_path: str
    src_duration_s: float
    start_s: float
    dur_s: float
    score: float = 0.0
    # cv2 aesthetic metrics, `hist` stripped and every value float()-coerced so
    # json.dumps(plan) cannot raise on a numpy ndarray.
    metrics: dict | None = None
    cleanup: PlanCleanup = Field(default_factory=PlanCleanup)
    fx: PlanFx = Field(default_factory=PlanFx)


class PlanAudioAuto(BaseModel):
    """Precomputed inputs for the renderer's auto music pick. Derived from the
    SOURCE ROWS, never from plan.cuts — a resolved source that produced no cut
    still contributes its category/tags/mood text (plan risk #1)."""
    category: str | None = None
    tags: list[str] | None = None
    mood_match: bool = True
    mood_captions: str = ""
    mood_tags: str = ""


class PlanAudio(BaseModel):
    mode: Literal["music", "original"] = "music"
    fade_s: float = 1.0
    # 1.0 = untouched (the auto path never sets anything else, so the renderer
    # emits the exact same filtergraph it did before the editor existed).
    volume: float = 1.0
    music_path: str | None = None       # absolute, already under MUSIC_DIR
    beat_track_path: str | None = None  # editor exports never re-derive beats
    enter_offset_s: float | None = None # explicit ⇒ deterministic export
    auto: PlanAudioAuto = Field(default_factory=PlanAudioAuto)


class PlanPersistInherit(BaseModel):
    category: str | None = None
    tags: list[str] | None = None


class PlanPersist(BaseModel):
    enabled: bool = True
    inherit: PlanPersistInherit = Field(default_factory=PlanPersistInherit)
    segments_per_clip: int = 1
    grade_name: str = ""
    fx_flags: dict = Field(default_factory=dict)
    edited_from: str | None = None      # parent media_id this export derives from


class Plan(BaseModel):
    """What `merge_clips.render(plan)` consumes. Must be JSON-serializable."""
    plan_version: int = PLAN_VERSION
    origin: Literal["auto", "editor"] = "editor"
    merge_id: str
    video: PlanVideo = Field(default_factory=PlanVideo)
    canvas: Canvas = Field(default_factory=Canvas)
    timeline: PlanTimeline
    cuts: list[PlanCut]
    grade: GradeSpec = Field(default_factory=GradeSpec)
    audio: PlanAudio = Field(default_factory=PlanAudio)
    persist: PlanPersist = Field(default_factory=PlanPersist)
    cleanup_segments: bool = True


class EditOverrides(BaseModel):
    """Everything the merge render does NOT own — composited downstream by
    `video_edit` in one encode (Phase 3/4). Returned as compile()'s second value
    so the two halves never leak into each other."""
    lut: str | None = None              # absolute .cube path under LUTS_DIR
    eq: EqSpec = Field(default_factory=EqSpec)
    branding: bool = True
    voiceover: bool = False
    # None ⇒ video_edit keeps using `voiceover.music_duck_volume`.
    music_duck_volume: float | None = None
    intro: ScreenSpec = Field(default_factory=ScreenSpec)
    cast: ScreenSpec = Field(default_factory=ScreenSpec)
    # Layers keep NORMALIZED coordinates (browser/render parity) and gain a
    # resolved absolute path for the one thing that must not be re-derived
    # downstream: the font / sticker file.
    text_layers: list[dict] = Field(default_factory=list)
    image_layers: list[dict] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════
# Path containment — the `resolve()` + `is_relative_to()` idiom from
# merge_clips._safe_music_path (:781-801), one helper per asset root.
# ══════════════════════════════════════════════════════════════════════════

def _safe_under(raw, root: Path, exts: set[str] | None = None,
                marker: str | None = None) -> str | None:
    """Accept a caller-supplied path only if it resolves INSIDE *root* (no
    absolute escapes, no `..` traversal), exists, and (when *exts* is given) has
    an allowed extension. Returns the absolute path, else None."""
    if not raw:
        return None
    s = str(raw)
    if marker and marker in s:      # a served URL (…/static/assets/x/<file>)
        s = s.split(marker, 1)[1]
    try:
        cand = Path(s)
        if not cand.is_absolute():
            cand = root / cand
        cand = cand.resolve()
        if not cand.is_relative_to(root.resolve()):
            return None
        if exts and cand.suffix.lower() not in exts:
            return None
        return str(cand) if cand.exists() else None
    except Exception:
        return None


def _safe_font(name: str) -> str | None:
    """Fonts must be a BARE filename inside FONTS_DIR — reject any separator or
    traversal outright rather than relying on containment alone."""
    if not name:
        return None
    if "/" in name or "\\" in name or ".." in name:
        return None
    return _safe_under(name, FONTS_DIR)


def _safe_sticker(rel: str) -> str | None:
    return _safe_under(rel, ASSETS_DIR, exts=_STICKER_EXTS,
                       marker="static/assets/")


def _safe_lut(rel: str) -> str | None:
    return _safe_under(rel, LUTS_DIR, exts={".cube"}, marker="assets/luts/")


def _clean_metrics(met) -> dict | None:
    """Drop `hist` (numpy ndarray → json.dumps raises) and coerce every value
    with float() so float32 leaks can't change a downstream '%.2f' string."""
    if not isinstance(met, dict):
        return None
    out: dict = {}
    for k, v in met.items():
        if k == "hist":
            continue
        if k == "bgr":
            try:
                out["bgr"] = [float(x) for x in v]
            except Exception:
                continue
            continue
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            continue
    return out or None


# ══════════════════════════════════════════════════════════════════════════
# hydrate — metadata.merge → EDL
# ══════════════════════════════════════════════════════════════════════════

def _resolve_music_by_name(basename: str | None) -> str | None:
    """`metadata.merge.music_path` stores a BASENAME only. Resolve it back to a
    MUSIC_DIR-relative path by searching the library. Ambiguous (same filename in
    two subdirs) or missing ⇒ None, and the EDL is marked approx."""
    if not basename:
        return None
    try:
        hits = [p for p in MUSIC_DIR.rglob(basename) if p.is_file()]
    except Exception:
        return None
    if len(hits) != 1:
        return None
    try:
        return str(hits[0].relative_to(MUSIC_DIR))
    except Exception:
        return None


def hydrate(media_row: dict) -> EDL:
    """Build an editable EDL from an existing media row.

    Preferred path: `metadata.merge.plan` (persisted by merge_clips.render from
    v2.0.0 on) — an exact round-trip, `approx=False`.

    Fallback path: the legacy `metadata.merge.cuts` spine. Per-cut slow-mo,
    Ken Burns enablement, cleanup, join durations, music offset/fade and
    grain/vignette were never recorded, so they are reconstructed from the
    CURRENT settings and the doc is marked `approx=True`.

    Single-clip (non-merge) rows synthesize a one-cut EDL spanning the whole
    clip, so the editor opens on any reel, not just montages.
    """
    from backend.pipeline import merge_clips as _mc

    media_id = media_row.get("id") or ""
    meta = media_row.get("metadata")
    if isinstance(meta, str):
        try:
            import json as _json
            meta = _json.loads(meta)
        except Exception:
            meta = {}
    merge = (meta or {}).get("merge") if isinstance(meta, dict) else None

    if isinstance(merge, dict) and isinstance(merge.get("plan"), dict):
        return _hydrate_from_plan(media_id, merge["plan"], merge)
    if isinstance(merge, dict) and merge.get("cuts"):
        return _hydrate_from_cuts(media_id, merge, _mc)
    return _hydrate_single(media_row)


def _hydrate_from_plan(media_id: str, plan: dict, merge: dict) -> EDL:
    """Exact round-trip from the trimmed plan merge_clips.render persists."""
    joins = plan.get("timeline", {}).get("joins") or []
    cuts: list[Cut] = []
    for i, c in enumerate(plan.get("cuts") or []):
        fx = c.get("fx") or {}
        slow = fx.get("slow_motion") or {}
        kb = fx.get("ken_burns") or {}
        join = joins[i] if i < len(joins) else (joins[-1] if joins else {})
        start = float(c.get("start_s", 0.0))
        cuts.append(Cut(
            id=f"c{i}",
            src_media_id=str(c.get("src_media_id") or ""),
            in_s=round(start, 3),
            out_s=round(start + float(c.get("dur_s", 0.0)), 3),
            speed=float(slow.get("factor", 1.0) or 1.0),
            smooth_slowmo=bool(slow.get("smooth")),
            ken_burns=KenBurnsSpec(enabled=bool(kb),
                                   direction=kb.get("direction", "in") if kb else "in",
                                   drift=int(kb.get("drift", 0)) if kb else 0),
            transition=TransitionSpec(
                name=str(join.get("name", "fade")),
                duration_s=_clamp(float(join.get("duration_s", 0.35)), MIN_JOIN_S, MAX_JOIN_S),
            ),
        ))
    grade = plan.get("grade") or {}
    audio = plan.get("audio") or {}
    music_rel = None
    if audio.get("music_path"):
        try:
            music_rel = str(Path(audio["music_path"]).relative_to(MUSIC_DIR.resolve()))
        except Exception:
            music_rel = _resolve_music_by_name(Path(audio["music_path"]).name)
    return EDL(
        source_media_id=media_id,
        approx=False,
        cuts=cuts,
        reel=Reel(
            grade=GradeSpec(profile=str(grade.get("profile") or ""),
                            deband=bool(grade.get("deband", True)),
                            grain=bool(grade.get("grain", False)),
                            vignette=bool(grade.get("vignette", False))),
            lut=None if merge.get("graded") else _current_lut_default(),
            audio_mode=audio.get("mode", "music"),
            music=MusicSpec(path=music_rel,
                            # `or 1.0` would be wrong here: 0.0 is a deliberate
                            # mute, only a missing key means "unchanged".
                            volume=_clamp(float(audio.get("volume") if audio.get("volume")
                                                is not None else 1.0), 0.0, 2.0),
                            fade_s=float(audio.get("fade_s", 1.0)),
                            start_offset_s=audio.get("enter_offset_s")),
            loop_friendly=bool(plan.get("timeline", {}).get("loop_friendly")),
            **_current_reel_toggles(),
        ),
    )


def _hydrate_from_cuts(media_id: str, merge: dict, _mc) -> EDL:
    """Lossy hydrate from the legacy per-cut spine. Fidelity per field:

    exact  — src_media_id, in_s, out_s, transition NAME, Ken Burns direction/drift,
             grade profile, deband, audio_mode, loop_friendly
    approx — transition DURATION (never recorded → merge.transition_ms, with the
             1-frame hard cut re-derived at i%3==2), Ken Burns ENABLEMENT, speed,
             grain/vignette, music path/offset/fade/volume, LUT, eq, branding,
             intro/cast, voiceover. Layers have no legacy source at all → [].
    """
    cfg = _mc._settings()
    fx = merge.get("fx") or {}
    variety = _mc._VARIETY_TRANSITIONS if fx.get("transition_variety") else None
    base_name = merge.get("transition") or cfg.get("transition") or "fade"
    base_tdur = _clamp(float(cfg.get("transition_ms", 500)) / 1000.0, MIN_JOIN_S, MAX_JOIN_S)
    hard_td = round(1.0 / 30.0, 3)
    kb_on = bool(fx.get("ken_burns") and not fx.get("adaptive_fx"))

    cuts: list[Cut] = []
    for i, c in enumerate(merge.get("cuts") or []):
        start = float(c.get("start", 0.0) or 0.0)
        dur = float(c.get("dur", 0.0) or 0.0)
        name = variety[i % len(variety)] if variety else base_name
        tdur = hard_td if (fx.get("hard_cuts_on_beat") and i % 3 == 2) else base_tdur
        cuts.append(Cut(
            id=f"c{i}",
            src_media_id=str(c.get("src") or ""),
            in_s=round(start, 3),
            out_s=round(start + dur, 3),
            speed=1.0,                       # per-cut slow-mo was never recorded
            smooth_slowmo=bool(fx.get("smooth_slowmo")),
            ken_burns=KenBurnsSpec(enabled=kb_on,
                                   direction="in" if i % 2 == 0 else "out",
                                   drift=i % 4),
            transition=TransitionSpec(name=name, duration_s=tdur),
        ))

    graded = bool(merge.get("graded"))
    return EDL(
        source_media_id=media_id,
        approx=True,
        cuts=cuts,
        reel=Reel(
            grade=GradeSpec(profile=(merge.get("grade") or "") if graded else "",
                            deband=bool(fx.get("deband", cfg.get("deband", True))),
                            grain=bool(cfg.get("grain", False)),
                            vignette=bool(cfg.get("vignette", False))),
            lut=None if graded else _current_lut_default(),
            audio_mode=merge.get("audio") or "music",
            music=MusicSpec(path=_resolve_music_by_name(merge.get("music_path")),
                            fade_s=float(cfg.get("music_fade_s", 1.0)),
                            start_offset_s=None),
            loop_friendly=bool(merge.get("loop_friendly")),
            **_current_reel_toggles(),
        ),
    )


def _hydrate_single(media_row: dict) -> EDL:
    """A non-merge reel (single clip, upload, stock) — one cut spanning the whole
    source. Exact on geometry, approx on everything the merge metadata would
    otherwise have carried."""
    cfg_lut = _current_lut_default()
    dur = float(media_row.get("duration_s") or 0.0)
    cuts: list[Cut] = []
    if dur > 0:
        cuts.append(Cut(
            id="c0",
            src_media_id=str(media_row.get("id") or ""),
            in_s=0.0,
            out_s=round(min(dur, MAX_CUT_S), 3),
            transition=TransitionSpec(name="fade", duration_s=0.35),
        ))
    return EDL(
        source_media_id=str(media_row.get("id") or ""),
        approx=True,
        cuts=cuts,
        reel=Reel(lut=cfg_lut, **_current_reel_toggles()),
    )


def _current_lut_default() -> str | None:
    """The LUT a legacy reel would have gotten downstream — only knowable when
    color.lut_mode is 'fixed'; the content-aware modes decide at render time."""
    color = get_setting("color") or {}
    if (color.get("lut_mode") or "category") == "fixed" and color.get("fixed_lut"):
        return str(color["fixed_lut"])
    return None


def _current_reel_toggles() -> dict:
    """branding / intro / cast / voiceover were never recorded on the media row —
    seed them from the current settings (part of why hydrate is `approx`)."""
    return {
        "branding": bool((get_setting("branding") or {}).get("overlay_enabled", False)),
        "voiceover": bool((get_setting("voiceover") or {}).get("enabled", False)),
        "intro": ScreenSpec(enabled=bool((get_setting("intro") or {}).get("enabled", False))),
        "cast": ScreenSpec(enabled=bool((get_setting("cast") or {}).get("enabled", False))),
    }


# ══════════════════════════════════════════════════════════════════════════
# compile — EDL → (PLAN, EditOverrides). This is the security boundary.
# ══════════════════════════════════════════════════════════════════════════

def _parent_plan_cuts(parent_row: dict) -> list[dict]:
    meta = parent_row.get("metadata")
    if isinstance(meta, str):
        try:
            import json as _json
            meta = _json.loads(meta)
        except Exception:
            meta = {}
    merge = (meta or {}).get("merge") if isinstance(meta, dict) else None
    plan = merge.get("plan") if isinstance(merge, dict) else None
    return (plan or {}).get("cuts") or []


def _match_parent_cut(parent_cuts: list[dict], src_id: str, in_s: float) -> dict | None:
    """Find the parent plan cut this EDL cut came from, so its RESOLVED cleanup
    fragments and cv2 metrics can be carried over. Exact on (src, start) at 3dp;
    otherwise the nearest same-source cut within 0.5 s (a small trim doesn't
    change what the footage needs). Never derived from user input."""
    want = round(float(in_s), 3)
    same_src = [c for c in parent_cuts if str(c.get("src_media_id")) == src_id]
    for c in same_src:
        if round(float(c.get("start_s", -1.0)), 3) == want:
            return c
    near = [c for c in same_src if abs(float(c.get("start_s", 1e9)) - want) <= 0.5]
    return min(near, key=lambda c: abs(float(c["start_s"]) - want)) if near else None


def compile(edl: EDL, parent_row: dict) -> tuple[Plan, EditOverrides]:  # noqa: A001
    """Validate an EDL and lower it into a render PLAN + downstream edit overrides.

    Raises EDLError on anything that cannot be rendered safely. The caller must
    treat every EDL field as hostile: this function is the only place that
    resolves paths, whitelists filter enum values, and enforces the DoS caps.

    A NEW `merge_id` is minted on every call — an export never mutates the reel
    it was opened from (`persist.edited_from` records the lineage instead).
    """
    from backend.pipeline import merge_clips as _mc

    if edl.edl_version != EDL_VERSION:
        raise EDLError(f"unsupported edl_version {edl.edl_version} (expected {EDL_VERSION})")
    if not edl.cuts:
        raise EDLError("EDL has no cuts")

    # Caps first — cheap, and it means a hostile doc is rejected before the
    # per-source ffprobe loop below does any work.
    check_caps(edl)
    ecfg = _editor_settings()

    mcfg = _mc._settings()
    vcfg = get_setting("video") or {}
    parent_cuts = _parent_plan_cuts(parent_row)

    # ── cuts: source resolution + time bounds ────────────────────────────
    plan_cuts: list[PlanCut] = []
    dur_cache: dict[str, float] = {}
    src_rows: list[dict] = []
    total_s = 0.0

    for order, cut in enumerate(edl.cuts):
        row = get_media_by_id(cut.src_media_id)
        if not row:
            raise EDLError(f"cut {cut.id}: source media {cut.src_media_id} not found")
        if (row.get("media_type") or "").upper() != "VIDEO":
            raise EDLError(f"cut {cut.id}: source {cut.src_media_id} is not VIDEO")
        src_path = _mc._source_path(row)
        if not src_path:
            raise EDLError(f"cut {cut.id}: source {cut.src_media_id} has no readable file on disk")

        dur = cut.out_s - cut.in_s
        if dur < MIN_CUT_S or dur > MAX_CUT_S:
            raise EDLError(
                f"cut {cut.id}: length {dur:.3f}s out of range [{MIN_CUT_S}, {MAX_CUT_S}]")
        if src_path not in dur_cache:
            dur_cache[src_path] = _mc._probe_duration(src_path)
        src_dur = dur_cache[src_path]
        # A 0.0 probe means ffprobe couldn't read the container — refuse rather
        # than render a segment that will silently come out empty.
        if src_dur <= 0:
            raise EDLError(f"cut {cut.id}: could not probe duration of {cut.src_media_id}")
        if cut.out_s > src_dur + 1e-3:
            raise EDLError(
                f"cut {cut.id}: out_s {cut.out_s:.3f}s exceeds source duration {src_dur:.3f}s")
        total_s += dur

        parent = _match_parent_cut(parent_cuts, cut.src_media_id, cut.in_s) or {}
        pc = parent.get("cleanup") or {}
        fx = PlanFx()
        if cut.speed < 1.0:
            fx.slow_motion = PlanSlowMotion(
                factor=round(_clamp(cut.speed, 0.3, 1.0), 4),
                smooth=bool(cut.smooth_slowmo),
            )
        if cut.ken_burns.enabled:
            fx.ken_burns = PlanKenBurns(direction=cut.ken_burns.direction,
                                        drift=int(_clamp(cut.ken_burns.drift, 0, 3)))

        plan_cuts.append(PlanCut(
            order=order,
            src_media_id=cut.src_media_id,
            src_path=src_path,
            src_duration_s=round(float(src_dur), 3),
            start_s=round(float(cut.in_s), 3),
            dur_s=round(float(dur), 3),
            score=round(float(parent.get("score", 0.0) or 0.0), 3),
            metrics=_clean_metrics(parent.get("metrics")),
            # Cleanup filter strings are copied verbatim from the parent plan or
            # left empty — a user-supplied fragment would be raw filtergraph.
            cleanup=PlanCleanup(pre=str(pc.get("pre", "") or ""),
                                post=str(pc.get("post", "") or "")),
            fx=fx,
        ))
        src_rows.append(row)

    if total_s > MAX_TOTAL_S:
        raise EDLError(f"total cut duration {total_s:.1f}s exceeds the {MAX_TOTAL_S:.0f}s cap")

    # ── joins: authoritative, whitelisted, shorter than the shortest cut ──
    min_dur = min(c.dur_s for c in plan_cuts)
    joins: list[PlanJoin] = []
    for i in range(len(edl.cuts) - 1):
        t = edl.cuts[i].transition
        name = t.name if t.name in _mc._XFADE_TRANSITIONS else "fade"
        if name != t.name:
            log.warning("editor compile: transition %r not whitelisted — using 'fade'", t.name)
        d = _clamp(float(t.duration_s), MIN_JOIN_S, MAX_JOIN_S)
        # xfade offsets go negative when the crossfade is not shorter than the
        # shortest segment — the same clamp merge_clips applies at :1369.
        if d >= min_dur:
            d = round(min_dur * 0.4, 3)
        joins.append(PlanJoin(name=name, duration_s=round(d, 3)))

    # ── grade ────────────────────────────────────────────────────────────
    profile = (edl.reel.grade.profile or "").strip()
    if profile and profile not in _mc._GRADE_PROFILES:
        raise EDLError(f"unknown grade profile {profile!r}")
    grade = GradeSpec(profile=profile, deband=edl.reel.grade.deband,
                      grain=edl.reel.grade.grain, vignette=edl.reel.grade.vignette)

    # ── audio ────────────────────────────────────────────────────────────
    music_abs = None
    if edl.reel.audio_mode == "music" and edl.reel.music.path:
        music_abs = _mc._safe_music_path(edl.reel.music.path)
        if not music_abs:
            raise EDLError("music path must resolve under the music library")
    total_render_s = round(total_s - sum(j.duration_s for j in joins), 3)
    enter = edl.reel.music.start_offset_s
    if music_abs and edl.reel.audio_mode == "music" and enter is None:
        # Resolve the auto "drop" detection ONCE here so two exports of the same
        # EDL produce the same reel (the renderer would otherwise re-detect).
        try:
            enter = _mc._music_enter_offset(music_abs, total_render_s)
        except Exception as exc:
            log.warning("editor compile: music enter detection failed (%s) — 0.0", exc)
            enter = 0.0
    audio = PlanAudio(
        mode=edl.reel.audio_mode,
        fade_s=round(_clamp(float(edl.reel.music.fade_s), 0.0, 5.0), 3),
        volume=round(_clamp(float(edl.reel.music.volume), 0.0, 2.0), 3),
        music_path=music_abs,
        beat_track_path=None,
        enter_offset_s=round(float(enter), 3) if enter is not None else None,
        auto=PlanAudioAuto(
            category=parent_row.get("category") or _mc._dominant_category(src_rows),
            tags=_flat_tags(src_rows) or None,
            mood_match=bool((get_setting("music") or {}).get("mood_match", True)),
            mood_captions=" ".join((r.get("original_caption") or "") for r in src_rows)[:4000],
            mood_tags=" ".join(_flat_tags(src_rows))[:2000],
        ),
    )

    # ── persist block (what render writes onto the new media row) ─────────
    parent_fx = _parent_fx_flags(parent_row)
    fx_flags = {k: bool(parent_fx.get(k, mcfg.get(k, False))) for k in _FX_FLAG_KEYS}
    fx_flags["slow_motion"] = any(c.fx.slow_motion for c in plan_cuts)
    fx_flags["ken_burns"] = any(c.fx.ken_burns for c in plan_cuts)
    fx_flags["transition_variety"] = len({j.name for j in joins}) > 1
    fx_flags["deband"] = bool(grade.deband)

    plan = Plan(
        origin="editor",
        merge_id=f"mrg_{uuid.uuid4().hex[:12]}",
        video=PlanVideo(crf=int(vcfg.get("crf", 20)), preset=str(vcfg.get("preset", "medium"))),
        # The renderer hardcodes 1080x1920@30; force rather than trust the doc.
        canvas=Canvas(w=_mc._W, h=_mc._H, fps=_mc._FPS),
        timeline=PlanTimeline(
            n_target=len(plan_cuts),
            loop_friendly=bool(edl.reel.loop_friendly),
            joins=joins or None,
            # Joins are authoritative for an editor export — the only policy left
            # is the render-side clamp against the PROBED segment durations.
            join_policy=PlanJoinPolicy(clamp_to_min_seg=True),
        ),
        cuts=plan_cuts,
        grade=grade,
        audio=audio,
        persist=PlanPersist(
            enabled=True,
            inherit=PlanPersistInherit(
                category=parent_row.get("category"),
                tags=parent_row.get("tags"),
            ),
            segments_per_clip=_segments_per_clip(plan_cuts),
            grade_name=profile,
            fx_flags=fx_flags,
            edited_from=edl.source_media_id,
        ),
        cleanup_segments=bool(mcfg.get("cleanup_segments", True)),
    )

    return plan, _compile_overrides(edl, ecfg)


def _flat_tags(rows: list[dict]) -> list[str]:
    out: list[str] = []
    for r in rows:
        t = r.get("tags")
        if isinstance(t, list):
            out.extend(str(x) for x in t)
        elif t:
            out.append(str(t))
    return out


def _parent_fx_flags(parent_row: dict) -> dict:
    meta = parent_row.get("metadata")
    if isinstance(meta, str):
        try:
            import json as _json
            meta = _json.loads(meta)
        except Exception:
            meta = {}
    merge = (meta or {}).get("merge") if isinstance(meta, dict) else None
    return (merge or {}).get("fx") or {}


def _segments_per_clip(plan_cuts: list[PlanCut]) -> int:
    """Max cuts drawn from any one source — the same statistic merge_clips
    records as metadata.merge.segments_per_clip."""
    counts: dict[str, int] = {}
    for c in plan_cuts:
        counts[c.src_media_id] = counts.get(c.src_media_id, 0) + 1
    return max(counts.values()) if counts else 1


def _compile_overrides(edl: EDL, ecfg: dict) -> EditOverrides:
    """Validate + resolve everything composited downstream by video_edit. Text
    length, font/sticker/LUT containment and colors are enforced here — nothing
    that fails validation reaches a filtergraph. (Layer COUNT caps are handled
    up front by check_caps.)"""
    lut_abs = None
    if edl.reel.lut:
        lut_abs = _safe_lut(edl.reel.lut)
        if not lut_abs:
            raise EDLError("lut must be an existing .cube under the LUT library")

    text_layers: list[dict] = []
    for layer in edl.layers.text:
        content = (layer.content or "").strip()
        # An empty drawtext textfile makes ffmpeg error out, so reject rather
        # than silently drop a layer the user thinks they added.
        if not content:
            raise EDLError(f"text layer {layer.id}: content is empty")
        if len(content) > MAX_TEXT_CHARS:
            raise EDLError(f"text layer {layer.id}: content exceeds {MAX_TEXT_CHARS} chars")
        font_abs = _safe_font(layer.font) if layer.font else None
        if layer.font and not font_abs:
            raise EDLError(f"text layer {layer.id}: font {layer.font!r} not found in the font library")
        d = layer.model_dump()
        d["content"] = content
        d["font_path"] = font_abs       # absolute, validated; "" font = renderer default
        text_layers.append(d)

    image_layers: list[dict] = []
    for layer in edl.layers.image:
        asset_abs = _safe_sticker(layer.asset)
        if not asset_abs:
            raise EDLError(
                f"image layer {layer.id}: asset {layer.asset!r} must be an existing "
                f".png/.webp under the assets library")
        d = layer.model_dump()
        d["asset_path"] = asset_abs
        image_layers.append(d)
    image_layers.sort(key=lambda d: d["z"])

    duck = edl.reel.music.duck_volume
    return EditOverrides(
        lut=lut_abs,
        eq=edl.reel.eq,
        branding=bool(edl.reel.branding),
        voiceover=bool(edl.reel.voiceover),
        music_duck_volume=(round(_clamp(float(duck), 0.0, 1.0), 3)
                           if duck is not None else None),
        intro=edl.reel.intro,
        cast=edl.reel.cast,
        text_layers=text_layers,
        image_layers=image_layers,
    )
