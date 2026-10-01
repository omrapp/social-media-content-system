"""
Multi-clip merge stage — stitch several raw/resized clips into one 20–60s reel.

Auto-select builds a montage of >=merge.min_segments (default 12) rapid cuts; each
source video contributes up to merge.segments_per_clip distinct, non-overlapping
sub-shots, so a small pool still yields a fast, varied montage. The per-merge scratch
dir of trimmed segments is deleted after the final reel renders (merge.cleanup_segments).

Two clip sources:
  - auto-select : reuse posts._pick_media_for_create (category/tags + strategy)
  - hand-pick   : explicit media_ids (+ optional order)

Per clip we (optionally) pick the best PySceneDetect sub-shot, trim it to an
even share of the target duration (or a beat-aligned share when merge.beat_sync),
normalize to 1080x1920/30fps (fill-crop, same as resize_clips), then xfade-chain
the segments into a single silent reel. The merged reel is written as a NEW media
row (id="mrg_<uuid>", source="merge", status="resized") so the existing
edit→upload pipeline adds LUT + music + branding with zero downstream changes.

CLI:
    python -m backend.pipeline.merge_clips --category nature --tags drone,landscape --count 3
    python -m backend.pipeline.merge_clips --media-ids id1,id2,id3
"""

import json
import logging
import random
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from backend.config import ORGANIZED_DIR, MERGE_DIR, MUSIC_DIR
from backend.db import get_media_by_id, get_setting, update_media, upsert_media

log = logging.getLogger(__name__)

_W, _H, _FPS = 1080, 1920, 30

# Serialize the FFmpeg-heavy render so concurrent create-merge calls can't fork a
# storm of encodes and exhaust the CPU. Selection/DB work stays outside the lock.
_RENDER_SEM = threading.Semaphore(1)

# Above this many cuts the monolithic xfade graph opens too many concurrent 1080p
# decoders and the OS OOM-killer takes ffmpeg down (signal 9) on small-RAM hosts.
# Reels beyond it assemble via _incremental_xfade (2 inputs per ffmpeg → bounded
# RAM). At/below it the single-pass graph is cheap enough and avoids re-encodes.
_PLAN_VERSION = 1
_XFADE_MAX_INLINE = 6

# Mirrors the DEFAULTS["merge"] group in api/routes/settings.py. Kept local so the
# pipeline never imports the route layer (avoids a circular import at module load).
_DEFAULTS = {
    "enabled": False,
    "auto_run": False,
    "clips_per_reel": 4,
    "target_duration_s": 30.0,
    "selection_strategy": "diverse",
    "scene_aware": True,
    "transition": "fade",
    "transition_ms": 500,
    "beat_sync": True,
    "min_clip_score": 0.0,
    "cut_min_s": 1.5,
    "cut_max_s": 3.0,
    "min_segments": 20,
    "min_main_videos": 10,
    "segments_per_clip": 3,
    # Stock/local segment quota (1.8.1): guarantee a floor of stock B-roll AND
    # local-archive clips in every auto-selected montage. A thin pool on one side
    # tops up from the other so the reel still fills to the cut count.
    "split_stock_local": True,
    "min_stock_segments": 8,
    "min_local_segments": 12,
    # Auto-source stock (1.8.1): when a category has NO stock yet, download a few
    # clips per provider on the fly so the montage can blend them. Opt-in.
    "auto_fetch_stock": False,
    "auto_fetch_pexels": 3,
    "auto_fetch_pixabay": 3,
    "cleanup_segments": True,
    "grade": "",
    "grain": False,
    "vignette": False,
    "auto_count": True,
    "audio_mode": "music",
    "music_fade_s": 1.0,
    "slow_motion": True,
    "slow_motion_factor": 0.85,
    "ken_burns": True,
    "transition_variety": True,
    "loop_friendly": False,
    # --- Quality enhancement (feature/merge-reel-enhancement) ---
    # Master: per-clip content-adaptive FX (duration + slow-mo + Ken Burns + cleanup
    # decided per clip from its cv2 metrics). Off = fixed idx-parity rules (legacy).
    "adaptive_fx": True,
    # Phase 1 — smart cut selection (cv2 aesthetic scoring; near-free, default on).
    "smart_select": True,
    "select_sharpness_weight": 0.5,
    "select_min_sharpness": 0.0,
    # Phase 2 — color consistency + anti-banding (cheap, default on).
    "color_match": True,
    "deband": True,
    # Phase 3 — motion/transition polish. hard_cuts_on_beat cheap (on);
    # smooth_slowmo is minterpolate (CPU-heavy) so it defaults OFF.
    "hard_cuts_on_beat": True,
    "smooth_slowmo": False,
    "smooth_slowmo_max_s": 3.0,
    # Phase 4 — detail / de-artifact. deblock cheap (on); nlmeans + per-segment
    # sharpen default OFF (sharpen coordinates with downstream video.sharpen).
    "deblock": True,
    "sharpen": False,
    "sharpen_amount": 0.3,
    "strong_denoise": False,
    # --- Freshness & Variety (feature/merge-reel-enhancement) ---
    # Anti-repeat + diversity across same-category reels. Memory is METADATA-ONLY
    # (each cut's src/start/dur/score in the mrg_ row JSONB) — no disk cache, no
    # migration. All default-ON; set to legacy values for byte-identical output.
    "dedupe_enabled": True,
    "subshot_cooldown_reels": 3,
    "dedupe_soft_weight": 0.5,
    "proven_topup": True,
    "proven_min_score": 0.5,
    "dynamic_count": True,
    "max_cuts_per_source": 1,
}

# Transitions rotated across cuts when merge.transition_variety is on. Every
# entry must live in _XFADE_TRANSITIONS (validated below).
_VARIETY_TRANSITIONS = ["fade", "dissolve", "slideup", "wipeleft", "smoothleft",
                        "circleopen", "slideleft", "smoothright", "wipedown"]

# Whitelist of xfade transitions we expose — never interpolate a raw user string
# into the filtergraph. Anything outside this set falls back to "fade".
_XFADE_TRANSITIONS = {
    "fade", "fadeblack", "fadewhite", "dissolve", "wipeleft", "wiperight",
    "wipeup", "wipedown", "slideleft", "slideright", "slideup", "slidedown",
    "smoothleft", "smoothright", "circleopen", "circleclose", "radial",
    "pixelize", "distance",
}

# Film-look color-grade profiles (FFmpeg colorbalance/curves/eq chains) ported from
# OpenMontage tools/enhancement/color_grade.py — pure FFmpeg, no extra deps. When a
# profile is set (merge.grade) the merged reel is graded at render time and the
# downstream LUT is skipped (one coherent look, no double-grade).
_GRADE_PROFILES = {
    "cinematic_warm": (
        "colorbalance=rs=0.08:gs=0.02:bs=-0.05:rh=0.06:gh=0.02:bh=-0.04,"
        "curves=all='0/0.03 0.25/0.22 0.5/0.50 0.75/0.78 1/0.97',"
        "eq=contrast=1.05:saturation=1.1"
    ),
    "cinematic_cool": (
        "colorbalance=rs=-0.02:gs=-0.03:bs=0.08:rh=0.06:gh=-0.02:bh=-0.06,"
        "curves=all='0/0.02 0.25/0.20 0.5/0.48 0.75/0.78 1/0.98',"
        "eq=contrast=1.08:saturation=1.05"
    ),
    "moody_dark": (
        "curves=all='0/0.05 0.15/0.12 0.5/0.45 0.85/0.82 1/0.95',"
        "eq=contrast=1.12:saturation=0.8:brightness=-0.03"
    ),
    "bright_clean": (
        "curves=all='0/0.05 0.25/0.30 0.5/0.55 0.75/0.80 1/1.0',"
        "eq=contrast=1.0:saturation=1.15:brightness=0.02"
    ),
    "vintage_film": (
        "colorbalance=rs=0.06:gs=0.03:bs=-0.03:ms=0.03:mh=-0.02,"
        "curves=all='0/0.06 0.25/0.25 0.5/0.50 0.75/0.74 1/0.94',"
        "eq=saturation=0.85:contrast=0.95"
    ),
    "high_contrast": (
        "curves=all='0/0 0.20/0.12 0.5/0.50 0.80/0.88 1/1',"
        "eq=contrast=1.2:saturation=1.1"
    ),
    "neutral": "eq=contrast=1.02:saturation=1.02:brightness=0.01",
    # Teal shadows / orange highlights — the classic "cinematic" split-tone.
    "teal_orange": (
        "colorbalance=rs=-0.05:gs=0.02:bs=0.10:rh=0.10:gh=0.03:bh=-0.08,"
        "curves=all='0/0.03 0.5/0.50 1/0.97',eq=contrast=1.08:saturation=1.12"
    ),
    # Warm sunset wash — lifted warm mids, gentle rolloff.
    "golden_hour": (
        "colorbalance=rs=0.10:gs=0.04:bs=-0.08:rh=0.10:gh=0.05:bh=-0.10,"
        "curves=all='0/0.04 0.5/0.52 1/0.98',"
        "eq=contrast=1.04:saturation=1.15:brightness=0.02"
    ),
    # Punchy, saturated social-first pop.
    "vivid_pop": (
        "eq=contrast=1.10:saturation=1.25:brightness=0.01,"
        "curves=all='0/0.02 0.5/0.50 1/1'"
    ),
}


def _grade_chain(cfg: dict) -> tuple[str, bool]:
    """Build the post-montage cinematic filter (grade + grain + vignette).

    Returns (filter_string, graded) where graded=True when a color-grade PROFILE
    is applied — the caller records that so video_edit skips the downstream LUT.
    grain/vignette alone do not count as a grade (LUT still wanted)."""
    parts: list[str] = []
    prof = (cfg.get("grade") or "").strip()
    graded = bool(prof and prof in _GRADE_PROFILES)
    if graded:
        parts.append(_GRADE_PROFILES[prof])
    # deband right after the grade — grading flat footage induces 8-bit banding in
    # skies/gradients; a cheap deband pass removes it. Not itself a "grade".
    if cfg.get("deband"):
        parts.append("deband")
    if cfg.get("grain"):
        # subtle temporal+uniform grain — filmic texture without crushing detail
        parts.append("noise=alls=8:allf=t+u")
    if cfg.get("vignette"):
        parts.append("vignette=PI/5")
    return ",".join(parts), graded


# Fill-crop to 9:16 + lanczos scale — identical framing to resize_clips so merged
# clips match the look of single-clip reels. fps lock keeps xfade inputs uniform.
_NORM_FILTER = (
    f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',"
    f"scale={_W}:{_H}:flags=lanczos,setsar=1,fps={_FPS}"
)


class MergeError(RuntimeError):
    """Raised when a merge cannot proceed (too few clips, all renders failed)."""


def _settings() -> dict:
    stored = get_setting("merge") or {}
    return {**_DEFAULTS, **(stored if isinstance(stored, dict) else {})}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _source_path(row: dict) -> str | None:
    """Best on-disk path for a media row: prefer the resized reel, then the
    decaptioned (cleaned) raw clip, else the original raw clip (relative paths
    anchor to ORGANIZED_DIR, same as resize_clips)."""
    rrp = row.get("reel_ready_path")
    if rrp and Path(rrp).exists():
        return rrp
    # Cleaned raw source (decaption pre-pass) takes precedence over the original.
    dcp = row.get("decaptioned_path")
    if dcp and Path(dcp).exists():
        return dcp
    src = row.get("local_path")
    if not src:
        return None
    if not Path(src).is_absolute():
        src = str(ORGANIZED_DIR / src)
    return src if Path(src).exists() else None


