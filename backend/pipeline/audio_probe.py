"""ffprobe/ffmpeg-based audio fingerprinting.

`probe()`    — coarse stream-presence label + music_source (legacy callers).
`classify()` — hybrid heuristic deciding whether a clip needs background music:
               loudness (volumedetect) gates silence, spectral flatness
               (aspectralstats) separates tonal music/ambient from
               speech/noise (talking, loud voices, raw camera mic).

Music is added (replacing the original track) when a clip has no audio,
is near-silent, or is speech/noise-dominant. Real music or pleasant tonal
ambient is left untouched.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

from backend.config import AUDIO_SILENT_DB, AUDIO_NOISY_DB, AUDIO_SPEECH_FLATNESS
from backend.db import MUSIC_SOURCES  # noqa: F401  — keeps enum import path consistent

# How many leading seconds to analyse (reels are short; bounds ffmpeg cost).
_ANALYZE_SECONDS = 30


def _ffprobe_available():
    return shutil.which("ffprobe") is not None


def _ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def _has_audio_stream(p: Path) -> bool:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_streams", "-of", "json", str(p)],
            stderr=subprocess.DEVNULL, timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return bool(json.loads(out or "{}").get("streams", []))


def probe(path):
    """Return (label, source) for a media file.

    label  — short codec/bitrate summary or empty when no audio
    source — one of MUSIC_SOURCES
    """
    p = Path(path)
    if not p.exists() or not _ffprobe_available():
        return "", "unknown"

    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_streams", "-of", "json", str(p)],
            stderr=subprocess.DEVNULL, timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "", "unknown"

    streams = json.loads(out or "{}").get("streams", [])
    if not streams:
        return "", "none"

    s = streams[0]
    codec = s.get("codec_name", "?")
    bitrate = s.get("bit_rate", "")
    sample_rate = s.get("sample_rate", "")
    channels = s.get("channels", "")
    label = f"{codec} {bitrate}bps {sample_rate}Hz {channels}ch".strip()
    return label, "unknown"


def _measure_loudness(p: Path):
    """Return (mean_db, max_db) via ffmpeg volumedetect, or (None, None)."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-t", str(_ANALYZE_SECONDS),
             "-i", str(p), "-map", "0:a:0", "-af", "volumedetect",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return None, None
    err = proc.stderr or ""
    mean = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", err)
    mx = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", err)
    return (
        float(mean.group(1)) if mean else None,
        float(mx.group(1)) if mx else None,
    )


def _measure_spectral(p: Path):
    """Return (mean_flatness, mean_centroid) via aspectralstats, or (None, None).

    Tonal content (music) has low flatness; speech/crowd/noise is flatter.
    """
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-t", str(_ANALYZE_SECONDS),
             "-i", str(p), "-map", "0:a:0",
             "-af", "aspectralstats=measure=flatness+centroid,ametadata=print:file=-",
             "-f", "null", "/dev/null"],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return None, None
    text = proc.stdout or ""
    flats = [float(m) for m in re.findall(r"flatness=(-?\d+(?:\.\d+)?)", text)]
    cents = [float(m) for m in re.findall(r"centroid=(-?\d+(?:\.\d+)?)", text)]
    mean_flat = sum(flats) / len(flats) if flats else None
    mean_cent = sum(cents) / len(cents) if cents else None
    return mean_flat, mean_cent


def _probe_duration(p: Path) -> float | None:
    """Return media duration in seconds via ffprobe, or None on failure."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(p)],
            stderr=subprocess.DEVNULL, timeout=15,
        )
        return float(out.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            ValueError, AttributeError):
        return None


def classify(path) -> dict:
    """Classify a clip's audio and decide whether it needs background music.

    Returns dict:
        has_stream  bool
        duration    float | None  — total clip length in seconds
        mean_db     float | None
        max_db      float | None
        flatness    float | None
        centroid    float | None
        category    'none'|'silent'|'speech_noise'|'music_ambient'|'unknown'
        needs_music bool   — True → add music as the sole audio track
    """
    p = Path(path)
    base = {"has_stream": False, "duration": None,
            "mean_db": None, "max_db": None,
            "flatness": None, "centroid": None,
            "category": "unknown", "needs_music": False}

    if not p.exists() or not _ffmpeg_available() or not _ffprobe_available():
        return base

    base["duration"] = _probe_duration(p)

    if not _has_audio_stream(p):
        base.update(category="none", needs_music=True)
        return base
    base["has_stream"] = True

    mean_db, max_db = _measure_loudness(p)
    base["mean_db"], base["max_db"] = mean_db, max_db

    # Near-silent (or unmeasurable) → needs music.
    if mean_db is None or mean_db < AUDIO_SILENT_DB:
        base.update(category="silent", needs_music=True)
        return base

    flatness, centroid = _measure_spectral(p)
    base["flatness"], base["centroid"] = flatness, centroid

    # Audible + non-tonal (high flatness) = talking / loud voices / raw mic.
    if flatness is not None and flatness >= AUDIO_SPEECH_FLATNESS:
        base.update(category="speech_noise", needs_music=True)
        return base

    # Loud but flatness unknown → fall back to loudness gate, treat as noise.
    if flatness is None and mean_db >= AUDIO_NOISY_DB:
        base.update(category="speech_noise", needs_music=True)
        return base

    # Tonal / pleasant ambient / real music → leave untouched.
    base.update(category="music_ambient", needs_music=False)
    return base
