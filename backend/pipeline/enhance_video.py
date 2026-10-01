"""
Video quality enhancement stage.
Runs after resize, before edit.

Applies (in order):
  1. Optional libvidstab 2-pass stabilization
  2. Sharpening (unsharp)
  3. Contrast + saturation boost (eq)
  4. Fade in/out
  5. Optional Instagram watermark blur (bottom/top/both strip)
  6. Audio loudnorm (EBU R128)

Usage:
    python -m backend.pipeline.enhance_video
    python -m backend.pipeline.enhance_video --media-id abc123
"""

import argparse
import logging
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from backend.config import REELS_READY_DIR
from backend.db import get_media, get_media_by_id, update_media, update_status, get_setting, _use_supabase

log = logging.getLogger(__name__)

_RENDER_SEM = threading.Semaphore(2)   # allow 2 concurrent encodes per stage

# Post-resize dimensions are always 1080×1920
VIDEO_W, VIDEO_H = 1080, 1920
STRIP_H = int(VIDEO_H * 0.12)   # 230px — height of each watermark strip
BOTTOM_Y = VIDEO_H - STRIP_H    # 1690 — top edge of bottom strip

# Shake detection: score below threshold = stable, skip stabilization
SHAKE_SCORE_THRESHOLD = 3.5
SHAKE_SAMPLE_DURATION = 6       # seconds to analyze


def measure_shake_score(path: str) -> float:
    """
    Returns mean inter-frame motion score using tblend+signalstats on a downscaled sample.
    tblend=difference128 maps zero motion → YAVG=128; deviation from 128 = actual motion.
    Typical: <3 stable, 3-8 mild, >8 shaky. Returns 5.0 on any failure (safe default).
    """
    try:
        r = subprocess.run([
            "ffmpeg", "-i", path,
            "-t", str(SHAKE_SAMPLE_DURATION),
            "-vf", (
                "scale=320:-2,"
                "fps=8,"
                "format=yuv420p,"
                "tblend=all_mode=difference128,"
                "signalstats=stat=tout,"
                "metadata=mode=print:file=-"
            ),
            "-f", "null", "-y", "/dev/null",
        ], capture_output=True, text=True, timeout=30)

        scores = re.findall(r"lavfi\.signalstats\.YAVG=([\d.]+)", r.stdout)
        if not scores:
            log.debug("shake_detect: no stats for %s — assuming moderate", path)
            return 5.0
        return sum(abs(float(s) - 128.0) for s in scores) / len(scores)
    except Exception as exc:
        log.warning("shake_detect failed for %s: %s", path, exc)
        return 5.0


def has_libvidstab() -> bool:
    r = subprocess.run(["ffmpeg", "-filters"], capture_output=True, text=True, timeout=10)
    return "vidstabdetect" in (r.stdout + r.stderr)


def get_video_duration(path: str) -> float | None:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=15,
    )
    try:
        return float(r.stdout.strip())
    except (ValueError, AttributeError):
        return None


def has_audio_stream(path: str) -> bool:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=10,
    )
    return bool(r.stdout.strip())


def find_resize_source(media_id: str, current_reel_path: str | None) -> Path | None:
    """
    Return the original post-resize file for re-enhancement.
    Tries _9x16.mp4 naming convention first, then falls back to current reel_ready_path.
    This lets Preview re-enhance without re-stabilizing from scratch.
    """
    candidate = REELS_READY_DIR / f"{media_id}_9x16.mp4"
    if candidate.exists():
        return candidate
    if current_reel_path and Path(current_reel_path).exists():
        return Path(current_reel_path)
    return None