def _probe_duration(path: str) -> float:
    """Clip duration in seconds via ffprobe (0.0 on failure)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, timeout=30,
        )
        return float((out.stdout or b"0").decode().strip() or 0.0)
    except Exception:
        return 0.0


def _cv2mod():
    """OpenCV module if importable (ships via scenedetect[opencv]), else None.
    Every aesthetic-scoring / color-match path degrades gracefully when absent."""
    try:
        import cv2  # noqa: F401
        return cv2
    except Exception:
        return None


def _window_metrics(cv2, path: str, start: float, dur: float, samples: int = 3):
    """Sample a few frames across [start, start+dur] and return cheap CPU aesthetic
    metrics normalized to 0..1: sharpness (variance of Laplacian), exposure sanity
    (mean luma near mid), motion sanity (inter-frame diff, mid-range preferred),
    plus a coarse color histogram (variety guard) and BGR channel means (white
    balance). Returns None when the clip can't be read. Cheap: frames downscaled
    to 160x284 before any math."""
    try:
        import numpy as np
    except Exception:
        return None
    cap = cv2.VideoCapture(path)
    if not cap or not cap.isOpened():
        try:
            cap.release()
        except Exception:
            pass
        return None
    try:
        ts = [start + dur * (i + 1) / (samples + 1) for i in range(samples)]
        lap_vars, lumas, grays, means = [], [], [], []
        hist = None
        for t in ts:
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            small = cv2.resize(frame, (160, 284))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            lap_vars.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
            lumas.append(float(gray.mean()))
            grays.append(gray)
            means.append(small.reshape(-1, 3).mean(axis=0))  # BGR
            if hist is None:
                h = cv2.calcHist([small], [0, 1, 2], None, [4, 4, 4],
                                 [0, 256, 0, 256, 0, 256])
                hist = cv2.normalize(h, h).flatten()
        if not lap_vars:
            return None
        # 300 ~ "acceptably sharp" reference for the Laplacian variance on 160-wide.
        sharp = min(1.0, (sum(lap_vars) / len(lap_vars)) / 300.0)
        luma = sum(lumas) / len(lumas)
        expo = max(0.0, 1.0 - abs(luma - 128.0) / 128.0)
        if len(grays) >= 2:
            diffs = [float(np.abs(grays[i].astype("int16") - grays[i - 1].astype("int16")).mean())
                     for i in range(1, len(grays))]
            md = sum(diffs) / len(diffs)
            # sanity score: reject frozen (~0) and violently shaky (>40); peak ~16.
            motion = max(0.0, 1.0 - abs(min(md, 40.0) - 16.0) / 24.0)
            # raw magnitude 0..1 (low = calm/static, high = action) — drives the
            # per-clip adaptive slow-mo / Ken Burns decisions.
            motion_mag = min(md, 40.0) / 40.0
        else:
            motion = 0.5
            motion_mag = 0.5
        bgr = np.mean(means, axis=0)
        return {"sharp": sharp, "expo": expo, "motion": motion, "motion_mag": motion_mag,
                "hist": hist, "bgr": (float(bgr[0]), float(bgr[1]), float(bgr[2]))}
    except Exception:
        return None
    finally:
        cap.release()


def _hist_sim(cv2, a, b) -> float:
    """Correlation similarity of two color histograms (1.0 = identical look)."""
    try:
        return float(cv2.compareHist(a, b, cv2.HISTCMP_CORREL))
    except Exception:
        return 0.0


def _wb_gains(bgr: tuple, limit: float = 0.12):
    """Gray-world white-balance gains (R,G,B order for colorchannelmixer rr/gg/bb),
    each clamped to 1±limit so the correction is a gentle shot-match nudge, never a
    recolor. bgr = (B,G,R) channel means. None when the frame is near-black."""
    b, g, r = bgr
    avg = (b + g + r) / 3.0
    if avg <= 1.0:
        return None
    def gain(c):
        return _clamp(avg / max(c, 1.0), 1.0 - limit, 1.0 + limit)
    return gain(r), gain(g), gain(b)


class MergeError(Exception):
    """Selection failed. run() converts this back into the {"status":"error"}
    dict its callers (posts.py, telegram_bot.py) parse, so the message strings
    are part of the contract — do not reword them."""


def _plan_metrics(met: dict | None) -> dict | None:
    """Trim cv2 metrics to the JSON-serializable subset the render actually reads.

    `hist` is dropped deliberately: _window_metrics returns it as a numpy
    ndarray (json.dumps raises on it) and only _subshots, which is selection-side,
    ever reads it. Every value is coerced with float() so numpy scalars don't
    leak into the plan and change a %.2f/%.3f filter string downstream."""
    if not met:
        return None
    out = {k: float(met[k]) for k in ("sharp", "expo", "motion", "motion_mag")
           if met.get(k) is not None}
    bgr = met.get("bgr")
    if bgr is not None:
        out["bgr"] = [float(v) for v in bgr]
    return out


def _first_of(rows: list[dict], field: str):
    """First non-empty `field` across rows. Iterates ROWS (every resolved source),
    not the cut list — a source that resolved but produced no cut still votes,
    and changing that would silently alter a reel's category/tags."""
    for r in rows:
        if r.get(field):
            return r[field]
    return None


def _clip_quality(met: dict | None, row: dict | None) -> float:
    """Per-clip 0..1 quality used to weight screen-time: blends cv2 sharpness +
    exposure with the row's hook/quality score. Degrades to the row score alone
    when cv2 metrics are unavailable."""
    hook = _clamp(float((row or {}).get("hook_score")
                        or (row or {}).get("quality_score") or 0.0), 0.0, 1.0)
    if not met:
        return hook
    return _clamp(0.45 * met.get("sharp", 0.5)
                  + 0.25 * met.get("expo", 0.5)
                  + 0.30 * hook, 0.0, 1.0)


def _adaptive_durations(base_seg: float, mets: list, rows: list,
                        cut_min: float, cut_max: float, target_total: float) -> list[float]:
    """Quality-weighted per-clip cut lengths: stronger clips (sharper / better
    exposed / higher hook) hold longer, weaker clips flash by. Each duration is
    base_seg × a 0.8–1.3 quality multiplier, clamped to [cut_min, cut_max], then
    the whole set is rescaled so the reel still lands on target_total."""
    n = len(mets)
    if n == 0:
        return []
    q = [_clip_quality(mets[i], rows[i] if i < len(rows) else None) for i in range(n)]
    durs = [_clamp(base_seg * (0.8 + 0.5 * qi), cut_min, cut_max) for qi in q]
    s = sum(durs) or 1.0
    scale = target_total / s
    return [round(_clamp(d * scale, cut_min, cut_max), 3) for d in durs]


def _best_subshot_start(path: str, want: float) -> float:
    """PySceneDetect: return the start offset (s) of the longest scene that can
    hold `want` seconds. Falls back to 0.0 if scenedetect is unavailable, errors,
    or finds nothing usable. Lazy-imported so non-merge code pays nothing."""
    try:
        from scenedetect import detect, ContentDetector
    except Exception:
        return 0.0
    try:
        scenes = detect(path, ContentDetector())
    except Exception as exc:
        log.warning("merge: scenedetect failed for %s (%s) — using whole clip", path, exc)
        return 0.0
    best_start, best_len = 0.0, -1.0
    for start_tc, end_tc in scenes or []:
        s, e = start_tc.get_seconds(), end_tc.get_seconds()
        length = e - s
        if length >= want and length > best_len:
            best_start, best_len = s, length
    return best_start


