"""
Shared luma-based thumbnail extraction used by resize_clips and upload_r2.
Picks the brightest non-black frame to avoid black intro/fade frame thumbnails.

Also provides brand_thumbnail() for baking the branding bottom bar onto a
still image (thumbnail) after extraction.
"""
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

BRIGHT_ENOUGH = 60.0  # mean luma (0-255) we accept and stop searching early


def _probe_duration(video_path: str) -> float | None:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", video_path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except (ValueError, AttributeError):
        return None


def _frame_luma(video_path: str, ts: float) -> float | None:
    """Mean luma (0-255) of the frame at timestamp ts. None on failure."""
    r = subprocess.run(
        ["ffmpeg", "-ss", f"{ts:.3f}", "-i", video_path,
         "-frames:v", "1", "-vf", "signalstats,metadata=print",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for stream in (r.stderr or "", r.stdout or ""):
        for line in stream.splitlines():
            if "YAVG" in line:
                try:
                    return float(line.split("=")[-1].strip())
                except ValueError:
                    pass
    return None


def pick_bright_frame(video_path: str, thumb_path: str) -> bool:
    """
    Extract a thumbnail from video_path, avoiding black intro/fade frames.
    Samples 6 timestamps across the clip, measures mean luma, picks the
    brightest. Falls back to midpoint then first frame on failure.

    Returns True if thumbnail was written successfully.
    """
    duration = _probe_duration(video_path)
    if duration and duration > 0:
        candidates = [duration * f for f in (0.1, 0.25, 0.4, 0.55, 0.7, 0.85)]
    else:
        candidates = [1.0]

    best_ts, best_luma = None, -1.0
    for ts in candidates:
        luma = _frame_luma(video_path, ts)
        if luma is None:
            continue
        if luma > best_luma:
            best_luma, best_ts = luma, ts
        if luma >= BRIGHT_ENOUGH:
            break

    # No luma reading → midpoint seek.
    if best_ts is None:
        best_ts = (duration / 2) if duration and duration > 0 else 1.0

    cmd = ["ffmpeg", "-ss", f"{best_ts:.3f}", "-i", video_path,
           "-frames:v", "1", "-q:v", "3", "-y", thumb_path]
    if subprocess.run(cmd, capture_output=True).returncode == 0:
        return True
    # Last-ditch: first frame.
    cmd = ["ffmpeg", "-i", video_path, "-frames:v", "1", "-q:v", "3", "-y", thumb_path]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def brand_thumbnail(
    thumb_path: str,
    location: str | None,
    handle: str = "",
    bar_h: int = 45,
    font_path: str = "",
    bar_bg_color: str = "#ffffff",
    text_color: str = "#000000",
    bar_opacity: float = 1.0,
    bar_position: str = "bottom",
    location_side: str = "left",
    handle_side: str = "right",
    custom_text: str = "",
    font_size: int = 0,
) -> bool:
    """Bake the branding bar onto a thumbnail image in-place.

    FFmpeg cannot read and write the same file in one pass, so the
    branded output is written to a sibling temp file and then
    os.replace atomically overwrites the original.

    Returns True on success, False if ffmpeg failed (original untouched).
    """
    from backend.pipeline.overlay import build_branding_filters

    filters = build_branding_filters(
        location, handle,
        bar_h=bar_h, font_path=font_path,
        bar_bg_color=bar_bg_color, text_color=text_color,
        bar_opacity=bar_opacity, bar_position=bar_position,
        location_side=location_side, handle_side=handle_side,
        custom_text=custom_text,
        font_size=font_size,
    )
    if not filters:
        return True  # nothing to draw

    vf = ",".join(filters)
    thumb = Path(thumb_path)
    tmp = thumb.with_suffix(".brand_tmp.jpg")
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", str(thumb), "-vf", vf, "-q:v", "3", "-y", str(tmp)],
            capture_output=True,
        )
        if result.returncode == 0 and tmp.exists():
            os.replace(str(tmp), thumb_path)
            return True
        log.warning(
            "brand_thumbnail: ffmpeg failed (rc=%d) for %s",
            result.returncode, thumb_path,
        )
        tmp.unlink(missing_ok=True)
        return False
    except Exception as exc:
        log.warning("brand_thumbnail: exception for %s: %s", thumb_path, exc)
        tmp.unlink(missing_ok=True)
        return False
