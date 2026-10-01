"""
Vision classification + hook scoring (Enhancement E).

Looks at the actual footage (not just the caption) to:
  - confirm / set the content category with a confidence score, and
  - assign a hook_score (0-1): how scroll-stopping the opening frames are,
    used to bias auto-create clip selection toward the strongest visuals.

Two providers, chosen by `provider`:
  groq  — Groq Llama-4 vision (fast, free tier, GROQ_API_KEY). Primary.
  local — Moondream via a local Ollama daemon (http://localhost:11434).
          $0, CPU-friendly, lower accuracy — good for background backfill.
  auto  — try groq, fall back to local on any failure (default).

Run modes:
  Pipeline (auto): registered as the `classify_vision` stage after `classify`.
  Manual batch:    python -m backend.pipeline.classify_vision --provider local --limit 50

Results land in media.hook_score (existing column) + media.metadata.vision
(confidence/provider/category). category is only set when the row has none, so
we never fight the Groq text classifier. Everything degrades to a skip on
missing footage, a disabled flag, or provider errors — never raises into the
pipeline.
"""

import argparse
import base64
import json
import logging
import os
import subprocess
import tempfile

import requests

from backend.config import GROQ_API_KEY, ORGANIZED_DIR
from backend.db import get_media, get_media_by_id, update_media, get_setting, _use_supabase

log = logging.getLogger(__name__)

CATEGORIES = ("hidden_gem", "budget", "culture", "nature", "food", "beach")

# Override via env if Groq renames/retires the vision model — avoids a code change.
GROQ_VISION_MODEL = os.environ.get("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "moondream")

_PROMPT = (
    "You are tagging a vertical short-form Reel from a few sampled frames.\n"
    "Pick the single best content category and rate the opening's scroll-stopping appeal.\n"
    f"category must be one of: {', '.join(CATEGORIES)}.\n"
    "hook_score is 0.0-1.0: how visually striking / thumb-stopping the footage is "
    "(vivid colour, motion, a clear subject, a 'wow' frame = high).\n"
    "confidence is 0.0-1.0 for the category choice.\n"
    'Output ONLY JSON: {"category":"<one>","confidence":<0-1>,"hook_score":<0-1>}'
)


# ── Keyframe extraction ────────────────────────────────────────────────


def _duration(path: str) -> float | None:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except (ValueError, AttributeError):
        return None


def _extract_keyframes(video_path: str, n: int = 3) -> list[str]:
    """Sample n frames spread across the clip, downscaled, as base64 JPEGs.
    Downscale to 512px wide to keep vision token cost tiny."""
    dur = _duration(video_path)
    fractions = [0.1, 0.5, 0.9][:n] if dur else [0.0]
    timestamps = [dur * f for f in fractions] if dur else [0.0]
    frames: list[str] = []
    for ts in timestamps:
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.close()
        try:
            subprocess.run(
                ["ffmpeg", "-v", "quiet", "-ss", f"{ts:.2f}", "-i", video_path,
                 "-frames:v", "1", "-vf", "scale=512:-1", "-y", tmp.name],
                capture_output=True,
            )
            if os.path.getsize(tmp.name) > 0:
                with open(tmp.name, "rb") as fh:
                    frames.append(base64.b64encode(fh.read()).decode())
        except Exception as exc:
            log.warning("classify_vision: frame extract failed at %.1fs (%s)", ts, exc)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    return frames


# ── JSON parsing + validation ──────────────────────────────────────────


def _parse(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
    data = json.loads(text)
    category = data.get("category")
    if category not in CATEGORIES:
        category = None
    return {
        "category": category,
        "confidence": _clamp(data.get("confidence")),
        "hook_score": _clamp(data.get("hook_score")),
    }


def _clamp(v) -> float | None:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return None


# ── Providers ──────────────────────────────────────────────────────────


def _classify_groq(frames: list[str]) -> dict:
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)
    content = [{"type": "text", "text": _PROMPT}]
    for f in frames:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{f}"}})
    resp = client.chat.completions.create(
        model=GROQ_VISION_MODEL,
        messages=[{"role": "user", "content": content}],
        max_tokens=120,
        temperature=0.1,
    )
    return _parse(resp.choices[0].message.content)


def _classify_moondream(frames: list[str]) -> dict:
    """Moondream via Ollama. Sends the first frame only (small models handle
    one image best)."""
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": _PROMPT,
            "images": frames[:1],
            "stream": False,
            "format": "json",
        },
        timeout=180,
    )
    r.raise_for_status()
    return _parse(r.json().get("response", ""))