def _subshots(path: str, k: int, want: float, clip_dur: float, scene_aware: bool,
              cfg: dict | None = None, used: list[tuple] | None = None) -> list[float]:
    """Up to `k` DISTINCT, non-overlapping start offsets (s) in one clip, each able
    to hold `want` seconds — so a single source video contributes several different
    moments to the montage (rule: reuse different segments from the same video).

    Candidate pool = PySceneDetect scenes (>= want) + an even-spread fill. When
    merge.smart_select is on and cv2 is available, candidates are RANKED by a cheap
    aesthetic score (sharpness / exposure / motion) and the top-k are chosen with a
    color-histogram variety guard so near-duplicate looks aren't picked twice. Falls
    back to the legacy "longest scenes, then even spread" order when smart_select is
    off, cv2 is missing, or scoring yields nothing. Returns fewer than k only when
    the clip is too short to hold that many `want`-windows.

    `used` = [(start, dur, reel_rank)] sub-shots this SAME source contributed to
    recent same-category reels (metadata memory). When merge.dedupe_enabled, a
    candidate overlapping a window used within merge.subshot_cooldown_reels is
    HARD-EXCLUDED (unless that empties the pool); overlapping a window used past the
    cooldown is SOFT-weighted (score ×merge.dedupe_soft_weight / pushed after fresh)
    so a new reel avoids repeating recent cuts. Empty `used` / dedupe off ⇒ old
    behavior unchanged."""
    if clip_dur <= 0 or want <= 0:
        return [0.0]
    cfg = cfg or {}
    # Hard ceiling on how many non-overlapping windows physically fit.
    fit = max(1, int(clip_dur // want))
    k = max(1, min(k, fit))
    span = max(0.0, clip_dur - want)

    # 1. Build a non-overlapping candidate pool (longest scenes first, then even
    #    spread). Over-generate a little so smart-select has real choice.
    pool: list[float] = []
    if scene_aware:
        try:
            from scenedetect import detect, ContentDetector
            scenes = detect(path, ContentDetector()) or []
            cand = sorted(
                ((s.get_seconds(), e.get_seconds()) for s, e in scenes),
                key=lambda se: se[1] - se[0], reverse=True,
            )
            for s, e in cand:
                if (e - s) < want:
                    continue
                start = _clamp(s, 0.0, span)
                if all(abs(start - p) >= want for p in pool):
                    pool.append(start)
        except Exception as exc:
            log.warning("merge: scenedetect subshots failed for %s (%s)", path, exc)
            pool = []
    m = max(k, min(fit, 8))
    even = [round((span * i) / max(1, m - 1), 3) if m > 1 else 0.0 for i in range(m)]
    for st in even:
        if all(abs(st - p) >= want for p in pool):
            pool.append(st)

    # Anti-repeat memory: rank each candidate against sub-shots this source gave to
    # recent same-category reels. _used_rank(st) = smallest reel_rank overlapping st,
    # or None when fresh. rank < cooldown ⇒ hard-exclude; rank >= cooldown ⇒ soft.
    used = used or []
    dedupe = bool(cfg.get("dedupe_enabled", True)) and bool(used)
    cooldown = int(_clamp(int(cfg.get("subshot_cooldown_reels", 3)), 0, 20))
    soft_w = _clamp(float(cfg.get("dedupe_soft_weight", 0.5)), 0.0, 1.0)

    def _used_rank(st):
        best = None
        for u_start, _u_dur, u_rank in used:
            if abs(st - u_start) < want:
                best = u_rank if best is None else min(best, u_rank)
        return best

    ranks = {p: _used_rank(p) for p in pool} if dedupe else {}

    # 2. Legacy path: no scoring needed / possible → longest-then-even order.
    cv2 = _cv2mod() if cfg.get("smart_select", True) else None
    if len(pool) <= k or cv2 is None:
        if dedupe:
            # Fresh (unused) first, then soft (used past cooldown); hard-excluded
            # (rank < cooldown) dropped — unless that empties the pool (last resort).
            fresh = sorted(p for p in pool if ranks[p] is None)
            soft = sorted(p for p in pool
                          if ranks[p] is not None and ranks[p] >= cooldown)
            cands = (fresh + soft) or sorted(pool)
            return cands[:k] or [0.0]
        pool.sort()
        return pool[:k] or [0.0]

    # 3. Smart-select: score every candidate, greedily take top-k that don't overlap
    #    and don't repeat a look (histogram correlation guard).
    w_sharp = _clamp(float(cfg.get("select_sharpness_weight", 0.5)), 0.0, 1.0)
    min_sharp = _clamp(float(cfg.get("select_min_sharpness", 0.0)), 0.0, 1.0)
    scored: list[tuple] = []
    for st in pool:
        rank = ranks.get(st) if dedupe else None
        if rank is not None and rank < cooldown:
            continue  # hard-excluded: used within the cooldown window
        met = _window_metrics(cv2, path, st, want)
        if not met:
            continue
        if min_sharp > 0 and met["sharp"] < min_sharp:
            continue
        score = (w_sharp * met["sharp"]
                 + (1.0 - w_sharp) * 0.5 * met["expo"]
                 + (1.0 - w_sharp) * 0.5 * met["motion"])
        if rank is not None:  # soft (used past cooldown): keep but down-weight
            score *= soft_w
        scored.append((score, st, met))
    if not scored:
        pool.sort()
        return pool[:k] or [0.0]
    scored.sort(key=lambda x: x[0], reverse=True)
    chosen: list[float] = []
    chosen_hists: list = []
    for _score, st, met in scored:
        if any(abs(st - c) < want for c in chosen):
            continue
        if chosen_hists and met.get("hist") is not None:
            sim = max(_hist_sim(cv2, met["hist"], h) for h in chosen_hists)
            if sim > 0.9:  # near-identical look already picked — skip for variety
                continue
        chosen.append(st)
        if met.get("hist") is not None:
            chosen_hists.append(met["hist"])
        if len(chosen) >= k:
            break
    chosen.sort()
    return chosen or (sorted(pool)[:k] or [0.0])


def _beat_segment_durations(track_path: str, n: int, total: float, base: float) -> list[float]:
    """Beat-align per-clip durations to the music. Returns n durations summing
    ~total, each a whole number of beats nearest to `base`. Falls back to even
    split on any failure. librosa lazy-imported (heavy)."""
    try:
        import librosa
        import numpy as np
        y, sr = librosa.load(track_path, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        # librosa >=0.10 returns tempo as an ndarray; float() on a 1-element
        # array raises "only 0-dimensional arrays can be converted". Coerce the
        # first element to a Python float regardless of scalar/array shape.
        bpm = float(np.atleast_1d(tempo)[0]) if tempo is not None else 0.0
        if bpm <= 0:
            raise ValueError("no tempo")
        beat = 60.0 / bpm
        beats_each = max(1, round(base / beat))
        return [round(beats_each * beat, 3)] * n
    except Exception as exc:
        log.warning("merge: beat_sync failed (%s) — even split", exc)
        return [round(base, 3)] * n


def _music_enter_offset(track_path: str, seg_len: float) -> float:
    """Best enter point (s) into the music bed so the montage opens on energy,
    not the track's quiet intro. Uses librosa onset strength to find the first
    strong onset (the "drop"), clamped so the reel still fits. Falls back to the
    energy-based scan (video_edit.best_audio_offset), then 0.0. librosa is
    lazy-imported (heavy)."""
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(track_path, mono=True)
        total = librosa.get_duration(y=y, sr=sr)
        if not total or total <= seg_len + 1:
            return 0.0
        latest = max(0.0, total - seg_len)

        env = librosa.onset.onset_strength(y=y, sr=sr)
        times = librosa.times_like(env, sr=sr)
        # First onset that clears 70% of the peak strength = the "drop".
        thresh = float(np.max(env)) * 0.7 if env.size else 0.0
        for t, e in zip(times, env):
            if e >= thresh and t <= latest:
                return round(float(t), 3)
        # No clear drop before the cutoff — start on the overall strongest onset.
        strong_t = float(times[int(np.argmax(env))]) if env.size else 0.0
        return round(min(strong_t, latest), 3)
    except Exception as exc:
        log.warning("merge: music enter-point detection failed (%s) — energy scan", exc)
        try:
            from backend.pipeline.video_edit import best_audio_offset
            return best_audio_offset(track_path, seg_len)
        except Exception:
            return 0.0


def _fx_decide(idx: int, cfg: dict, met: dict | None = None) -> dict:
    """Choose this segment's motion FX. Pure, JSON-serializable, duration-free.

    Split out of _fx_segment so the decision can be made once at plan-build time
    and frozen into the plan: the editor renders the decisions the user saw in
    preview rather than re-deriving them from cv2 at render time (which would let
    preview and export disagree). Auto merges are unaffected — build_plan calls
    this with the same (idx, cfg, met) the render loop used to.

    Adaptive (merge.adaptive_fx + cv2 metrics available) picks per clip by content:
      - slow-mo → CALM/low-motion clips (met.motion_mag < 0.30) for a dreamy hold;
        action clips stay real-time. (Legacy: alternating even idx.)
      - Ken Burns → low-motion clips (met.motion_mag < 0.45) to add life to
        near-static shots; already-dynamic clips are left alone. (Legacy: all.)

    `smooth` is the REQUESTED flag; the duration gate against smooth_max_s can
    only be applied once the segment is probed, so _fx_filter binds it."""
    adaptive = bool(cfg.get("adaptive_fx", True)) and met is not None
    if adaptive:
        want_slow = cfg.get("slow_motion") and met.get("motion_mag", 0.5) < 0.30
    else:
        want_slow = cfg.get("slow_motion") and idx % 2 == 0

    slow = None
    if want_slow:
        factor = _clamp(float(cfg.get("slow_motion_factor", 0.85)), 0.3, 1.0)
        if factor < 1.0:
            slow = {
                "factor": factor,
                "smooth": bool(cfg.get("smooth_slowmo")),
                "smooth_max_s": _clamp(float(cfg.get("smooth_slowmo_max_s", 3.0)), 0.5, 8.0),
            }

    want_kb = cfg.get("ken_burns") and (
        (met.get("motion_mag", 0.5) < 0.45) if adaptive else True)
    # direction: alternating push/pull. drift: occasional off-center horizontal
    # travel (rule: not always dead-center) — most segments stay centered.
    kb = {"direction": "in" if idx % 2 == 0 else "out",
          "drift": idx % 4} if want_kb else None

    return {"slow_motion": slow, "ken_burns": kb}


def _fx_filter(dec: dict | None, seg_dur: float) -> str:
    """Render a _fx_decide() decision into an FFmpeg filter string.

    DURATION-PRESERVING so the xfade offsets computed from the probed segment
    durations stay valid: slow-mo uses `setpts=(1/factor)*PTS` then
    `trim=duration=seg_dur` + rebase, and the eased zoompan emits one frame per
    input frame. Returns "null" (== no-op) when nothing applies."""
    chain: list[str] = []
    dec = dec or {}

    slow = dec.get("slow_motion")
    if slow:
        factor = float(slow["factor"])
        # Motion-compensated interpolation → judder-free slow-mo. CPU-HEAVY
        # (gated by merge.smooth_slowmo, default off; capped by smooth_max_s).
        smooth = bool(slow.get("smooth")) and seg_dur <= float(slow.get("smooth_max_s", 3.0))
        if smooth:
            chain.append(
                f"setpts={1.0 / factor:.4f}*PTS,"
                f"minterpolate=fps={_FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
                f"trim=duration={seg_dur:.3f},setpts=PTS-STARTPTS"
            )
        else:
            chain.append(
                f"setpts={1.0 / factor:.4f}*PTS,"
                f"trim=duration={seg_dur:.3f},setpts=PTS-STARTPTS"
            )

    kb = dec.get("ken_burns")
    if kb:
        frames = max(1, round(seg_dur * _FPS))
        # Eased (smoothstep) push/pull so the zoom starts and ends gently instead
        # of a linear ramp — reads more deliberate/cinematic.
        t = f"(on/{frames})"
        ease = f"(3*pow({t},2)-2*pow({t},3))"
        zexpr = f"1+0.10*{ease}" if kb.get("direction") == "in" else f"1.10-0.10*{ease}"
        drift = int(kb.get("drift", 0)) % 4
        if drift == 1:
            xexpr = f"iw/2-(iw/zoom/2)+(iw*0.04*on/{frames})"
        elif drift == 3:
            xexpr = f"iw/2-(iw/zoom/2)-(iw*0.04*on/{frames})"
        else:
            xexpr = "iw/2-(iw/zoom/2)"
        chain.append(
            f"zoompan=z='{zexpr}':d=1:"
            f"x='{xexpr}':y='ih/2-(ih/zoom/2)':"
            f"s={_W}x{_H}:fps={_FPS}"
        )

    return ",".join(chain) if chain else "null"


def _fx_segment(idx: int, seg_dur: float, cfg: dict, met: dict | None = None) -> str:
    """Decide + render this segment's motion FX. Kept as the composition of
    _fx_decide and _fx_filter so the equivalence test holds by construction."""
    return _fx_filter(_fx_decide(idx, cfg, met), seg_dur)


def _resolve_joins(cfg: dict, final_durs: list[float],
                   tdur: float) -> tuple[list[str] | None, list[float] | None, float]:
    """Resolve the per-join transition plan: (variety, tdurs, tdur).

    Sole owner of the SECOND tdur clamp. The first clamp happens at plan-build
    time against `base_seg` (the requested per-cut duration); this one runs after
    the segments are probed, because a segment can come back shorter than
    requested and a tdur >= the shortest segment drives xfade offsets negative.
    Keeping both clamps in one place is what stops the split from silently
    shifting every offset — see tests/test_merge_equivalence.py.

    `tdurs` is the per-join duration list used for hard-cuts-on-beat: every 3rd
    join collapses to ~1 frame, which reads as a hard cut without breaking the
    xfade offset math. None when the feature is off or the reel is too short."""
    if tdur >= min(final_durs):
        tdur = round(min(final_durs) * 0.4, 3)

    variety = _VARIETY_TRANSITIONS if cfg.get("transition_variety") else None

    tdurs = None
    if cfg.get("hard_cuts_on_beat", True) and len(final_durs) > 3:
        hard_td = round(1.0 / _FPS, 3)
        tdurs = [(hard_td if (k % 3 == 2) else tdur)
                 for k in range(len(final_durs) - 1)]

    return variety, tdurs, tdur


def _xfade_chain(seg_durs: list[float], transition: str, tdur: float,
                 seg_filters: list[str] | None = None,
                 transitions: list[str] | None = None,
                 tdurs: list[float] | None = None) -> tuple[str, float]:
    """Build the filter_complex xfade chain across N normalized inputs.

    Crossfades overlap per-join, so the offset for the k-th join is
    sum(d_0..d_{k-1}) - sum(td_1..td_k). Final timeline = sum(durs) - sum(all td).
    Returns (filtergraph, total_duration). This is the assembly seam where a
    vendored OpenMontage builder can drop in (see _vendor_chain).

    seg_filters: per-segment filter prefix (from _fx_segment); None ⇒ _NORM_FILTER
    for every input (backward-compatible). transitions: rotate through this list
    across cuts (variety); None ⇒ the single `transition` everywhere. tdurs: per-join
    overlap seconds (len N-1) — used for hard-cut-on-beat, where select joins get a
    near-zero overlap (hard cut) mixed among the crossfades; None ⇒ constant `tdur`."""
    n = len(seg_durs)
    filt = seg_filters or [_NORM_FILTER] * n
    # xfade requires both of its inputs to share a timebase. Per-segment FX diverge:
    # Ken Burns (zoompan) emits tb=1/_FPS while a plain "null"/setpts segment keeps
    # the source file's fine tb (e.g. 1/15360). When FX are applied to only SOME
    # clips (adaptive_fx / KB skipped on dynamic clips) the chain mixes timebases and
    # xfade aborts ("timebase do not match"). Pin every input to a uniform tb.
    parts = [f"[{i}:v]{filt[i]},settb=1/{_FPS}[v{i}]" for i in range(n)]
    prev = "v0"
    acc = 0.0
    tacc = 0.0
    for k in range(1, n):
        acc += seg_durs[k - 1]
        td = tdurs[k - 1] if tdurs else tdur
        tacc += td
        offset = round(acc - tacc, 3)
        out = f"x{k}" if k < n - 1 else "vout"
        trans = transitions[(k - 1) % len(transitions)] if transitions else transition
        parts.append(
            f"[{prev}][v{k}]xfade=transition={trans}:duration={td}:"
            f"offset={offset}[{out}]"
        )
        prev = out
    total_td = sum(tdurs) if tdurs else (n - 1) * tdur
    total = round(sum(seg_durs) - total_td, 3)
    return ";".join(parts), total


def _vendor_chain(seg_durs, transition, tdur, seg_filters=None, transitions=None, tdurs=None):
    """Use the vendored OpenMontage xfade assembler when present; otherwise the
    built-in _xfade_chain. Keeps the stage functional before Phase 0 vendoring.
    The vendored builder predates per-segment FX/variety, so when FX or variety
    are requested we fall through to _xfade_chain to honor them."""
    if seg_filters is None and transitions is None and tdurs is None:
        try:
            from backend.vendor.openmontage import build_xfade_chain  # type: ignore
            return build_xfade_chain(seg_durs, transition, tdur, _NORM_FILTER)
        except Exception:
            pass
    return _xfade_chain(seg_durs, transition, tdur, seg_filters, transitions, tdurs)


def _incremental_xfade(seg_files: list[Path], seg_durs: list[float],
                       seg_filters: list[str] | None, transition: str,
                       transitions: list[str] | None, tdur: float,
                       tdurs: list[float] | None, work: Path) -> tuple[Path, float]:
    """Assemble the montage by folding two segments at a time to disk. Each ffmpeg
    invocation opens only the running accumulator + the next segment (2 inputs), so
    peak RAM stays bounded no matter how many cuts the reel has — unlike the
    monolithic xfade graph, whose N concurrent 1080p decoders OOM-kill ffmpeg
    (signal 9) on small-RAM hosts. FX are already pre-baked into seg_files
    (duration-preserving), so each fold is xfade-only. Per-join transition/overlap
    mirror _xfade_chain: transitions rotates for variety, tdurs sets per-join
    overlap (hard-cut-on-beat). Returns (montage_path, total_duration); raises on any
    fold failure so the caller can fall back to the monolithic graph."""
    n = len(seg_files)
    filt = seg_filters or ["null"] * n
    acc = seg_files[0]
    acc_len = seg_durs[0]
    for k in range(1, n):
        td = tdurs[k - 1] if tdurs else tdur
        trans = transitions[(k - 1) % len(transitions)] if transitions else transition
        offset = round(acc_len - td, 3)
        # The accumulator already carries seg 0's FX after the first fold; only the
        # very first step still needs to apply filt[0]. Pin both to a uniform tb so
        # xfade doesn't abort on a timebase mismatch (same guard as _xfade_chain).
        f0 = filt[0] if k == 1 else "null"
        out = work / f"fold_{k:02d}.mp4"
        fc = (f"[0:v]{f0},settb=1/{_FPS}[a];"
              f"[1:v]{filt[k]},settb=1/{_FPS}[b];"
              f"[a][b]xfade=transition={trans}:duration={td}:offset={offset}[vout]")
        cmd = [
            "ffmpeg", "-hide_banner", "-i", str(acc), "-i", str(seg_files[k]),
            "-filter_complex", fc, "-map", "[vout]", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            "-pix_fmt", "yuv420p",
            "-filter_complex_threads", "2", "-filter_threads", "2", "-threads", "2",
            "-y", str(out),
        ]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            stderr = (r.stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"fold {k} failed (rc={r.returncode}): {stderr[-300:]}")
        acc = out
        acc_len = round(acc_len + seg_durs[k] - td, 3)
    return acc, acc_len


def _dominant_category(rows: list[dict]) -> str | None:
    """Most common category across the picked clips (for music selection)."""
    from collections import Counter
    c = Counter((r.get("category") or "") for r in rows if r.get("category"))
    return c.most_common(1)[0][0] if c else None


def _safe_music_path(p) -> str | None:
    """Accept a caller-supplied music path only if it resolves INSIDE MUSIC_DIR
    (no absolute escapes, no `..` traversal) and exists. Else None → auto-pick."""
    if not p:
        return None
    s = str(p)
    # A served URL (…/assets/music/<file>) → MUSIC_DIR-relative path.
    marker = "assets/music/"
    if marker in s:
        s = s.split(marker, 1)[1]
    try:
        cand = Path(s)
        if not cand.is_absolute():
            cand = MUSIC_DIR / cand
        cand = cand.resolve()
        if cand.is_relative_to(MUSIC_DIR.resolve()) and cand.exists():
            return str(cand)
    except Exception:
        return None
    return None


def _music_volume(cfg: dict) -> float:
    """Bed level from a cfg dict. Only a MISSING key means "unchanged" — 0.0 is a
    deliberate mute the editor can set, so `or 1.0` must not be used here."""
    v = cfg.get("music_volume")
    return 1.0 if v is None else float(v)


def _music_rel(p: str | None) -> str | None:
    """Inverse of `_safe_music_path` for persistence: absolute track path →
    MUSIC_DIR-relative. Falls back to the bare filename for anything outside the
    library, which `editor_edl._resolve_music_by_name` can still look up."""
    if not p:
        return None
    try:
        return str(Path(p).resolve().relative_to(MUSIC_DIR.resolve()))
    except Exception:
        return Path(p).name


def _interleave(a: list, b: list) -> list:
    """Weave two lists (local, stock) together so the montage alternates provenance
    instead of clustering all stock at the end. Longer list's tail is appended."""
    out: list = []
    for i in range(max(len(a), len(b))):
        if i < len(a):
            out.append(a[i])
        if i < len(b):
            out.append(b[i])
    return out


def _maybe_autofetch_stock(category: str, tags: list[str] | None, cfg: dict) -> None:
    """When merge.auto_fetch_stock is on AND the category/filter has NO stock clip
    yet, download a few clips per provider (default 3 Pexels + 3 Pixabay) so the
    montage can blend stock in. Requires stock.enabled + a provider key. Best-effort
    — any failure is logged, never aborts the merge."""
    if not cfg.get("auto_fetch_stock", False):
        return
    if not (get_setting("stock") or {}).get("enabled"):
        return
    from backend.db import get_category_raw_media
    # Existence probe against the SAME filter the merge pool uses.
    if get_category_raw_media(category, [], tags, "random", source="stock"):
        return
    from backend.pipeline.stock_footage import auto_fetch
    px = int(cfg.get("auto_fetch_pexels", 3) or 0)
    pb = int(cfg.get("auto_fetch_pixabay", 3) or 0)
    result = auto_fetch(category, tags, px, pb)
    log.info("merge: auto-sourced stock for %s → %s", category, result)


def _resolve_clips(media_ids, category, tags, count, order, cfg) -> list[dict]:
    """Return the ordered list of media rows to merge (hand-pick or auto-select)."""
    rows: list[dict] = []
    if media_ids:
        ordered = order or media_ids
        seen = set()
        for mid in ordered:
            if mid in seen:
                continue
            seen.add(mid)
            row = get_media_by_id(mid)
            if not row:
                log.warning("merge: media_id=%s not found — skipped", mid)
                continue
            if row.get("media_type") != "VIDEO":
                log.warning("merge: media_id=%s is not VIDEO — skipped", mid)
                continue
            rows.append(row)
        return rows

    # Auto-select. The montage rule is "all clips from the SAME category, mixed
    # tags", so a category pins the pool to one category (tags only narrow it).
    # get_category_raw_media honors that — unlike the 'diverse' picker, which
    # spans all categories. Without a category (CLI convenience) we fall back
    # to the generic cross-category picker.
    strategy = cfg["selection_strategy"]
    exclude: list[str] = []
    if category:
        from backend.db import get_category_raw_media

        def _pick(src, n):
            got: list[dict] = []
            for _ in range(max(0, int(n))):
                p = get_category_raw_media(category, exclude, tags, strategy, source=src)
                if not p:
                    break
                got.append(p)
                exclude.append(p["id"])
            return got

        # Stock/local quota (merge.split_stock_local): pull a floor of stock B-roll,
        # then fill the rest from local archive. A thin pool on either side tops up
        # from whatever's left so the reel still reaches `count` cuts.
        if bool(cfg.get("split_stock_local", True)):
            want_stock = min(int(cfg.get("min_stock_segments", 8) or 0), count)
            stock = _pick("stock", want_stock)
            local = _pick("local", count - len(stock))
            rows = _interleave(local, stock)
            if len(rows) < count:  # both sides short → top up with anything remaining
                rows += _pick(None, count - len(rows))
            return rows

        for _ in range(count):
            pick = get_category_raw_media(category, exclude, tags, strategy)
            if not pick:
                break
            rows.append(pick)
            exclude.append(pick["id"])
        return rows
    # No category: lazy import avoids a circular import (posts → scheduler → …).
    from backend.api.routes.posts import _pick_media_for_create
    for _ in range(count):
        pick = _pick_media_for_create(strategy, category, tags, exclude)
        if not pick:
            break
        rows.append(pick)
        exclude.append(pick["id"])
    return rows


def _segment_cleanup(src: str, start: float, dur: float, cfg: dict,
                     met: dict | None = None) -> tuple[str, str]:
    """Build the (pre, post) FFmpeg cleanup filter fragments wrapped around
    _NORM_FILTER for one segment. pre runs before crop/scale (deblock, denoise on
    source pixels); post runs after (colorchannelmixer white-balance nudge, cas
    sharpen). `met` are this segment's cv2 metrics (reused from the caller so we
    don't re-probe); when None and color-match/adaptive need them, they're probed
    here. Empty strings when nothing applies — so with every enhancement off the vf
    collapses to exactly _NORM_FILTER (regression-safe).

    Adaptive (merge.adaptive_fx): denoise only clips that look noisy (dark + soft),
    and sharpen only SOFT clips (strength scaled by how soft) — so each clip gets
    exactly the cleanup it needs, not a blanket pass."""
    adaptive = bool(cfg.get("adaptive_fx", True))
    if met is None and (cfg.get("color_match") or adaptive):
        cv2 = _cv2mod()
        if cv2 is not None:
            met = _window_metrics(cv2, src, start, dur, samples=2)
    return _cleanup_filters(_cleanup_decide(cfg, met))


def _cleanup_decide(cfg: dict, met: dict | None = None) -> dict:
    """Choose this segment's cleanup. Pure, JSON-serializable, never probes.

    Split out of _segment_cleanup so the decision is frozen into the plan at
    build time. Unlike _segment_cleanup this never falls back to probing when
    `met` is None — cleanup is derived from measured source pixels, never from
    editor input, so a plan compiled from an EDL copies the parent reel's
    resolved cleanup rather than recomputing it."""
    adaptive = bool(cfg.get("adaptive_fx", True))
    dec: dict = {"deblock": bool(cfg.get("deblock")), "denoise": None,
                 "wb": None, "cas": None}

    if cfg.get("strong_denoise"):
        # nlmeans is CPU-HEAVY (merge.strong_denoise, default off).
        dec["denoise"] = "nlmeans=s=1.5:p=3:r=7"
    elif adaptive and met and met.get("expo", 1.0) < 0.45 and met.get("sharp", 1.0) < 0.6:
        # Dark + not-crisp ⇒ likely sensor noise → cheap light denoise (only here).
        dec["denoise"] = "hqdn3d=2:1.5:3:3"

    if cfg.get("color_match") and met and met.get("bgr"):
        gains = _wb_gains(met["bgr"])
        if gains:
            dec["wb"] = [float(g) for g in gains]

    # Sharpen: adaptive picks soft clips and scales strength; else the blanket knob.
    if adaptive and met and met.get("sharp", 1.0) < 0.5:
        dec["cas"] = _clamp(0.6 * (1.0 - met["sharp"]), 0.15, 0.4)
    elif cfg.get("sharpen"):
        dec["cas"] = _clamp(float(cfg.get("sharpen_amount", 0.3)), 0.0, 1.0)

    return dec


def _cleanup_filters(dec: dict | None) -> tuple[str, str]:
    """Render a _cleanup_decide() decision into (pre, post) filter fragments.

    pre runs before crop/scale (source pixels), post after. Empty strings when
    nothing applies — so with every enhancement off the vf collapses to exactly
    _NORM_FILTER (regression-safe)."""
    dec = dec or {}
    pre: list[str] = []
    post: list[str] = []

    if dec.get("deblock"):
        pre.append("deblock=filter=strong:block=8")
    if dec.get("denoise"):
        pre.append(str(dec["denoise"]))

    wb = dec.get("wb")
    if wb:
        gr, gg, gb = wb
        post.append(f"colorchannelmixer=rr={gr:.3f}:gg={gg:.3f}:bb={gb:.3f}")
    if dec.get("cas") is not None:
        post.append(f"cas={float(dec['cas']):.2f}")

    return ",".join(pre), ",".join(post)


def _normalize_segment(src: str, start: float, dur: float, dest: Path,
                       cfg_video: dict, cfg: dict | None = None,
                       met: dict | None = None,
                       cleanup: dict | None = None) -> bool:
    """Extract [start, start+dur] from src, fill-crop to 1080x1920, write dest
    (video only — music is added downstream by video_edit). Encoded at ultrafast/crf18
    because segments are transient xfade inputs, not delivery files — the full
    filter+xfade pass produces the delivery encode. Optional per-segment cleanup
    (deblock / denoise / color-match / sharpen) wraps _NORM_FILTER when enabled;
    `met` (cv2 metrics) is threaded from the caller to avoid a re-probe."""
    # `cleanup` (editor plans) is an already-resolved _cleanup_decide dict;
    # without it we resolve from `met` exactly as before.
    pre, post = (_cleanup_filters(cleanup) if cleanup is not None
                 else _segment_cleanup(src, start, dur, cfg or {}, met))
    vf = ",".join([p for p in (pre, _NORM_FILTER, post) if p])
    cmd = [
        "ffmpeg", "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
        "-i", src,
        "-vf", vf, "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-movflags", "+faststart", "-y", str(dest),
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        stderr = (res.stderr or b"").decode("utf-8", "replace").strip()
        log.error("merge: segment ffmpeg failed (%s) for %s\n%s",
                  res.returncode, src, stderr[-1200:])
    return res.returncode == 0


def build_plan(
    media_ids: list[str] | None = None,
    *,
    category: str | None = None,
    tags: list[str] | None = None,
    count: int | None = None,
    order: list[str] | None = None,
    settings: dict | None = None,
) -> dict:
    """Select clips and plan the montage. Returns a JSON-serializable PLAN
    for render(). Raises MergeError when the pool cannot support a merge."""
    cfg = {**_settings(), **(settings or {})}
    video_cfg = get_setting("video") or {}

    # Clamp every numeric the render depends on (DoS / resource-exhaustion guard).
    target_total = _clamp(float(cfg["target_duration_s"]), 20.0, 60.0)
    cut_min = _clamp(float(cfg.get("cut_min_s", 3.0)), 1.0, 10.0)
    cut_max = _clamp(float(cfg.get("cut_max_s", 5.0)), cut_min, 12.0)
    # Segment count. Hand-pick → exactly the supplied ids (1 cut each). Auto →
    # a montage of >=min_segments rapid cuts (rule: many short scenes); explicit
    # count overrides; else legacy clips_per_reel.
    min_seg = int(_clamp(int(cfg.get("min_segments", 20)), 15, 30))
    seg_per = int(_clamp(int(cfg.get("segments_per_clip", 3)), 1, 4))
    min_main = int(_clamp(int(cfg.get("min_main_videos", 10)), 2, 20))
    # Stock/local quota floor (merge.split_stock_local): the montage must hold at
    # least (min_stock_segments + min_local_segments) cuts so both quotas fit.
    # Auto-select only — hand-pick keeps its exact supplied clips.
    split_active = bool(cfg.get("split_stock_local", True)) and not media_ids
    split_floor = 0
    if split_active:
        split_floor = (int(cfg.get("min_stock_segments", 8) or 0)
                       + int(cfg.get("min_local_segments", 12) or 0))
        min_seg = int(_clamp(max(min_seg, split_floor), 15, 30))
    # Diversity-first sizing (merge.dynamic_count): spread cuts across as many
    # DISTINCT source clips as the pool allows (breadth over depth) so a fresh reel
    # looks varied. Auto-select only — hand-pick / explicit count keep their exact
    # counts. Applied after the source pool is resolved (needs the real clip count).
    dynamic = bool(cfg.get("dynamic_count", True)) and not media_ids and not count
    if media_ids:
        n_target = max(2, len(order or media_ids))
    elif count:
        n_target = int(_clamp(int(count), 2, 30))
    elif cfg.get("auto_count", True):
        avg_cut = (cut_min + cut_max) / 2.0
        n_target = int(_clamp(round(target_total / max(avg_cut, 1.0)), min_seg, 30))
    else:
        n_target = int(_clamp(int(cfg["clips_per_reel"]), 2, 8))
    loop_friendly = bool(cfg.get("loop_friendly", False))
    transition = cfg["transition"] if cfg["transition"] in _XFADE_TRANSITIONS else "fade"
    tdur = _clamp(int(cfg["transition_ms"]), 100, 1500) / 1000.0

    # Auto-select spreads cuts across many videos: target at least `min_main`
    # source videos (rule: >=10 main videos) while still pulling several sub-shots
    # per clip. Best-effort — a smaller category pool just uses everything it has.
    # Hand-pick uses the supplied ids as-is.
    # Diversity mode pulls one cut per distinct source, so ask the picker for as many
    # DIFFERENT clips as there are cuts (breadth). Legacy spreads across >=min_main.
    n_sources = n_target if (media_ids or dynamic) else max(2, min_main, -(-n_target // seg_per))
    if split_active:
        # Resolve at least split_floor distinct sources so the stock/local quota
        # is satisfiable regardless of dynamic/legacy sizing.
        n_sources = max(n_sources, split_floor)
    # Auto-source stock B-roll for a category that has none yet (opt-in). Runs before
    # selection so freshly-downloaded stock rows are pickable in the same merge.
    if category and not media_ids:
        try:
            _maybe_autofetch_stock(category, tags, cfg)
        except Exception as exc:
            log.warning("merge: auto stock fetch failed (non-fatal): %s", exc)
    rows = _resolve_clips(media_ids, category, tags, n_sources, order, cfg)
    if len(rows) < 2:
        raise MergeError(f"need >=2 clips, got {len(rows)}")

    # min_clip_score gate (reuse the quality_score already on the row).
    min_score = float(cfg.get("min_clip_score", 0.0) or 0.0)
    if min_score > 0:
        rows = [r for r in rows if float(r.get("quality_score") or 0.0) >= min_score]
        if len(rows) < 2:
            raise MergeError("too few clips pass min_clip_score")

    # Diversity-first count refinement (merge.dynamic_count). With the real pool now
    # known, honor a per-source cap so cuts spread across distinct clips: when the
    # cap would bind (need > cap) AND enough distinct clips remain to still fill the
    # reel at cut_max, shrink the montage to cap×sources (fewer cuts, all different
    # clips). Small pools that can't fill are left to reuse sources (fill wins).
    if dynamic and rows:
        avail = len(rows)
        cap = int(_clamp(int(cfg.get("max_cuts_per_source", 1)), 0, 8))
        need = -(-n_target // avail)  # ceil cuts/source to reach n_target
        # Fewest DISTINCT cuts that still fill target_total. Each xfade join eats
        # `tdur` of the timeline, so a cut nets (cut_max - tdur) toward the target;
        # ignoring the overlap (old formula) let medium pools shrink one cut short
        # and land the reel ~5s under target. Guard the denominator against tiny
        # cut_max/large tdur.
        denom = max(0.1, cut_max - tdur)
        min_fill = max(2, int(-(-(target_total - tdur) // denom)))
        if cap > 0 and need > cap and avail * cap >= min_fill:
            n_target = min(n_target, avail * cap)

    # Decaption pre-pass: clean burned-in IG captions/watermarks off each resolved
    # source clip ONCE (cached on media.decaptioned_path), so _source_path() below
    # picks up the cleaned file. Lazy-imported + self-gated: no cost when disabled,
    # best-effort per clip (never aborts the merge). Skipped for hand-picked reels
    # that already point at a resized reel_ready_path (no raw source to clean).
    # Per-run override (manual create wizard) wins over the global setting.
    _dc_force = cfg.get("decaption_force")
    _dc_enabled = (get_setting("decaption") or {}).get("enabled") if _dc_force is None else bool(_dc_force)
    if _dc_enabled:
        try:
            from backend.pipeline import decaption
            for r in rows:
                if r.get("reel_ready_path") and Path(r["reel_ready_path"]).exists():
                    continue
                try:
                    updated = decaption.ensure_clean(row=r)
                    if updated.get("decaptioned_path"):
                        r["decaptioned_path"] = updated["decaptioned_path"]
                except Exception as exc:
                    log.warning("merge: decaption pre-pass failed for %s (non-fatal): %s",
                                r.get("id"), exc)
        except Exception as exc:
            log.warning("merge: decaption unavailable (non-fatal): %s", exc)

    # n is the number of CUTS in the final montage (not source videos).
    n = n_target
    # Crossfades overlap, so the final reel = sum(seg_durs) - (n-1)*tdur. Add that
    # lost time back into each cut's target so the rendered reel actually lands on
    # target_total (>=30s rule) instead of falling short by (n-1)*tdur (~6s at n=13).
    # Plus 1 frame/cut headroom: ffmpeg's per-segment `-t` rounds DOWN up to 1 frame,
    # so n cuts lose up to n/FPS (~0.43s at n=13) — enough to dip a 30s target under
    # the floor (observed 29.6s). The headroom keeps the rendered reel >= target.
    def _base(td):
        return (target_total + max(0, n - 1) * td) / max(1, n) + 1.0 / _FPS
    base_seg = _base(tdur)
    # tdur must be shorter than the shortest segment, else xfade offsets go negative.
    if tdur >= base_seg:
        tdur = round(base_seg * 0.4, 3)
        base_seg = _base(tdur)

    # Per-cut durations: beat-aligned (default) or even split. track is reused
    # below as the music bed when audio_mode="music".
    from backend.pipeline.music_fetcher import get_track_for_category
    track: str | None = None
    if cfg.get("beat_sync"):
        track = get_track_for_category(category or _dominant_category(rows) or "nature",
                                       tags=tags or (rows[0].get("tags") if rows else None),
                                       clip_len=target_total)
        seg_durs = (_beat_segment_durations(track, n, target_total, base_seg)
                    if track else [round(base_seg, 3)] * n)
    else:
        seg_durs = [round(base_seg, 3)] * n
    # Rule: every cut is a short rapid taste, never the whole clip.
    seg_durs = [_clamp(d, cut_min, cut_max) for d in seg_durs]

    merge_id = f"mrg_{uuid.uuid4().hex[:12]}"

    # Pull enough cuts per source so even a small pool reaches n_target. Hand-pick
    # stays 1 cut per id. Diversity mode pulls the FEWEST cuts per source needed to
    # fill (ceil(n/sources)) → maximum distinct clips; legacy pulls up to seg_per.
    k_per = (1 if media_ids else seg_per)
    if rows and not media_ids:
        need = -(-n_target // len(rows))  # ceil(n_target / sources)
        k_per = max(1, need) if dynamic else max(k_per, need)

    # Anti-repeat memory (metadata-only): which sub-shots recent same-category reels
    # already used, so a fresh reel avoids them. Auto-select + a category only; empty
    # for hand-pick / no category / dedupe off. `proven` (high-score used segments) is
    # the top-up pool if the fresh pool can't fill the montage.
    dedupe_on = bool(cfg.get("dedupe_enabled", True)) and not media_ids and bool(category)
    usage: dict = {}
    proven: list = []
    if dedupe_on:
        cooldown = int(_clamp(int(cfg.get("subshot_cooldown_reels", 3)), 0, 20))
        try:
            from backend.db import get_recent_merge_usage
            usage, proven = get_recent_merge_usage(category, cooldown)
        except Exception as exc:
            log.warning("merge: usage memory unavailable (non-fatal): %s", exc)

    def _used_windows(mid):
        return [(u["start"], u["dur"], u["reel_rank"]) for u in usage.get(mid, [])]

    # Plan the sub-shots for every source up front, then INTERLEAVE them (rule:
    # cuts from the same video must be mixed through the reel, not back-to-back).
    # Each plan entry is (row, src, clip_dur, [start offsets]); hand-pick uses one
    # offset per id, auto pulls up to k_per distinct windows.
    want_ref = seg_durs[0] if seg_durs else cut_min
    plans: list[tuple] = []
    for row in rows:
        src = _source_path(row)
        if not src:
            log.warning("merge: %s has no usable file on disk — skipped", row.get("id"))
            continue
        clip_dur = _probe_duration(src)
        seg0 = min(want_ref, clip_dur) if clip_dur > 0 else want_ref
        if media_ids:
            st = _best_subshot_start(src, seg0) if cfg.get("scene_aware") else 0.0
            starts = [_clamp(st, 0.0, max(0.0, clip_dur - seg0))] if clip_dur > 0 else [st]
        else:
            starts = _subshots(src, k_per, seg0, clip_dur, bool(cfg.get("scene_aware")), cfg,
                               used=_used_windows(row["id"]))
        plans.append((row, src, clip_dur, starts))

    # Shuffle source order for a mixed-but-even spread, then round-robin: pass p
    # takes the p-th window from each source. Same-source cuts land >= len(plans)
    # apart, so no video's segments ever follow each other (rule 1).
    random.shuffle(plans)
    # Pin the highest hook_score (fallback: quality_score) clip to opener
    # position so the strongest visual always leads the montage.  random.shuffle
    # already varied the rest — we only move the best clip to slot 0.
    # Skip pinning for hand-picked merges: the caller's explicit media_ids order
    # is intentional and must be preserved.
    if plans and not media_ids:
        def _opener_score(p: tuple) -> float:
            row = p[0]
            hs = float(row.get("hook_score") or 0.0)
            return hs if hs > 0 else float(row.get("quality_score") or 0.0)
        best_idx = max(range(len(plans)), key=lambda i: _opener_score(plans[i]))
        if best_idx != 0:
            plans[0], plans[best_idx] = plans[best_idx], plans[0]
    interleaved: list[tuple] = []  # (row, src, clip_dur, start)
    p = 0
    while len(interleaved) < n_target and any(p < len(pl[3]) for pl in plans):
        for row, src, clip_dur, starts in plans:
            if len(interleaved) >= n_target:
                break
            if p < len(starts):
                interleaved.append((row, src, clip_dur, starts[p]))
        p += 1

    # Proven top-up: the fresh pool (after anti-repeat exclusion) couldn't fill the
    # montage → re-cut a few of the HIGHEST-scoring sub-shots past same-category reels
    # used (metadata memory, sorted by score). "Mostly fresh + few proven": only when
    # short, only high-score segments, never a segment already chosen this reel.
    if (cfg.get("proven_topup", True) and proven and not media_ids
            and len(interleaved) < n_target):
        min_sc = _clamp(float(cfg.get("proven_min_score", 0.5)), 0.0, 1.0)
        have = {(e[0].get("id"), round(float(e[3]), 1)) for e in interleaved}
        for pv in proven:
            if len(interleaved) >= n_target:
                break
            if float(pv.get("score") or 0.0) < min_sc:
                continue
            key = (pv["src"], round(float(pv["start"]), 1))
            if key in have:
                continue
            prow = get_media_by_id(pv["src"])
            if not prow:
                continue
            psrc = _source_path(prow)
            if not psrc:
                continue
            interleaved.append((prow, psrc, _probe_duration(psrc), float(pv["start"])))
            have.add(key)

    # Fill guard (regression fix): diversity + anti-repeat can starve a montage —
    # a small category pool, or a REPEAT same-category reel whose fresh windows were
    # all hard-excluded with no proven pool to top up, would fall to a few cuts and
    # ship a ~9s stub. Better a slightly-repeated reel than a short one: re-pull
    # windows from the resolved sources IGNORING the used/dedupe filter until we hit
    # n_target or genuinely run out of distinct fitting windows. Only adds NEW
    # (source, start) windows not already chosen this reel, so no exact dup cuts.
    if not media_ids and len(interleaved) < n_target:
        have_w = {(e[0].get("id"), round(float(e[3]), 2)) for e in interleaved}
        extra_k = max(k_per, -(-n_target // max(1, len(rows))))
        for row in rows:
            if len(interleaved) >= n_target:
                break
            src = _source_path(row)
            if not src:
                continue
            clip_dur = _probe_duration(src)
            seg0 = min(want_ref, clip_dur) if clip_dur > 0 else want_ref
            for st in _subshots(src, extra_k, seg0, clip_dur,
                                bool(cfg.get("scene_aware")), cfg):  # no `used` → all windows
                key = (row.get("id"), round(float(st), 2))
                if key in have_w:
                    continue
                interleaved.append((row, src, clip_dur, st))
                have_w.add(key)
                if len(interleaved) >= n_target:
                    break

    # B4: echo opener as final cut so TikTok loops back to the opening frame.
    if loop_friendly and interleaved and not media_ids:
        interleaved.append(interleaved[0])
        n_target += 1

    # Per-clip content metrics (cv2). Probed ONCE per chosen window here, then
    # threaded into normalize (color-match / adaptive denoise+sharpen) and _fx_segment
    # (adaptive slow-mo / Ken Burns) so no clip is measured twice. None entries when
    # cv2 is unavailable → every adaptive path falls back to the fixed rules.
    adaptive_on = bool(cfg.get("adaptive_fx", True))
    cv2mod = _cv2mod() if (adaptive_on or cfg.get("color_match")) else None
    seg_mets: list[dict | None] = []
    for (_r, _src, _cd, _st) in interleaved:
        if cv2mod is None:
            seg_mets.append(None)
        else:
            w = min(want_ref, _cd) if _cd > 0 else want_ref
            seg_mets.append(_window_metrics(cv2mod, _src, _st, w))

    # Quality-driven per-clip screen-time: stronger clips hold longer, weaker ones
    # flash by. Only when adaptive_fx is on and we actually have metrics; otherwise
    # keep the beat/even uniform durations computed above (regression-safe).
    if adaptive_on and any(m is not None for m in seg_mets):
        rows_i = [e[0] for e in interleaved]
        # Overlap compensation (same as _base above): _adaptive_durations rescales
        # the per-cut lengths to SUM to its target, but the xfade chain later
        # subtracts (n-1)*tdur (crossfade overlap) from that sum. Passing a bare
        # target_total here made the RENDERED reel land at target_total-(n-1)*tdur
        # (~7s short at n=15 → the observed 20-29s). Add the overlap + per-cut frame
        # headroom back so the montage lands ON target (>=30s rule), matching the
        # non-adaptive base_seg path exactly.
        n_cuts = len(seg_mets)
        comp_target = target_total + max(0, n_cuts - 1) * tdur + n_cuts / _FPS
        seg_durs = _adaptive_durations(base_seg, seg_mets, rows_i,
                                       cut_min, cut_max, comp_target)

    # --- Minimum-duration guarantee (final authority over seg_durs) -----------
    # A thin or short-clip category pool can leave the assembled montage well under
    # target_duration_s (observed 9s reels). The min_segments/n_target floors only
    # bound the CUT COUNT — with every cut clamped to cut_max, few short cuts still
    # ship a stub. This is the last word before render: if the planned cuts can't
    # fill target_total, (1) stretch each hold to spread the timeline across the
    # cuts we have — lifting the rapid-cut cut_max cap only as far as the fill
    # demands, each cut still bounded downstream by its own clip length — and (2) if
    # the available footage still can't cover target (every clip very short), loop
    # the montage (reshuffled) until it can. Healthy reels that already reach target
    # keep their beat-synced / adaptive seg_durs untouched (guard never engages).
    _MAX_CUTS = 40  # RAM ceiling on the looped filtergraph
    if interleaved and not media_ids:
        def _projected(durs: list[float], seq: list) -> float:
            """Rendered length if each cut holds its seg_dur, capped by its clip
            length, minus the (n-1) xfade overlaps."""
            tot = 0.0
            for i, (_r, _s, cd, _st) in enumerate(seq):
                d = durs[min(i, len(durs) - 1)] if durs else cut_min
                tot += d if cd <= 0 else min(d, cd)
            return tot - max(0, len(seq) - 1) * tdur

        if _projected(seg_durs, interleaved) + 0.25 < target_total:
            base_seq = list(interleaved)  # loop this fixed block (linear growth)
            while True:
                n = len(interleaved)
                fill_seg = (target_total + max(0, n - 1) * tdur) / max(1, n) + 1.0 / _FPS
                eff_max = max(cut_max, fill_seg)
                durs = [round(_clamp(fill_seg, cut_min, eff_max), 3)] * n
                if (_projected(durs, interleaved) + 0.25 >= target_total
                        or len(interleaved) + len(base_seq) > _MAX_CUTS):
                    seg_durs = durs
                    n_target = n
                    break
                extra = list(base_seq)
                random.shuffle(extra)
                interleaved = interleaved + extra
            log.info("merge: min-duration guarantee → %d cuts, hold=%.2fs (thin pool)",
                     n_target, seg_durs[0] if seg_durs else 0.0)

    # ---- seam: selection is done, everything below is deterministic render ----
    return {
        "plan_version": _PLAN_VERSION,
        "origin": "auto",
        "merge_id": merge_id,
        "video": video_cfg,
        "canvas": {"w": _W, "h": _H, "fps": _FPS},
        "timeline": {
            "n_target": n_target,
            "loop_friendly": loop_friendly,
            "transition": transition,
            "tdur": tdur,
            "joins": None,          # auto path: _resolve_joins derives them post-probe
        },
        "cuts": [
            {
                "order": i,
                "src_media_id": row.get("id"),
                "src_path": src,
                "src_duration_s": clip_dur,
                "start_s": start,
                "dur_s": seg_durs[min(i, len(seg_durs) - 1)] if seg_durs else cut_min,
                "score": round(_clip_quality(seg_mets[i] if i < len(seg_mets) else None,
                                             row), 3),
                "metrics": _plan_metrics(seg_mets[i] if i < len(seg_mets) else None),
                "fx": _fx_decide(i, cfg, seg_mets[i] if i < len(seg_mets) else None),
                "cleanup": _cleanup_decide(cfg, seg_mets[i] if i < len(seg_mets) else None),
            }
            for i, (row, src, clip_dur, start) in enumerate(interleaved)
        ],
        "grade": {"profile": cfg.get("grade") or "",
                  "deband": bool(cfg.get("deband")),
                  "grain": bool(cfg.get("grain")),
                  "vignette": bool(cfg.get("vignette"))},
        "audio": {
            "mode": cfg.get("audio_mode", "music"),
            "fade_s": _clamp(float(cfg.get("music_fade_s", 1.0)), 0.0, 5.0),
            "music_path": cfg.get("music_path"),
            "beat_track_path": track,
            "enter_offset_s": None,   # auto path: _music_enter_offset resolves it
            # Precomputed from ROWS, not cuts: a resolved source that produced no
            # cut still votes on mood/category today, and deriving these from the
            # cut list would silently change a reel's music. See plan risk #1.
            "auto": {
                "category": category or _dominant_category(rows) or "nature",
                "tags": tags or (rows[0].get("tags") if rows else None),
                "mood_match": bool((get_setting("music") or {}).get("mood_match", True)),
                "mood_captions": " ".join(
                    str(r.get("original_caption") or "") for r in rows).strip(),
                "mood_tags": " ".join(
                    " ".join(r.get("tags") or []) if isinstance(r.get("tags"), list)
                    else str(r.get("tags") or "") for r in rows).strip(),
            },
        },
        "persist": {
            "enabled": True,
            # _first() over ROWS (not cuts) — same reason as audio.auto above.
            "inherit": {"category": _first_of(rows, "category"),
                        "tags": _first_of(rows, "tags")},
            "segments_per_clip": k_per,
            "edited_from": None,
        },
        "cleanup_segments": bool(cfg.get("cleanup_segments", True)),
        "_cfg": cfg,
    }


def _cfg_from_plan(plan: dict) -> dict:
    """Reconstruct the render-side cfg from a plan's structured fields.

    Auto plans carry `_cfg` verbatim (the merge settings group as resolved at
    build time) and use it as-is. Editor plans are compiled by editor_edl and
    have no `_cfg` — without this they would render with an empty cfg, silently
    dropping the grade, deband/grain/vignette and audio-fade the user picked.
    Only render-side knobs are rebuilt; every selection knob is already spent."""
    cfg = dict(plan.get("_cfg") or {})
    if cfg:
        return cfg
    grade = plan.get("grade") or {}
    audio = plan.get("audio") or {}
    tl = plan.get("timeline") or {}
    cfg.update({
        "grade": grade.get("profile") or "",
        "deband": bool(grade.get("deband")),
        "grain": bool(grade.get("grain")),
        "vignette": bool(grade.get("vignette")),
        "audio_mode": audio.get("mode", "music"),
        "music_fade_s": float(audio.get("fade_s", 1.0) or 0.0),
        # `or 1.0` would silently un-mute a bed the editor set to 0.0.
        "music_volume": float(audio["volume"] if audio.get("volume") is not None else 1.0),
        "music_path": audio.get("music_path"),
        "transition": tl.get("transition") or "fade",
        "loop_friendly": bool(tl.get("loop_friendly")),
        "cleanup_segments": bool(plan.get("cleanup_segments", True)),
        # Editor plans carry explicit per-join durations, so the auto-path
        # rotation/hard-cut heuristics must not also fire.
        "transition_variety": False,
        "hard_cuts_on_beat": False,
    })
    return cfg


def render(plan: dict, *, persist: bool = True) -> dict:
    """Render a plan to a finished reel. Deterministic: no selection, no cv2,
    no DB reads — everything it needs is in the plan.

    `persist=False` renders without writing a media row (editor preview).
    """
    from backend.pipeline.music_fetcher import get_track_for_category

    origin = plan.get("origin", "auto")
    cfg = _cfg_from_plan(plan)
    video_cfg = plan.get("video") or {}
    merge_id = plan["merge_id"]
    work = MERGE_DIR / merge_id
    work.mkdir(parents=True, exist_ok=True)

    tl = plan.get("timeline") or {}
    n_target = int(tl.get("n_target") or 0)
    loop_friendly = bool(tl.get("loop_friendly"))
    transition = tl.get("transition") or "fade"
    tdur = float(tl.get("tdur") or 0.5)
    plan_joins = tl.get("joins")

    plan_cuts = plan.get("cuts") or []
    # Rebuild the render loop's inputs. `row` is a stub carrying only the fields
    # render actually reads (id for the cut memory, hook/quality for _clip_quality).
    interleaved = [
        ({"id": c.get("src_media_id")},
         c.get("src_path"), float(c.get("src_duration_s") or 0.0),
         float(c.get("start_s") or 0.0))
        for c in plan_cuts
    ]
    seg_durs = [float(c.get("dur_s") or 0.0) for c in plan_cuts]
    seg_mets = [c.get("metrics") for c in plan_cuts]
    plan_scores = [float(c.get("score") or 0.0) for c in plan_cuts]
    plan_fx = [c.get("fx") for c in plan_cuts]
    plan_cleanup = [c.get("cleanup") for c in plan_cuts]

    grade_cfg = plan.get("grade") or {}
    audio_plan = plan.get("audio") or {}
    audio_auto = audio_plan.get("auto") or {}
    category = audio_auto.get("category")
    tags = audio_auto.get("tags")
    track = audio_plan.get("beat_track_path")
    persist_cfg = plan.get("persist") or {}
    inherit = persist_cfg.get("inherit") or {}
    k_per = persist_cfg.get("segments_per_clip")
    persist = persist and bool(persist_cfg.get("enabled", True))

    def _cleanup():
        if plan.get("cleanup_segments", True):
            shutil.rmtree(work, ignore_errors=True)

    def _first(field):
        return inherit.get(field)

    music_enter = 0.0

    # One render at a time — bound CPU under concurrent create-merge calls.
    with _RENDER_SEM:
        seg_files: list[Path] = []
        src_ids: list[str] = []
        seg_met_final: list[dict | None] = []
        seg_starts: list[float] = []   # chosen start offset per rendered cut (memory)
        seg_scores: list[float] = []   # per-cut aesthetic score (memory / proven pool)
        seg_plan_idx: list[int] = []   # rendered position -> plan cut index
        for j, (row, src, clip_dur, start) in enumerate(interleaved):
            if len(seg_files) >= n_target:
                break
            want = seg_durs[min(j, len(seg_durs) - 1)]
            seg = min(want, clip_dur) if clip_dur > 0 else want
            start = _clamp(start, 0.0, max(0.0, clip_dur - seg)) if clip_dur > 0 else start
            met = seg_mets[j] if j < len(seg_mets) else None
            # Editor plans carry frozen cleanup (copied from the parent reel); auto
            # plans let _normalize_segment resolve it from `met` exactly as before.
            cln = plan_cleanup[j] if (origin == "editor" and j < len(plan_cleanup)) else None
            dest = work / f"seg_{len(seg_files):02d}.mp4"
            if _normalize_segment(src, start, seg, dest, video_cfg, cfg, met, cln):
                seg_files.append(dest)
                src_ids.append(row["id"])
                seg_met_final.append(met)
                seg_starts.append(round(float(start), 3))
                # Precomputed at build against the REAL media row; recomputing here
                # would blend against the render-side row stub and drift.
                seg_scores.append(plan_scores[j] if j < len(plan_scores) else 0.0)
                seg_plan_idx.append(j)

        if len(seg_files) < 2:
            _cleanup()
            return {"status": "error", "error": "fewer than 2 segments rendered ok"}

        # Rebuild seg_durs to match the segments that actually rendered.
        final_durs = [_probe_duration(str(f)) for f in seg_files]
        # Per-join transition plan + the post-probe tdur clamp (see _resolve_joins).
        n_joins = max(0, len(final_durs) - 1)
        if plan_joins:
            # Editor plans are authoritative: the user picked these per join, so
            # the rotation/hard-cut heuristics must not override them. Only the
            # safety clamp still applies — a join >= the shortest probed segment
            # drives xfade offsets negative and aborts ffmpeg. A cut that failed
            # to normalize leaves fewer joins than planned, so pad from the tail.
            cap = round(min(final_durs) * 0.4, 3) if final_durs else tdur
            names, durs_j = [], []
            for k in range(n_joins):
                j = plan_joins[k] if k < len(plan_joins) else (plan_joins[-1] if plan_joins else {})
                nm = j.get("name")
                names.append(nm if nm in _XFADE_TRANSITIONS else transition)
                d = float(j.get("duration_s") or tdur)
                durs_j.append(min(d, cap) if d >= min(final_durs) else d)
            variety = names or None
            tdurs = durs_j or None
            tdur = min(durs_j) if durs_j else tdur
        else:
            variety, tdurs, tdur = _resolve_joins(cfg, final_durs, tdur)
        # Per-clip content-adaptive FX (slow-mo + Ken Burns) and rotated transitions.
        # Editor plans render the decisions the user previewed. Auto plans re-derive
        # here so the index parity stays keyed to the RENDERED position exactly as
        # before the split — a cut that failed to normalize shifts every later
        # index, and freezing by plan position would change those reels.
        if origin == "editor":
            seg_fx = [_fx_filter(plan_fx[seg_plan_idx[i]], final_durs[i])
                      for i in range(len(final_durs))]
        else:
            seg_fx = [_fx_segment(i, final_durs[i], cfg, seg_met_final[i])
                      for i in range(len(final_durs))]
        # Memory guard: bake each segment's motion FX (Ken Burns zoompan / slow-mo)
        # into its own file up-front so the delivery filtergraph runs xfade-only.
        # Applying 15+ zoompan instances at once in the single delivery graph is what
        # OOM-kills ffmpeg (SIGKILL/-9) on small-RAM hosts — zoompan buffers scaled
        # frames per input, so peak RAM scales with the cut count. Baking bounds it to
        # one zoompan at a time. FX is duration-preserving, so final_durs (probed
        # above) and the xfade offsets computed from them stay valid.
        if any(fx and fx != "null" for fx in seg_fx):
            for i, fx in enumerate(seg_fx):
                if not fx or fx == "null":
                    continue
                baked = work / f"segfx_{i:02d}.mp4"
                bake_cmd = [
                    "ffmpeg", "-hide_banner", "-i", str(seg_files[i]),
                    "-vf", f"{fx},settb=1/{_FPS},format=yuv420p", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                    "-pix_fmt", "yuv420p", "-threads", "2", "-y", str(baked),
                ]
                r = subprocess.run(bake_cmd, capture_output=True)
                if r.returncode == 0 and baked.exists() and baked.stat().st_size > 0:
                    seg_files[i] = baked   # FX now baked in-file
                    seg_fx[i] = "null"     # → xfade-only for this segment
                else:
                    # Bake failed: leave the segment's inline FX string in place so the
                    # delivery graph still applies it (correctness over the RAM win).
                    log.warning("merge: FX pre-bake failed for seg %d (rc=%s) — "
                                "FX stays inline for this segment", i, r.returncode)
        # Above _XFADE_MAX_INLINE cuts the monolithic xfade graph OOM-kills ffmpeg
        # (N concurrent 1080p decoders). Fold the montage two segments at a time to
        # disk so each ffmpeg opens only 2 inputs, then feed the single folded file
        # to the delivery pass (grade + audio) below. Small reels keep the cheaper
        # single-pass graph. On any fold error, fall back to the monolithic path.
        if len(seg_files) > _XFADE_MAX_INLINE:
            try:
                montage, total = _incremental_xfade(
                    seg_files, final_durs, seg_fx, transition, variety, tdur, tdurs, work)
                seg_files = [montage]
                fc = f"[0:v]settb=1/{_FPS}[vout]"
                log.info("merge: folded %d cuts incrementally (RAM-bounded, total=%.2fs)",
                         len(final_durs), total)
            except Exception as e:
                log.warning("merge: incremental fold failed (%s) — monolithic xfade fallback", e)
                fc, total = _vendor_chain(final_durs, transition, tdur, seg_fx, variety, tdurs)
        else:
            fc, total = _vendor_chain(final_durs, transition, tdur, seg_fx, variety, tdurs)

        # Cinematic post-grade (OpenMontage film grade + grain + vignette) on the
        # assembled montage. When a grade profile is applied the reel is "graded"
        # and video_edit skips the downstream LUT (one coherent look).
        grade_fc, graded = _grade_chain(cfg)
        vlabel = "[vout]"
        if grade_fc:
            fc = fc + f";[vout]{grade_fc}[vgrade]"
            vlabel = "[vgrade]"

        # Audio bed: one mood-matched music track (default) or the longest clip's
        # own audio. Sources are otherwise muted (segments rendered with -an).
        audio_mode = cfg.get("audio_mode", "music")
        fade = _clamp(float(cfg.get("music_fade_s", 1.0)), 0.0, 5.0)
        used_audio: str | None = None
        if audio_mode == "original":
            li = max(range(len(final_durs)), key=lambda i: final_durs[i])
            orig_row = get_media_by_id(src_ids[li])
            used_audio = _source_path(orig_row) if orig_row else None
        else:
            audio_mode = "music"
            used_audio = _safe_music_path(cfg.get("music_path"))
            if not used_audio and cfg.get("beat_sync") and track:
                used_audio = track
            if not used_audio:
                # Caption-mood matching (Enh G) — mirrors video_edit.py's
                # _music_decision. merge_clips previously never derived a mood
                # at all, so merged reels always got category-only music picks
                # even when mood_match is on. Aggregate text across all picked
                # clips (not just one) for a more representative signal.
                # The caption/tag text and dominant category are aggregated at
                # plan time across ALL resolved rows — including sources that
                # produced no cut. Re-deriving them here from the rendered cuts
                # would silently change which track a reel gets.
                mood = None
                if audio_auto.get("mood_match", True):
                    try:
                        from backend.pipeline.music_mood import mood_from_text
                        mood = mood_from_text(audio_auto.get("mood_captions", ""),
                                              audio_auto.get("mood_tags", ""))
                    except Exception:
                        mood = None
                used_audio = get_track_for_category(
                    category or "nature", tags=tags, clip_len=total, mood=mood)

        out_path = MERGE_DIR / f"{merge_id}.mp4"
        crf = str(int(video_cfg.get("crf", 20)))
        preset = str(video_cfg.get("preset", "medium"))
        aidx = len(seg_files)
        cmd = ["ffmpeg", "-hide_banner"]
        for f in seg_files:
            cmd.extend(["-i", str(f)])
        if used_audio and Path(used_audio).exists():
            # Loop the bed so a short track still covers the reel; trim + fade to fit.
            # Enter the track at its first strong onset (the "drop") for a music-bed
            # source, so the montage opens on energy — not the quiet intro. Skip
            # the seek when using a clip's own original audio (keep it in sync).
            enter = (audio_plan.get("enter_offset_s")
                     if audio_plan.get("enter_offset_s") is not None
                     else (_music_enter_offset(used_audio, total)
                           if audio_mode == "music" else 0.0))
            music_enter = enter
            cmd.extend(["-stream_loop", "-1"])
            if enter > 0:
                cmd.extend(["-ss", f"{enter:.3f}"])
            cmd.extend(["-i", used_audio])
            _fade_out = (
                f",afade=t=out:st={max(0.0, total - fade):.3f}:d={fade:.2f}"
                if not loop_friendly else ""
            )
            # Editor exports can scale the bed. 1.0 (every auto merge) emits no
            # `volume` filter at all, so the auto-path filtergraph is byte-identical
            # to what it was before the editor existed.
            _vol = _clamp(_music_volume(cfg), 0.0, 2.0)
            _vol_f = f",volume={_vol:.3f}" if abs(_vol - 1.0) > 1e-6 else ""
            full_fc = (
                fc + f";[{aidx}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d={fade:.2f}"
                f"{_fade_out}{_vol_f}[aout]"
            )
            amap = "[aout]"
        else:
            # Silent stereo bed so the file always carries a valid AAC track.
            cmd.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
            full_fc = fc
            amap = f"{aidx}:a"
            used_audio = None
        # Thread caps bound peak RAM: a long xfade/zoompan filtergraph over 15+
        # 1080p inputs decodes many segments at once and the OS OOM-killer takes
        # ffmpeg down with signal 9 (returncode -9) on small-RAM hosts. Limiting
        # filter + codec threads trades a little speed for a much lower memory
        # ceiling.
        cmd.extend([
            "-filter_complex", full_fc,
            "-filter_complex_threads", "2", "-filter_threads", "2",
            "-map", vlabel, "-map", amap,
            "-c:v", "libx264", "-preset", preset, "-crf", crf, "-threads", "2",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total:.3f}", "-shortest", "-movflags", "+faststart",
            "-y", str(out_path),
        ])
        res = subprocess.run(cmd, capture_output=True)
        # returncode < 0 means killed by a signal; -9 (SIGKILL) is almost always
        # the OOM-killer. Retry once single-threaded with the ultrafast preset,
        # which carries a far smaller memory footprint, before giving up.
        if res.returncode < 0:
            stderr = (res.stderr or b"").decode("utf-8", "replace").strip()
            log.warning("merge: xfade killed by signal %s (likely OOM) — retry ultrafast/1-thread\n%s",
                        -res.returncode, stderr[-500:])
            retry = list(cmd)
            for flag, val in (("-preset", "ultrafast"),
                              ("-threads", "1"),
                              ("-filter_complex_threads", "1"),
                              ("-filter_threads", "1")):
                if flag in retry:
                    retry[retry.index(flag) + 1] = val
            res = subprocess.run(retry, capture_output=True)
        if res.returncode != 0:
            stderr = (res.stderr or b"").decode("utf-8", "replace").strip()
            log.error("merge: xfade ffmpeg failed (%s)\n%s", res.returncode, stderr[-1500:])
            _cleanup()
            return {"status": "error", "error": "xfade render failed"}

    if not persist:
        # Editor preview: render the file, write no media row.
        _cleanup()
        return {"status": "completed", "media_id": None, "path": str(out_path),
                "segments": len(seg_files), "sources": len(set(src_ids)),
                "duration_s": round(total, 2), "source_ids": src_ids}

    upsert_media({
        "id": merge_id,
        "source": "merge",
        "media_type": "VIDEO",
        "status": "resized",
        "reel_ready_path": str(out_path),
        "duration_s": round(total, 2),
        "category": _first("category"),
        "tags": _first("tags"),
        # dict (Supabase JSONB) — same convention as classify_vision, not a JSON string.
        "metadata": {"merge": {
            "source_ids": src_ids,
            "sources": len(set(src_ids)),
            "segments_per_clip": k_per,
            "graded": graded,
            "grade": (cfg.get("grade") or "") if graded else "",
            "transition": transition,
            "n": len(seg_files),
            "audio": audio_mode,
            "music_path": (Path(used_audio).name if used_audio else None),
            "loop_friendly": loop_friendly,
            "fx": {"slow_motion": bool(cfg.get("slow_motion")),
                   "ken_burns": bool(cfg.get("ken_burns")),
                   "transition_variety": bool(cfg.get("transition_variety")),
                   "adaptive_fx": bool(cfg.get("adaptive_fx")),
                   "smart_select": bool(cfg.get("smart_select")),
                   "color_match": bool(cfg.get("color_match")),
                   "deband": bool(cfg.get("deband")),
                   "hard_cuts_on_beat": bool(cfg.get("hard_cuts_on_beat")),
                   "smooth_slowmo": bool(cfg.get("smooth_slowmo")),
                   "deblock": bool(cfg.get("deblock")),
                   "strong_denoise": bool(cfg.get("strong_denoise")),
                   "sharpen": bool(cfg.get("sharpen"))},
            # Per-cut sub-shot memory (src/start/dur/score) — read by
            # get_recent_merge_usage so future same-category reels avoid repeating
            # these windows and can top up from the high-score ones.
            "cuts": [
                {"src": src_ids[i],
                 "start": seg_starts[i] if i < len(seg_starts) else 0.0,
                 "dur": round(final_durs[i], 3),
                 "score": seg_scores[i] if i < len(seg_scores) else 0.0}
                for i in range(len(final_durs))
            ],
            # Trimmed PLAN v1 of what actually rendered — the editor's exact
            # round-trip source (editor_edl.hydrate prefers this over the lossy
            # `cuts` spine above and only then marks a doc approx=True). Field
            # names are a contract with editor_edl._hydrate_from_plan; `metrics`
            # is stripped because get_recent_merge_usage selects this column on
            # every auto merge.
            "plan": {
                "plan_version": _PLAN_VERSION,
                "timeline": {
                    "joins": [
                        {"name": (variety[k % len(variety)] if variety else transition),
                         "duration_s": (tdurs[k] if tdurs and k < len(tdurs) else tdur)}
                        for k in range(max(0, len(final_durs) - 1))
                    ],
                    "loop_friendly": loop_friendly,
                },
                "cuts": [
                    {
                        "src_media_id": src_ids[i],
                        "start_s": seg_starts[i] if i < len(seg_starts) else 0.0,
                        "dur_s": round(final_durs[i], 3),
                        "score": seg_scores[i] if i < len(seg_scores) else 0.0,
                        "cleanup": dict(zip(
                            ("pre", "post"),
                            _cleanup_filters(plan_cleanup[seg_plan_idx[i]]
                                             if i < len(seg_plan_idx) else None))),
                        "fx": (plan_fx[seg_plan_idx[i]] if i < len(seg_plan_idx)
                               else {"slow_motion": None, "ken_burns": None}),
                    }
                    for i in range(len(final_durs))
                ],
                # Enough of the audio decision to round-trip into an EDL exactly:
                # without mode/fade/volume/path the editor would re-open a reel
                # with default music settings and silently change it on export.
                "audio": {
                    "enter_offset_s": music_enter,
                    "mode": audio_mode,
                    "fade_s": round(fade, 3),
                    "volume": round(_clamp(_music_volume(cfg), 0.0, 2.0), 3),
                    # MUSIC_DIR-relative, never absolute: this row outlives the
                    # machine that rendered it (local vs the server data mount).
                    "music_path": (_music_rel(used_audio) if audio_mode == "music" else None),
                },
            },
        }},
    })
    _cleanup()
    log.info("merge: %s ← %d cuts from %d videos (%.1fs) → %s",
             merge_id, len(seg_files), len(set(src_ids)), total, out_path)
    return {"status": "completed", "media_id": merge_id,
            "segments": len(seg_files), "sources": len(set(src_ids)),
            "duration_s": round(total, 2), "source_ids": src_ids}


def run(
    media_ids: list[str] | None = None,
    *,
    category: str | None = None,
    tags: list[str] | None = None,
    count: int | None = None,
    order: list[str] | None = None,
    settings: dict | None = None,
) -> dict:
    """Merge clips into one reel. Returns {"status", "media_id"?, "error"?, ...}.

    Thin wrapper over build_plan() + render() so the public contract is
    unchanged for posts.py, telegram_bot.py and the orchestrator."""
    try:
        plan = build_plan(media_ids, category=category, tags=tags,
                          count=count, order=order, settings=settings)
    except MergeError as exc:
        return {"status": "error", "error": str(exc)}
    return render(plan)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--media-ids", help="comma-separated media ids (hand-pick)")
    ap.add_argument("--category")
    ap.add_argument("--tags", help="comma-separated tags")
    ap.add_argument("--count", type=int)
    a = ap.parse_args()
    ids = [s.strip() for s in a.media_ids.split(",")] if a.media_ids else None
    tag_list = [s.strip() for s in a.tags.split(",") if s.strip()] if a.tags else None
    out = run(media_ids=ids, category=a.category, tags=tag_list, count=a.count)
    print(json.dumps(out, indent=2))