def run_stabilize(src: str, dest: str) -> bool:
    """
    vidstab 2-pass stabilization.
    Pass 1: motion detection → .trf file.
    Pass 2: apply transforms → stabilized video.
    Returns False if libvidstab unavailable or either pass fails.
    """
    if not has_libvidstab():
        log.warning("enhance: libvidstab not available — skipping stabilization")
        return False

    with tempfile.NamedTemporaryFile(suffix=".trf", delete=False) as f:
        trf = f.name

    try:
        r1 = subprocess.run([
            "ffmpeg", "-i", src,
            "-vf", f"vidstabdetect=shakiness=5:accuracy=9:result={trf}",
            "-an", "-f", "null", "-y", "/dev/null",
        ], capture_output=True, timeout=300)

        if r1.returncode != 0:
            log.error("vidstab pass1 failed: %s",
                      r1.stderr.decode("utf-8", "replace")[-500:])
            return False

        r2 = subprocess.run([
            "ffmpeg", "-i", src,
            "-vf", f"vidstabtransform=input={trf}:smoothing=7:optzoom=2:zoom=0:maxshift=-1:interpol=bicubic",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-y", dest,
        ], capture_output=True, timeout=600)

        if r2.returncode != 0:
            log.error("vidstab pass2 failed: %s",
                      r2.stderr.decode("utf-8", "replace")[-500:])
            return False

        return True
    finally:
        Path(trf).unlink(missing_ok=True)


def build_filter_complex(duration: float, remove_watermarks: bool, watermark_position: str, prepend_filter: str = "") -> str:
    """
    Build the FFmpeg filter_complex string.
    Quality chain (unsharp → eq → fade in → fade out) always applied.
    Watermark blur appended when remove_watermarks=True.
    prepend_filter: optional filter string prepended to the quality chain (e.g. vidstabtransform).
    Returns (filter_complex_string, video_output_label).
    """
    fade_out_start = max(0.0, duration - 0.5)
    quality = (
        prepend_filter +
        f"unsharp=5:5:0.8:5:5:0.0,"
        f"eq=contrast=1.08:saturation=1.15:brightness=0.01,"
        f"fade=t=in:st=0:d=0.4,"
        f"fade=t=out:st={fade_out_start:.2f}:d=0.4"
    )

    if not remove_watermarks:
        return f"[0:v]{quality}[vout]", "[vout]"

    pos = watermark_position.lower()

    if pos == "top":
        fc = (
            f"[0:v]{quality}[qual];"
            f"[qual]split=2[main][copy];"
            f"[copy]crop={VIDEO_W}:{STRIP_H}:0:0,boxblur=20:3[blurred];"
            f"[main][blurred]overlay=0:0[vout]"
        )
    elif pos == "both":
        fc = (
            f"[0:v]{quality}[qual];"
            f"[qual]split=3[main][topcopy][botcopy];"
            f"[topcopy]crop={VIDEO_W}:{STRIP_H}:0:0,boxblur=20:3[topblur];"
            f"[botcopy]crop={VIDEO_W}:{STRIP_H}:0:{BOTTOM_Y},boxblur=20:3[botblur];"
            f"[main][topblur]overlay=0:0[mid];"
            f"[mid][botblur]overlay=0:{BOTTOM_Y}[vout]"
        )
    else:  # bottom (default)
        fc = (
            f"[0:v]{quality}[qual];"
            f"[qual]split=2[main][copy];"
            f"[copy]crop={VIDEO_W}:{STRIP_H}:0:{BOTTOM_Y},boxblur=20:3[blurred];"
            f"[main][blurred]overlay=0:{BOTTOM_Y}[vout]"
        )

    return fc, "[vout]"


def enhance_and_render(src: str, dest: str, remove_watermarks: bool, watermark_position: str, prepend_filter: str = "") -> bool:
    """Apply quality enhancement + optional watermark blur, write to dest.

    prepend_filter: optional filter string prepended to the quality chain
    (used by C5 to fold vidstabtransform pass-2 into this single encode).
    """
    duration = get_video_duration(src) or 15.0
    fc, vmap = build_filter_complex(duration, remove_watermarks, watermark_position, prepend_filter)
    audio = has_audio_stream(src)

    cmd = ["ffmpeg", "-i", src, "-filter_complex", fc, "-map", vmap]
    if audio:
        cmd += ["-map", "0:a", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    cmd += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-y", dest,
    ]

    with _RENDER_SEM:
        result = subprocess.run(cmd, capture_output=True, timeout=600)
    if result.returncode != 0:
        log.error("enhance render failed for %s:\n%s",
                  src, result.stderr.decode("utf-8", "replace")[-1500:])
    return result.returncode == 0