def classify_frames(frames: list[str], provider: str = "auto") -> dict:
    """Dispatch to a provider. auto = groq then local fallback."""
    if not frames:
        raise ValueError("no frames to classify")
    if provider == "groq":
        return _classify_groq(frames)
    if provider == "local":
        return _classify_moondream(frames)
    # auto
    try:
        return _classify_groq(frames)
    except Exception as exc:
        log.warning("classify_vision: groq failed (%s), falling back to local", exc)
        return _classify_moondream(frames)


# ── Batch runner ───────────────────────────────────────────────────────


def _video_path(item: dict) -> str | None:
    # local_path is stored RELATIVE to ORGANIZED_DIR (see index_content.py) —
    # resolve it to an absolute path the same way resize_clips does, otherwise
    # os.path.exists() fails inside the container and the row is silently skipped.
    lp = item.get("local_path")
    if lp:
        p = lp if os.path.isabs(lp) else os.path.join(str(ORGANIZED_DIR), lp)
        if os.path.exists(p):
            return p
    # reel_ready_path is stored absolute (str(dest)) by resize_clips.
    rrp = item.get("reel_ready_path")
    if rrp and os.path.exists(rrp):
        return rrp
    # Local file purged after R2 upload — ffmpeg can stream from HTTP directly.
    r2 = item.get("r2_url")
    if r2 and r2.startswith("http"):
        return r2
    return None


def _persist(item: dict, result: dict, provider: str) -> None:
    updates: dict = {}
    if result.get("hook_score") is not None:
        updates["hook_score"] = result["hook_score"]
    # Confidence/provenance live in metadata (JSONB) — Supabase only, since the
    # SQLite fallback stores metadata as a JSON string we won't deep-merge here.
    if _use_supabase():
        meta = dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}
        meta["vision"] = {
            "category": result.get("category"),
            "confidence": result.get("confidence"),
            "provider": provider,
        }
        updates["metadata"] = meta
    # Only set category when the row has none — never override the text classifier.
    if result.get("category") and not item.get("category"):
        updates["category"] = result["category"]
    if updates:
        update_media(item["id"], updates)


def run(media_id: str | None = None, provider: str = "auto", limit: int | None = None) -> dict:
    """Score footage for hook strength + category. Pipeline calls this with no
    args (auto provider); CLI/background can force a provider + limit."""
    cfg = get_setting("vision") or {}
    if not cfg.get("enabled", True):
        return {"skipped": True, "reason": "vision disabled"}

    if media_id:
        item = get_media_by_id(media_id)
        items = [item] if item else []
    else:
        # Backfill rows without a hook_score yet.
        items = [m for m in get_media(limit=limit or 200) if m.get("hook_score") is None]
        if limit:
            items = items[:limit]

    scored = skipped = failed = 0
    for item in items:
        path = _video_path(item)
        if not path:
            # Log why so an empty run is diagnosable from server logs, not silent.
            log.info(
                "classify_vision: skip %s — no resolvable footage "
                "(local_path=%r reel_ready_path=%r r2_url=%r)",
                item.get("id"), item.get("local_path"),
                item.get("reel_ready_path"), item.get("r2_url"),
            )
            skipped += 1
            continue
        try:
            frames = _extract_keyframes(path)
            if not frames:
                log.warning("classify_vision: skip %s — no frames extracted from %s",
                            item.get("id"), path)
                skipped += 1
                continue
            result = classify_frames(frames, provider=provider)
        except Exception as exc:
            log.warning("classify_vision: %s failed (%s)", item.get("id"), exc)
            failed += 1
            continue
        _persist(item, result, provider)
        scored += 1

    summary = {"scored": scored, "skipped": skipped, "failed": failed, "total": len(items)}
    log.info("classify_vision: provider=%s %s", provider, summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-id", help="Score a single media item")
    parser.add_argument("--provider", choices=["auto", "groq", "local"], default="auto")
    parser.add_argument("--limit", type=int, default=None, help="Max items in batch mode")
    args = parser.parse_args()
    result = run(media_id=args.media_id, provider=args.provider, limit=args.limit)
    print(f"Vision: scored {result.get('scored', 0)}, skipped {result.get('skipped', 0)}, "
          f"failed {result.get('failed', 0)} / {result.get('total', 0)}"
          + (" — skipped (disabled)" if result.get("skipped") is True else ""))
