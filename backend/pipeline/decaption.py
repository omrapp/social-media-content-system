"""
Decaption stage — strip burned-in Instagram captions / watermarks from raw clips.

Design: one idempotent, cached per-clip cleaner (`ensure_clean`) reused by both
the create pipeline (as an orchestrator stage) and the merge flow (as a pre-pass).
A clip is cleaned ONCE — the result is persisted on `media.decaptioned_path` and
reused forever; the CPU cost is paid a single time per clip.

The actual ML backend (video-text-remover: YOLO11 detect + OpenCV inpaint on ONNX
Runtime) is vendored + installed MANUALLY by the user (see
backend/scripts/setup_decaption.py). This module IMPORT-GUARDS that backend and
degrades to a pass-through when it — or onnxruntime / the weights — is absent: the
app still boots, the pipeline still runs, clips are simply left uncleaned
(decaptioned stays 0). This stage is best-effort and ALWAYS keeps the clip; it
never marks do_not_use and never raises in a way that aborts the pipeline.

Feature default-OFF (opt-in via the `decaption` settings group).

Usage:
    python -m backend.pipeline.decaption --media-id abc123
"""

import argparse
import logging
import subprocess
from pathlib import Path

from backend.config import DECAPTIONED_DIR, ORGANIZED_DIR
from backend.db import get_media, get_media_by_id, update_media, get_setting

log = logging.getLogger(__name__)

# Mirror of the settings.py DEFAULTS["decaption"] block — used when the settings
# row is missing keys (deep-merge safety) or the settings table is unreachable.
_DEFAULTS = {
    "enabled": False,
    "algorithm": "hybrid",   # hybrid | telea | ns (OpenCV inpaint method)
    "detect_mode": "auto",   # auto | bottom | top | custom
    "custom_bbox": "",       # "x,y,w,h" when detect_mode=custom
    "min_confidence": 0.35,
    "dilate_px": 6,
    "fallback": "blur",      # blur | fill | none
}

_ALGORITHMS = {"hybrid", "telea", "ns"}
_DETECT_MODES = {"auto", "bottom", "top", "custom"}
_FALLBACKS = {"blur", "fill", "none"}

# Log the "backend unavailable" case only once per process to avoid log spam when
# a whole batch of clips flows through with the vendored module absent.
_IMPORT_WARNED = False


def _settings() -> dict:
    stored = get_setting("decaption") or {}
    if not isinstance(stored, dict):
        stored = {}
    cfg = {**_DEFAULTS, **stored}
    # Normalize enums; fall back to defaults on anything unexpected.
    if cfg.get("algorithm") not in _ALGORITHMS:
        cfg["algorithm"] = _DEFAULTS["algorithm"]
    if cfg.get("detect_mode") not in _DETECT_MODES:
        cfg["detect_mode"] = _DEFAULTS["detect_mode"]
    if cfg.get("fallback") not in _FALLBACKS:
        cfg["fallback"] = _DEFAULTS["fallback"]
    try:
        cfg["min_confidence"] = max(0.0, min(float(cfg.get("min_confidence", 0.35)), 1.0))
    except (TypeError, ValueError):
        cfg["min_confidence"] = _DEFAULTS["min_confidence"]
    try:
        cfg["dilate_px"] = max(0, min(int(cfg.get("dilate_px", 6)), 200))
    except (TypeError, ValueError):
        cfg["dilate_px"] = _DEFAULTS["dilate_px"]
    return cfg


def _parse_bbox(s) -> tuple[int, int, int, int] | None:
    """Parse a "x,y,w,h" string into 4 non-negative ints. Returns None when the
    string is empty or malformed (caller then skips the custom region)."""
    if not s or not isinstance(s, str):
        return None
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        return None
    try:
        x, y, w, h = (int(p) for p in parts)
    except (TypeError, ValueError):
        return None
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def _under_decaptioned_dir(path: str) -> bool:
    """True only if `path` resolves INSIDE DECAPTIONED_DIR (no traversal escapes).
    Mirrors the MUSIC_DIR containment check used for overrides.music_path."""
    try:
        return Path(path).resolve().is_relative_to(DECAPTIONED_DIR.resolve())
    except Exception:
        return False


