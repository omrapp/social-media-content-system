"""
Voiceover stage — edge-tts narration + word-synced burned subtitles (1.8.0).

Design: because we SYNTHESIZE speech from text we already wrote (the caption
hook line), edge-tts hands back exact word-boundary timestamps for free during
the same synthesis call — no separate transcription step (faster-whisper etc.)
is needed, unlike a "narrate pre-existing audio" pipeline. `SubMaker` (part of
the edge-tts package) collects those WordBoundary events into an SRT file that
video_edit.py burns downstream via the ffmpeg `subtitles=` filter.

edge-tts is a pure-Python (aiohttp-based) client with no model weights/native
deps — unlike decaption's YOLO11/onnxruntime backend, no vendor/ImportError-
guard machinery is needed here; it installs like any other requirements.txt
package, and the orchestrator's per-stage try/except already isolates a
missing-dependency failure to just this stage (pipeline still completes).

Feature default-OFF (opt-in via the `voiceover` settings group).

Required Supabase migration (manual — NOT executed by this stage):
    ALTER TABLE media ADD COLUMN voiceover_path TEXT;
    ALTER TABLE media ADD COLUMN voiceover_srt_path TEXT;

Usage:
    python -m backend.pipeline.voiceover --media-id abc123
"""

import argparse
import logging
from pathlib import Path

import edge_tts

from backend.config import VOICEOVER_DIR
from backend.db import get_media_by_id, update_media, get_setting

log = logging.getLogger(__name__)

# Mirror of the settings.py DEFAULTS["voiceover"] block — used when the settings
# row is missing keys (deep-merge safety) or the settings table is unreachable.
_DEFAULTS = {
    "enabled": False,
    "voice": "en-US-AriaNeural",
    "rate": "+0%",
    "narration_source": "caption_hook",  # "caption_hook" | "manual" (manual has no
                                          # dedicated text setting yet — falls back
                                          # to the same caption-hook extraction)
    "subtitles_enabled": True,
    "subtitle_position": "bottom",
    "subtitle_font_size": 28,
    "subtitle_color": "#ffffff",
    "music_duck_volume": 0.08,
}


def _settings() -> dict:
    stored = get_setting("voiceover") or {}
    if not isinstance(stored, dict):
        stored = {}
    return {**_DEFAULTS, **stored}


def _narration_text(row: dict) -> str:
    """Spoken line — reuses the exact first-line-of-caption extraction the intro
    overlay already uses for its on-screen hook text (video_edit._hook_overlay),
    so the narration and any on-screen hook headline say the same thing."""
    from backend.pipeline.video_edit import _hook_overlay
    return _hook_overlay(row)


def _synthesize(text: str, voice: str, rate: str, audio_out: Path, srt_out: Path) -> bool:
    """Single edge-tts pass: MP3 audio + WordBoundary timestamps → SRT.

    Uses the library's own stream_sync() wrapper rather than asyncio.run(): it
    spins a fresh event loop inside a worker thread, so it is safe to call from
    any synchronous context — including one that might already be inside a
    running loop — without the "asyncio.run() cannot be called from a running
    event loop" foot-gun. boundary="WordBoundary" (default is SentenceBoundary)
    is what makes the subtitles word-synced instead of sentence-synced.
    """
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, boundary="WordBoundary")
    submaker = edge_tts.SubMaker()
    with open(audio_out, "wb") as f:
        for chunk in communicate.stream_sync():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)

    if not audio_out.exists() or audio_out.stat().st_size == 0:
        return False
    srt_out.write_text(submaker.get_srt(), encoding="utf-8")
    return True


def run(media_id: str | None = None, voiceover_force: bool | None = None, **kw) -> dict:
    """Orchestrator stage entry.

    Self-gates on the `voiceover.enabled` setting; `voiceover_force` overrides
    that gate for this run only (None = respect the global setting — mirrors
    decaption.py's decaption_force pattern exactly).

    Always called with a single media_id from the per-post pipeline — unlike
    decaption's batch/backfill fallback, no bulk mode is needed here.
    """
    cfg = _settings()
    enabled = cfg.get("enabled") if voiceover_force is None else bool(voiceover_force)
    if not enabled:
        return {"processed": 0, "failed": 0, "total": 0, "skipped": "disabled"}

    if not media_id:
        log.error("voiceover: no media_id given — nothing to narrate")
        return {"processed": 0, "failed": 0, "total": 0, "error": "no media_id"}

    row = get_media_by_id(media_id)
    if not row:
        log.error("voiceover: media_id=%s not found", media_id)
        return {"processed": 0, "failed": 0, "total": 0, "error": f"media {media_id} not found"}

    # Cache hit — generated once, reused forever (same semantics as decaption's
    # decaptioned_path: cheap to regenerate, but there's no reason to).
    if row.get("voiceover_path"):
        return {"processed": 0, "failed": 0, "total": 0, "skipped": "cached"}

    text = _narration_text(row)
    if not text:
        log.info("voiceover: media_id=%s — no caption hook line to narrate, skipping", media_id)
        return {"processed": 0, "failed": 0, "total": 0, "skipped": "no_text"}

    audio_out = VOICEOVER_DIR / f"{media_id}.mp3"
    srt_out = VOICEOVER_DIR / f"{media_id}.srt"

    try:
        ok = _synthesize(text, cfg["voice"], cfg["rate"], audio_out, srt_out)
    except Exception as exc:
        log.error("voiceover: media_id=%s synthesis failed: %s", media_id, exc)
        return {"processed": 0, "failed": 1, "total": 1, "error": str(exc)}

    if not ok:
        log.error("voiceover: media_id=%s — no audio produced", media_id)
        return {"processed": 0, "failed": 1, "total": 1, "error": "no_audio"}

    update_media(media_id, {"voiceover_path": str(audio_out), "voiceover_srt_path": str(srt_out)})
    log.info("voiceover: media_id=%s narrated (%d chars) -> %s", media_id, len(text), audio_out)
    return {"processed": 1, "failed": 0, "total": 1}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Generate TTS narration + burned-subtitle SRT for a reel")
    parser.add_argument("--media-id", required=True, help="Narrate a single media item")
    args = parser.parse_args()
    result = run(media_id=args.media_id)
    print(f"Voiceover: processed={result.get('processed', 0)} failed={result.get('failed', 0)}"
          + (f" — {result['skipped']}" if result.get("skipped") else "")
          + (f" — {result['error']}" if result.get("error") else ""))
