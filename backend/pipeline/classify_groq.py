"""
Groq gpt-oss-120b classifier for new downloads.
Classifies category / tags from caption text.
Rate-limited to 28 req/min (Groq free tier is 30 — stay under).
Only processes new downloads: status='raw' with no category set.

llama-3.3-70b-versatile was decommissioned by Groq (announced 2026-06-17) —
gpt-oss-120b is Groq's recommended replacement.
"""

import json
import random
import time

from groq import Groq

from backend.config import GROQ_API_KEY
from backend.db import get_media, update_media, get_setting

# Trimmed prompt + truncated caption + tight max_tokens keep each request small so
# the Groq free-tier daily token cap (TPD) stretches across many more items.
_CAPTION_MAX_CHARS = 300

_DEFAULT_CATEGORIES = ["hidden_gem", "budget", "culture", "nature", "food", "beach"]


def _category_options() -> list[str]:
    """Configured category taxonomy, falling back to the built-in placeholder
    list. Reads live so a settings change doesn't need a code deploy."""
    try:
        cats = (get_setting("taxonomy") or {}).get("categories")
        if cats:
            return list(cats)
        cats = (get_setting("pillars") or {}).get("taxonomy")
        if cats:
            return list(cats)
    except Exception:
        pass
    return _DEFAULT_CATEGORIES


def _system_prompt() -> str:
    categories = "|".join(_category_options())
    return (
        "Classify short-form video content from its caption. Output ONLY JSON:\n"
        f'{{"category":"<{categories}>","tags":["<keyword>", ...]}}\n'
        "Pick the single best category. tags are 0-5 freeform descriptive "
        "keywords from the caption (topics, objects, mood) — never geography. "
        "Empty/non-English caption: use your best guess."
    )


class DailyTokenCapReached(Exception):
    """Groq TPD (tokens-per-day) cap hit — stop cleanly so a daily cron resumes tomorrow."""

# 28/min gives headroom under the 30/min free-tier cap.
_MIN_INTERVAL = 60.0 / 28
_last_req = 0.0


def _throttle():
    global _last_req
    wait = _MIN_INTERVAL - (time.monotonic() - _last_req)
    if wait > 0:
        time.sleep(wait)
    _last_req = time.monotonic()


def classify_one(caption: str) -> dict:
    client = Groq(api_key=GROQ_API_KEY)
    user_msg = f"Caption: {(caption[:_CAPTION_MAX_CHARS] or '(none)')}"
    system = _system_prompt()
    for attempt in range(5):
        _throttle()
        try:
            resp = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=100,
                temperature=0.1,
            )
            text = resp.choices[0].message.content.strip()
            # strip markdown code fences if model wraps output
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Groq returned non-JSON: {text!r}") from e
        except Exception as e:
            msg = str(e).lower()
            # Daily token cap is not worth retrying — bail so the caller can stop.
            if "tokens per day" in msg or "tpd" in msg:
                raise DailyTokenCapReached(str(e)[:200]) from e
            if "rate_limit" in msg or "429" in msg:
                backoff = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(backoff)
                continue
            raise
    raise RuntimeError("classify_one: all 5 attempts exhausted")


def run(media_id: str | None = None) -> dict:
    """
    Classify new downloads (status='raw', category not yet set).
    Pass media_id to force-classify a single item.
    """
    if media_id:
        row = get_media(filters={"id": media_id}, limit=1)
        items = row if row else []
    else:
        # Paginate ALL status='raw' rows — classifying sets category but leaves
        # status='raw', so a single fixed page would re-fetch already-tagged rows
        # and stall after the first 500. Walk every page, keep only untagged.
        items = []
        offset, page = 0, 500
        while True:
            chunk = get_media(filters={"status": "raw"}, limit=page, offset=offset)
            if not chunk:
                break
            items.extend(m for m in chunk if not m.get("category") or m.get("category") == "uncategorized")
            if len(chunk) < page:
                break
            offset += page

    valid_categories = set(_category_options())
    classified = skipped = failed = 0
    stopped_daily_cap = False

    for item in items:
        caption = item.get("original_caption") or item.get("caption") or ""

        try:
            result = classify_one(caption)
        except DailyTokenCapReached:
            stopped_daily_cap = True
            break
        except Exception:
            failed += 1
            continue

        updates: dict = {}
        if result.get("category") in valid_categories:
            updates["category"] = result["category"]
        tags = result.get("tags")
        if isinstance(tags, list) and tags and not item.get("tags"):
            updates["tags"] = [str(t) for t in tags][:5]

        if updates:
            update_media(item["id"], updates)
            classified += 1
        else:
            skipped += 1

    return {
        "classified": classified,
        "skipped": skipped,
        "failed": failed,
        "total": len(items),
        "stopped_daily_cap": stopped_daily_cap,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--media-id", help="Classify single media item")
    args = parser.parse_args()

    result = run(media_id=args.media_id)
    print(
        f"Classified {result['classified']}, skipped {result['skipped']}, "
        f"failed {result['failed']} / {result['total']}"
        + (" — stopped: daily token cap reached" if result.get("stopped_daily_cap") else "")
    )
