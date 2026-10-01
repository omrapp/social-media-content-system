"""
quality_probe — cheap FFmpeg blur/shake scoring for raw clips (0.6.0).

Runs as the FIRST pipeline stage (before resize) so junk footage is scored and,
when enforcement is on, rejected before any expensive resize/enhance/edit work.

Two single-pass FFmpeg measures (CPU-only, no extra deps), sampled over the
leading seconds at low fps/resolution to bound cost:

  blur_score   sharpness 0-1  — edgedetect→signalstats YAVG (more edges = sharper)
  shake_score  stability 0-1  — signalstats YDIF (inter-frame change; lower = steadier)
  quality_score = SHARP_WEIGHT*blur + (1-SHARP_WEIGHT)*shake   (0-1, higher = better)

Behaviour:
  - Always stores blur_score/shake_score/quality_score on the media row.
  - selection.min_quality_score == 0  → measure-only (never rejects). Default at
    launch so real scores can be collected and a threshold calibrated.
  - selection.min_quality_score  > 0  → a clip scoring below it is flagged
    do_not_use=1 (skipped by every future selection) and the stage raises
    QualityRejected so the orchestrator aborts the pipeline (no half-built reel).
  - Idempotent: a clip that already has quality_score is not re-probed unless
    force=True (so orchestrator retries after a reject are near-free).

CLI:
  python -m backend.pipeline.quality_probe --media-id <id>
  python -m backend.pipeline.quality_probe --backfill [--limit N] [--force]
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
from pathlib import Path

from backend.config import ORGANIZED_DIR
from backend.db import (
    get_media, get_media_by_id, get_setting, update_media,
)

log = logging.getLogger(__name__)

# Sampling window — reels are short; bound ffmpeg cost.
_ANALYZE_SECONDS = 8
_SAMPLE_FPS = 5
_SAMPLE_WIDTH = 320

# Normalization references (tunable). Edge/diff luma are ~0-255; these map a
# "typical good clip" near 1.0. Calibrate from collected scores before enforcing.
_SHARP_REF = 40.0   # edge-map YAVG at/above this = fully sharp
_SHAKE_REF = 60.0   # inter-frame YDIF at/above this = maximally shaky
_SHARP_WEIGHT = 0.6  # quality_score weighting (blur vs stability)


class QualityRejected(RuntimeError):
    """Raised when a clip scores below selection.min_quality_score (enforcement on)."""


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _resolve_source(row: dict) -> Path | None:
    src = row.get("local_path")
    if not src:
        return None
    p = Path(src)
    if not p.is_absolute():
        p = ORGANIZED_DIR / src
    return p if p.exists() else None


def _signalstats_yavg(p: Path, edge: bool) -> float | None:
    """Mean signalstats.YAVG over sampled frames. edge=True runs edgedetect
    first (→ sharpness); edge=False reads raw luma diff later via YDIF."""
    vf = f"fps={_SAMPLE_FPS},scale={_SAMPLE_WIDTH}:-2"
    if edge:
        vf += ",edgedetect=low=0.1:high=0.4"
    vf += ",signalstats,metadata=print"
    return _mean_metadata(p, vf, "lavfi.signalstats.YAVG")


def _signalstats_ydif(p: Path) -> float | None:
    """Mean signalstats.YDIF (avg luma difference between consecutive frames)."""
    vf = f"fps={_SAMPLE_FPS},scale={_SAMPLE_WIDTH}:-2,signalstats,metadata=print"
    return _mean_metadata(p, vf, "lavfi.signalstats.YDIF")


def _mean_metadata(p: Path, vf: str, key: str) -> float | None:
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-t", str(_ANALYZE_SECONDS),
             "-i", str(p), "-vf", vf, "-an", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        log.warning("quality_probe: ffmpeg timeout reading %s for %s", key, p.name)
        return None
    # metadata=print writes "key=value" lines to stderr.
    text = (proc.stderr or "") + (proc.stdout or "")
    vals = [float(m) for m in re.findall(rf"{re.escape(key)}=(-?\d+(?:\.\d+)?)", text)]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def probe_file(p: Path) -> dict | None:
    """Return {blur_score, shake_score, quality_score} for a video, or None on failure."""
    if not _ffmpeg_available():
        log.warning("quality_probe: ffmpeg not on PATH — cannot score %s", p.name)
        return None

    edge_yavg = _signalstats_yavg(p, edge=True)
    ydif = _signalstats_ydif(p)
    if edge_yavg is None and ydif is None:
        log.error("quality_probe: no measurable frames in %s (corrupt / image-only?)", p.name)
        return None

    blur_score = _clamp01((edge_yavg or 0.0) / _SHARP_REF)
    # Higher YDIF = more inter-frame change = shakier → invert for a stability score.
    shake_score = _clamp01(1.0 - (ydif or 0.0) / _SHAKE_REF)
    quality = _SHARP_WEIGHT * blur_score + (1.0 - _SHARP_WEIGHT) * shake_score

    return {
        "blur_score": round(blur_score, 4),
        "shake_score": round(shake_score, 4),
        "quality_score": round(quality, 4),
    }


def _score_one(row: dict, cfg: dict, force: bool) -> dict:
    """Probe+store a single media row. Returns a per-clip outcome dict.
    Raises QualityRejected when enforcement is on and the clip fails."""
    mid = row["id"]

    if row.get("media_type") != "VIDEO":
        log.info("quality_probe: skip media_id=%s — not a VIDEO (%s)", mid, row.get("media_type"))
        return {"media_id": mid, "skipped": "not_video"}

    if row.get("quality_score") is not None and not force:
        log.info("quality_probe: media_id=%s already scored (%.3f) — skip (use --force to redo)",
                 mid, row["quality_score"])
        score = row["quality_score"]
    else:
        src = _resolve_source(row)
        if src is None:
            log.error("quality_probe: media_id=%s source file missing on disk: %s",
                      mid, row.get("local_path"))
            return {"media_id": mid, "skipped": "no_source"}

        log.info("quality_probe: media_id=%s probing %s", mid, src.name)
        scores = probe_file(src)
        if scores is None:
            log.error("quality_probe: media_id=%s probe failed — leaving unscored", mid)
            return {"media_id": mid, "failed": "probe_error"}
        update_media(mid, scores)
        score = scores["quality_score"]
        log.info("quality_probe: media_id=%s scored quality=%.3f (blur=%.3f shake=%.3f)",
                 mid, score, scores["blur_score"], scores["shake_score"])

    threshold = cfg["min_quality_score"]
    if threshold > 0 and score < threshold:
        update_media(mid, {"do_not_use": 1})
        log.warning("quality_probe: media_id=%s REJECTED quality=%.3f < min_quality_score=%.3f "
                    "— flagged do_not_use, aborting pipeline. fix: lower selection.min_quality_score "
                    "or pick a sharper/steadier clip", mid, score, threshold)
        raise QualityRejected(
            f"media_id={mid} quality_score={score:.3f} below min_quality_score={threshold:.3f}"
        )

    return {"media_id": mid, "quality_score": score}


def _cfg() -> dict:
    sel = get_setting("selection") or {}
    try:
        thr = float(sel.get("min_quality_score", 0.0))
    except (TypeError, ValueError):
        thr = 0.0
    return {
        "enabled": bool(sel.get("quality_probe_enabled", True)),
        "min_quality_score": thr,
    }


def run(media_id: str | None = None, backfill: bool = False,
        limit: int = 500, force: bool = False) -> dict:
    """Pipeline-stage entry. Single clip (media_id) or --backfill batch.

    When selection.quality_probe_enabled is False the stage no-ops (lets the
    pipeline proceed untouched)."""
    cfg = _cfg()
    if not cfg["enabled"]:
        log.info("quality_probe: disabled in settings — skipping")
        return {"processed": 0, "skipped": 1, "reason": "disabled"}

    if media_id:
        row = get_media_by_id(media_id)
        if not row:
            log.error("quality_probe: media_id=%s not found", media_id)
            return {"processed": 0, "failed": 1, "error": "not_found"}
        rows = [row]
    elif backfill:
        rows = [r for r in (get_media(filters={"media_type": "VIDEO", "status": "raw"},
                                      limit=limit) or [])
                if force or r.get("quality_score") is None]
        log.info("quality_probe: backfill — %d clip(s) to score", len(rows))
    else:
        log.warning("quality_probe: no media_id and not --backfill — nothing to do")
        return {"processed": 0, "skipped": 1}

    processed = failed = skipped = 0
    for row in rows:
        outcome = _score_one(row, cfg, force)  # may raise QualityRejected (single-clip path)
        if "quality_score" in outcome:
            processed += 1
        elif "failed" in outcome:
            failed += 1
        else:
            skipped += 1

    log.info("quality_probe: done — processed=%d failed=%d skipped=%d total=%d",
             processed, failed, skipped, len(rows))
    return {"processed": processed, "failed": failed,
            "skipped": skipped, "total": len(rows)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-id")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(media_id=args.media_id, backfill=args.backfill,
                 limit=args.limit, force=args.force)
    print(result)