def enhance_single(item: dict, settings: dict | None = None) -> dict:
    """
    Enhance one media item.
    settings keys: stabilize, remove_watermarks, watermark_position
    Returns dict with status/output/id.
    """
    settings = settings or {}
    mid = item["id"]

    do_stabilize = settings.get("stabilize", True)
    remove_wm = settings.get("remove_watermarks", False)  # off by default
    wm_pos = settings.get("watermark_position", "bottom")

    src = find_resize_source(mid, item.get("reel_ready_path"))
    if not src:
        log.warning("enhance: no source file for %s — resetting to 'raw' so resize can regenerate", mid)
        update_media(mid, {"status": "raw", "reel_ready_path": None})
        return {"status": "error", "reason": "source_not_found", "id": mid}

    # Check manual skip flag stored in media metadata
    existing_meta = item.get("metadata") or {}
    if not isinstance(existing_meta, dict):
        existing_meta = {}
    if existing_meta.get("skip_stabilize", False):
        log.info("enhance: %s stabilization skipped (manual flag)", mid)
        do_stabilize = False

    # Auto-detect shake level — skip stable videos to avoid over-smoothing.
    # C10: reuse quality_probe shake_score (0-1, 1=stable) when available to skip
    # the measure_shake_score subprocess. Only fast-path clearly-stable clips
    # (>= 0.85 ≈ YDIF < 9); ambiguous values fall through to the live measure.
    if do_stabilize:
        stored_shake = item.get("shake_score")
        if stored_shake is not None and float(stored_shake) >= 0.85:
            log.info("enhance: %s shake_score=%.3f (quality_probe) — stable, skipping stabilization",
                     mid, float(stored_shake))
            do_stabilize = False
        else:
            shake_score = measure_shake_score(str(src))
            log.info("enhance: %s shake_score=%.2f threshold=%.1f", mid, shake_score, SHAKE_SCORE_THRESHOLD)
            if shake_score < SHAKE_SCORE_THRESHOLD:
                log.info("enhance: %s stable — skipping stabilization", mid)
                do_stabilize = False

    log.info("enhance: %s  src=%s  stabilize=%s  wm=%s/%s",
             mid, src.name, do_stabilize, remove_wm, wm_pos)

    # Stabilization (optional, slow — ~1–3 min per video).
    # C5: pass-1 (vidstabdetect) runs standalone; pass-2 (vidstabtransform) is
    # folded into the quality encode via prepend_filter — eliminates the
    # _stabilized.mp4 intermediate file and one ffmpeg subprocess.
    enhance_src = str(src)
    trf_path: str | None = None

    if do_stabilize:
        if has_libvidstab():
            with tempfile.NamedTemporaryFile(suffix=".trf", delete=False) as f:
                trf_path = f.name
            r1 = subprocess.run([
                "ffmpeg", "-i", str(src),
                "-vf", f"vidstabdetect=shakiness=5:accuracy=9:result={trf_path}",
                "-an", "-f", "null", "-y", "/dev/null",
            ], capture_output=True, timeout=300)
            if r1.returncode != 0:
                log.error("vidstab pass1 failed: %s",
                          r1.stderr.decode("utf-8", "replace")[-500:])
                Path(trf_path).unlink(missing_ok=True)
                trf_path = None
        else:
            log.warning("enhance: libvidstab not available — skipping stabilization")

    prepend_filter = (
        f"vidstabtransform=input={trf_path}:smoothing=7:optzoom=2:zoom=0:maxshift=-1:interpol=bicubic,"
        if trf_path else ""
    )
    stabilized_ok = trf_path is not None

    # Quality + watermark enhancement (pass-2 vidstabtransform folded in when stabilized)
    out_path = str(REELS_READY_DIR / f"{mid}_enhanced.mp4")

    # Prevent FFmpeg in-place overwrite when re-enhancing an already-enhanced file
    # (happens after _9x16.mp4 is deleted and reel_ready_path already points to _enhanced.mp4).
    tmp_path = None
    actual_dest = out_path
    if Path(enhance_src).resolve() == Path(out_path).resolve():
        fd, tmp_path = tempfile.mkstemp(dir=str(REELS_READY_DIR), suffix=".mp4")
        os.close(fd)
        actual_dest = tmp_path

    ok = enhance_and_render(enhance_src, actual_dest, remove_wm, wm_pos, prepend_filter=prepend_filter)

    if tmp_path:
        if ok:
            Path(tmp_path).replace(Path(out_path))
        else:
            Path(tmp_path).unlink(missing_ok=True)

    # Clean up the .trf motion-vectors file
    if trf_path:
        Path(trf_path).unlink(missing_ok=True)

    if not ok:
        update_status(mid, "error", "enhance_ffmpeg_failed")
        return {"status": "error", "reason": "ffmpeg_failed", "id": mid}

    update_media(mid, {"status": "enhanced", "reel_ready_path": out_path})

    # Delete the resize source (_9x16.mp4) now that _enhanced.mp4 is canonical —
    # keeps reels_ready from accumulating duplicate files per clip.
    if src != Path(out_path):
        src.unlink(missing_ok=True)
        log.info("enhance: deleted resize source %s (replaced by %s)", src.name, Path(out_path).name)

    # Store enhance metadata in Supabase (JSONB column unavailable in SQLite fallback)
    if _use_supabase():
        try:
            from backend.db import get_supabase, db_retry
            existing_meta = item.get("metadata") or {}
            if not isinstance(existing_meta, dict):
                existing_meta = {}
            db_retry(lambda: get_supabase().table("media").update({
                "metadata": {
                    **existing_meta,
                    "enhance_applied": True,
                    "watermark_removed": remove_wm,
                    "watermark_position": wm_pos,
                    "stabilized": stabilized_ok,
                }
            }).eq("id", mid).execute())
        except Exception as e:
            log.warning("enhance: metadata write failed for %s: %s", mid, e)

    log.info("enhance: ok %s → %s", mid, out_path)
    return {"status": "enhanced", "output": out_path, "id": mid}