def _resolve_src(row: dict) -> str | None:
    """Absolute on-disk path of the raw source clip (relative local_path anchors to
    ORGANIZED_DIR, same convention as resize_clips)."""
    src = row.get("local_path")
    if not src:
        return None
    if not Path(src).is_absolute():
        src = str(ORGANIZED_DIR / src)
    return src if Path(src).exists() else None


def _probe_dims(path: str) -> tuple[int, int]:
    """(width, height) of the first video stream via ffprobe; (1080, 1920) on
    failure so downstream region math still has sane bounds."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=s=x:p=0", path],
            capture_output=True, timeout=30,
        )
        w, h = (out.stdout or b"").decode().strip().split("x")
        return int(w), int(h)
    except Exception:
        return 1080, 1920


def _region_hint(src: str, mode: str) -> tuple[int, int, int, int] | None:
    """Region hint for detect_mode bottom/top — constrains the detector to a band
    (captions/watermarks almost always sit in the lower/upper third)."""
    w, h = _probe_dims(src)
    if mode == "bottom":
        return (0, int(h * 0.70), w, h - int(h * 0.70))
    if mode == "top":
        return (0, 0, w, int(h * 0.30))
    return None


def _remux_audio(video_only: str, audio_src: str, out: str) -> bool:
    """video-text-remover drops audio — mux the original clip's audio track back
    onto the inpainted video. The audio map is optional (`?`) so silent sources
    still produce a valid file. List-form subprocess, no shell."""
    cmd = [
        "ffmpeg", "-hide_banner",
        "-i", video_only,       # inpainted video (no audio)
        "-i", audio_src,        # original clip (audio source)
        "-map", "0:v:0", "-map", "1:a:0?",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        "-y", out,
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        stderr = (res.stderr or b"").decode("utf-8", "replace").strip()
        log.error("decaption: audio re-mux failed (%s)\n%s", res.returncode, stderr[-1200:])
    return res.returncode == 0


def _blur_fallback(src: str, bbox: tuple[int, int, int, int] | None, out: str) -> bool:
    """Best-effort cleanup when inpaint is unavailable/failed: reuse VideoEditor to
    append an FFmpeg `delogo` filter constrained to `bbox` (region-interpolation
    removal — fits VideoEditor's linear vf chain, unlike a split/overlay boxblur).
    When bbox is unknown, target a default lower-third. Returns True on render."""
    from backend.pipeline.video_edit import VideoEditor

    w, h = _probe_dims(src)
    if bbox is None:
        bbox = (0, int(h * 0.72), w, h - int(h * 0.72))
    x, y, bw, bh = bbox
    # delogo requires the region strictly inside the frame (>=1px border).
    x = max(1, min(int(x), w - 2))
    y = max(1, min(int(y), h - 2))
    bw = max(1, min(int(bw), w - x - 1))
    bh = max(1, min(int(bh), h - y - 1))

    editor = VideoEditor(src)
    editor.filters.append(f"delogo=x={x}:y={y}:w={bw}:h={bh}")
    try:
        return editor.render(out)
    except Exception as exc:
        log.error("decaption: blur fallback render raised for %s: %s", src, exc)
        return False


def ensure_clean(media_id: str | None = None, row: dict | None = None) -> dict:
    """Idempotent, cached per-clip cleaner — the whole brain.

    Returns a dict describing what happened (always safe; never raises out):
        {"decaptioned": 0|1, "decaptioned_path": str|None, ...}

    - decaptioned==1 already on the row → cache hit, no work.
    - vendored backend absent → pass-through (decaptioned stays 0, clip kept).
    - detector finds no overlay → decaptioned=1, decaptioned_path=original (skip inpaint).
    - overlay found → inpaint + re-mux audio → decaptioned_path=<clean file under DECAPTIONED_DIR>.
    - any error → blur/delogo fallback (unless fallback="none") else pass-through.
    """
    global _IMPORT_WARNED

    if row is None:
        if not media_id:
            return {"decaptioned": 0, "error": "no media_id or row"}
        row = get_media_by_id(media_id)
    if not row:
        return {"decaptioned": 0, "error": f"media {media_id} not found"}

    mid = row.get("id")

    # Cache hit — already scanned/cleaned, never re-scan.
    if row.get("decaptioned"):
        return {"decaptioned": 1, "decaptioned_path": row.get("decaptioned_path"), "cached": True}

    # Only video clips carry burned-in captions; leave images/carousels untouched.
    if row.get("media_type") != "VIDEO":
        return {"decaptioned": 0, "skipped": "not_video"}

    src = _resolve_src(row)
    if not src:
        return {"decaptioned": 0, "skipped": "no_source"}

    cfg = _settings()

    # Guarded import of the vendored backend. Absent module / onnxruntime / weights
    # all surface as ImportError → pass-through (writing decaptioned=0 is a no-op).
    try:
        from backend.vendor.vtr import remove_text
    except ImportError as exc:
        if not _IMPORT_WARNED:
            log.warning("decaption: backend unavailable — passing clips through "
                        "uncleaned (run backend/scripts/setup_decaption.py): %s", exc)
            _IMPORT_WARNED = True
        return {"decaptioned": 0, "skipped": "unavailable"}

    # Resolve the detection region hint from detect_mode.
    detect_mode = cfg["detect_mode"]
    bbox: tuple[int, int, int, int] | None = None
    if detect_mode == "custom":
        bbox = _parse_bbox(cfg.get("custom_bbox"))
        if bbox is None:
            log.warning("decaption: %s — detect_mode=custom but custom_bbox %r is "
                        "malformed; skipping (clip kept uncleaned)", mid, cfg.get("custom_bbox"))
            return {"decaptioned": 0, "skipped": "bad_bbox"}
    elif detect_mode in ("bottom", "top"):
        bbox = _region_hint(src, detect_mode)

    inpaint_tmp = DECAPTIONED_DIR / f"{mid}_inpaint.mp4"
    final_out = DECAPTIONED_DIR / f"{mid}_clean.mp4"

    try:
        result = remove_text(
            src, str(inpaint_tmp),
            method=cfg["algorithm"],
            bbox=bbox,
            min_confidence=cfg["min_confidence"],
            dilate_px=cfg["dilate_px"],
            detect_mode=detect_mode,
        ) or {}
    except ImportError as exc:
        # remove_text can raise ImportError at CALL time: the vtr stub does so
        # deliberately, and the real backend does when onnxruntime / the weights
        # are missing (lazy import). Same as a missing module → pass-through
        # (no DB write, no fallback), so an unconfigured box just skips cleaning.
        if not _IMPORT_WARNED:
            log.warning("decaption: backend unavailable — passing clips through "
                        "uncleaned (run backend/scripts/setup_decaption.py): %s", exc)
            _IMPORT_WARNED = True
        return {"decaptioned": 0, "skipped": "unavailable"}
    except Exception as exc:
        log.error("decaption: %s — remove_text raised: %s", mid, exc)
        return _degrade(mid, src, bbox, cfg, final_out)

    # Detector found no overlay → nothing to inpaint. Mark clean so it's never
    # re-scanned; point decaptioned_path at the untouched original.
    if not result.get("found"):
        update_media(mid, {"decaptioned": 1, "decaptioned_path": src})
        log.info("decaption: %s — no overlay text detected (kept original)", mid)
        return {"decaptioned": 1, "decaptioned_path": src, "found": False}

    # Overlay inpainted (video-only) → re-mux the original audio back.
    produced = result.get("out") or str(inpaint_tmp)
    if not Path(produced).exists():
        log.error("decaption: %s — inpaint reported success but output missing: %s", mid, produced)
        return _degrade(mid, src, bbox, cfg, final_out)

    remuxed = _remux_audio(produced, src, str(final_out))
    _unlink(inpaint_tmp)
    if produced != str(inpaint_tmp):
        _unlink(Path(produced))

    if not remuxed:
        return _degrade(mid, src, bbox, cfg, final_out)

    # Confine the persisted path to DECAPTIONED_DIR before writing it to the row.
    if not _under_decaptioned_dir(str(final_out)):
        log.error("decaption: %s — refusing to persist out-of-tree path %s", mid, final_out)
        return {"decaptioned": 0, "skipped": "path_unsafe"}

    update_media(mid, {"decaptioned": 1, "decaptioned_path": str(final_out)})
    log.info("decaption: %s — cleaned %d region(s) → %s", mid, result.get("regions", 0), final_out)
    return {"decaptioned": 1, "decaptioned_path": str(final_out), "found": True,
            "regions": result.get("regions", 0)}


def _degrade(mid, src, bbox, cfg, final_out) -> dict:
    """Inpaint unavailable/failed → blur (delogo) fallback if enabled, else keep
    the clip untouched. ALWAYS keeps the clip; never raises."""
    if cfg.get("fallback") == "none":
        log.info("decaption: %s — inpaint failed, fallback=none → keeping original uncleaned", mid)
        return {"decaptioned": 0, "skipped": "fallback_none"}
    ok = _blur_fallback(src, bbox, str(final_out))
    if ok and _under_decaptioned_dir(str(final_out)):
        update_media(mid, {"decaptioned": 1, "decaptioned_path": str(final_out)})
        log.info("decaption: %s — inpaint failed, applied %s fallback → %s",
                 mid, cfg.get("fallback"), final_out)
        return {"decaptioned": 1, "decaptioned_path": str(final_out), "fallback": cfg.get("fallback")}
    log.warning("decaption: %s — inpaint + fallback both failed → keeping original uncleaned", mid)
    return {"decaptioned": 0, "skipped": "fallback_failed"}


def _unlink(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
    except Exception:
        pass


def run(media_id: str | None = None, **kw) -> dict:
    """Orchestrator stage entry. Self-gates on the `decaption.enabled` setting
    (pass-through when disabled). Resolves rows like resize_clips.run — a single
    media_id, or the batch of status=raw VIDEO clips — and cleans each via the
    cached ensure_clean. Never raises (best-effort stage)."""
    cfg = _settings()
    # Per-run override from the manual create wizard: force enable/disable for this
    # run regardless of the global decaption.enabled setting (None = respect global).
    force = kw.get("decaption_force")
    enabled = cfg.get("enabled") if force is None else bool(force)
    if not enabled:
        return {"decaptioned": 0, "skipped": "disabled"}

    if media_id:
        m = get_media_by_id(media_id)
        if not m:
            log.error("decaption: media_id=%s not found — nothing to clean", media_id)
            return {"decaptioned": 0, "total": 0, "error": f"media_id {media_id} not found"}
        rows = [m]
    else:
        rows = get_media(filters={"media_type": "VIDEO", "status": "raw"}, limit=1000) or []

    log.info("decaption: %d clip(s) to scan", len(rows))
    cleaned = 0
    for row in rows:
        try:
            res = ensure_clean(row=row)
            if res.get("decaptioned"):
                cleaned += 1
        except Exception as exc:  # defensive — ensure_clean already swallows, but keep the stage alive
            log.error("decaption: ensure_clean raised for %s (non-fatal): %s", row.get("id"), exc)

    log.info("decaption: done — decaptioned=%d total=%d", cleaned, len(rows))
    return {"decaptioned": cleaned, "total": len(rows)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Remove burned-in IG captions/watermarks from raw clips")
    parser.add_argument("--media-id", help="Clean a single media item (else all status=raw VIDEO)")
    args = parser.parse_args()
    result = run(media_id=args.media_id)
    print(f"Decaptioned {result.get('decaptioned', 0)}/{result.get('total', 0)}"
          + (f" — {result['skipped']}" if result.get("skipped") else ""))