def run(media_id: str | None = None) -> dict:
    cfg = get_setting("video", {}) or {}
    settings = {
        "stabilize": cfg.get("auto_stabilize", True),
        "remove_watermarks": cfg.get("remove_watermarks", False),  # off by default
        "watermark_position": cfg.get("watermark_position", "bottom"),
    }

    if media_id:
        item = get_media_by_id(media_id)
        if not item:
            return {"enhanced": 0, "failed": 1, "total": 1,
                    "error": f"media_id {media_id} not found"}
        items = [item]
    else:
        items = get_media(filters={"status": "resized", "media_type": "VIDEO"}) or []
        log.info("enhance: batch — %d resized video(s)", len(items))

    enhanced = failed = 0
    for item in items:
        if item.get("media_type") != "VIDEO":
            continue
        result = enhance_single(item, settings)
        if result["status"] == "enhanced":
            enhanced += 1
        else:
            failed += 1

    log.info("enhance: done  enhanced=%d  failed=%d  total=%d",
             enhanced, failed, len(items))
    return {"enhanced": enhanced, "failed": failed, "total": len(items)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-id", help="Enhance single media item")
    parser.add_argument("--no-stabilize", action="store_true",
                        help="Skip stabilization (faster, for re-enhancement)")
    args = parser.parse_args()
    result = run(media_id=args.media_id)
    print(f"Enhanced: {result['enhanced']}/{result['total']}. Failed: {result['failed']}")
