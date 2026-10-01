"""
Caption generation: Groq (openai/gpt-oss-120b) primary, OpenRouter
(google/gemma-4-31b-it:free) fallback, DB row last resort.
Refinement / self-critique always go through OpenRouter.

Two modes:
  generate — write a fresh per-platform caption set from category/tags.
             Style: short guide (3-5 lines), factual, informative. No series narrative.
  refine   — polish an existing caption using user feedback.

Output JSON schema (both modes):
  caption                 — English IG caption ≤300 chars (fact hook + 2 info lines + save CTA)
  caption_ar              — Arabic IG caption (natural, not literal)
  caption_yt_title        — ≤97 chars, topic keyword first + #Shorts
  caption_yt_description  — 2-4 sentences with key facts + a useful tip
  caption_tt              — TikTok caption ≤150 chars, fact-first hook
  hashtags_en             — exactly 5 English strings (no #, lowercase)
  hashtags_ar             — 3-5 Arabic strings (no #)
  alt_text                — ≤120 chars literal visual description (English)
"""

import json
import logging
from openai import OpenAI, BadRequestError as OpenAIBadRequestError

from backend.db import (
    get_media_by_id, save_caption, update_media, get_setting,
    _use_supabase, get_supabase, query,
)

log = logging.getLogger(__name__)

SYSTEM_GENERATE = """You write short, high-retention captions for Instagram Reels, TikTok, and YouTube Shorts.

Voice: practical, factual, informative — like a knowledgeable enthusiast sharing the best of this content. NOT a personal story, NOT episodic, NOT first-person diary.

Length: 3–5 lines maximum for the main caption. Every line must add value.

Structure (adapt to what is most interesting about this clip):
• Line 1: open with the category/topic keyword in the first 5–7 words, immediately followed by a striking fact, surprising statistic, or useful tip — both SEO and hook in one line
• Lines 2–3: pick 2 from — an interesting insight, a practical tip, a top highlight, a useful detail (cost / timing / how-to)
• Last line: a call-to-action — the exact style is specified in the user message

Rules:
— Never start with "I", "We", or "POV:"
— No cliffhangers, no episode references, no "follow for part 2"
— Weave in the given category/tags naturally where relevant — don't force them
— Arabic must read naturally, not as a literal translation
— Keep each line punchy — cut filler words

Output ONLY valid JSON (no code fences):
{
  "caption":              "<English caption 3–5 lines, ≤300 chars>",
  "caption_ar":           "<Arabic caption, natural phrasing, ≤300 chars>",
  "caption_yt_title":     "<≤97 chars — destination + experience keyword first + #Shorts>",
  "caption_yt_description": "<2–4 sentences: key facts about the destination + visit tip. Plain text.>",
  "caption_tt":           "<TikTok caption ≤150 chars, fact-first hook>",
  "hashtags_en":          ["tag1","tag2","tag3","tag4","tag5"],
  "hashtags_en_b":        ["alt1","alt2","alt3","alt4","alt5"],
  "hashtags_ar":          ["وسم1","وسم2","وسم3"],
  "alt_text":             "<≤120 chars visual scene description>"
}"""

SYSTEM_CRITIQUE = """You are a short-form hooks editor for a travel guide account.
You receive a caption set as JSON. Judge ONLY the scroll-stopping strength of the hooks
(IG caption first line, TikTok first line, YouTube title). A strong hook is ≤8 words,
specific, and opens with a surprising fact or useful tip — not a personal story.

If every hook is already strong, return the JSON UNCHANGED.
If any hook is weak/generic/vague, rewrite ONLY the weak hook line(s) — keep everything
else (body, Arabic, hashtags, alt_text) byte-for-byte identical.
Preserve both English and Arabic.

Output ONLY the full valid JSON object (no code fences, same schema you received)."""

SYSTEM_REFINE = """You refine short-form captions for Instagram Reels, TikTok, and YouTube Shorts.
Apply the user feedback while keeping the voice: practical, factual, 3–5 lines. No cliffhangers, no episode references.
ALWAYS output BOTH English and Arabic. Arabic must feel natural, not literal.

Output ONLY valid JSON with the same per-platform schema:
{
  "caption":                "<refined English caption ≤300 chars>",
  "caption_ar":             "<refined Arabic caption>",
  "caption_yt_title":       "<≤97 chars>",
  "caption_yt_description": "<2–4 sentences>",
  "caption_tt":             "<TikTok caption ≤150 chars>",
  "hashtags_en":            ["...", "...", "...", "...", "..."],
  "hashtags_en_b":          ["...", "...", "...", "...", "..."],
  "hashtags_ar":            ["...", "...", "..."],
  "alt_text":               "<≤120 chars>"
}"""


def _call_openrouter(system: str, user_msg: str, max_tokens: int = 1600) -> dict:
    from backend.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL

    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY)
    r = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        extra_body={"reasoning": {"enabled": True}},
    )
    text = (r.choices[0].message.content or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
    return json.loads(text)


def _call_groq_json(system: str, user_msg: str, max_tokens: int = 1600) -> dict:
    """Free-tier Groq drafter (Track 3, Enh L). Uses JSON-object response mode
    so the same caption schema comes back; the caller polishes it with the
    self-critique pass. llama-3.3-70b-versatile was decommissioned by Groq
    (announced 2026-06-17) — gpt-oss-120b is Groq's recommended replacement."""
    from groq import Groq
    from backend.config import GROQ_API_KEY

    client = Groq(api_key=GROQ_API_KEY)
    r = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    )
    return json.loads(r.choices[0].message.content)


def _notify_fallback(reason: str, category: str) -> None:
    try:
        from backend.config import TELEGRAM_CHAT_ID
        from backend.pipeline.telegram_bot import send_message
        chat_id = int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None
        if not chat_id:
            return
        send_message(
            chat_id,
            f"⚠️ <b>Caption fallback triggered</b>\n"
            f"Reason: {reason}\n"
            f"Category: {category or '—'}",
        )
    except Exception as exc:
        log.warning("caption: telegram fallback notify failed (%s)", exc)


def _fallback_from_db(category: str) -> dict | None:
    """Return the most recent caption row for this category.
    Reconstructs the caption dict from stored fields; missing platform fields filled
    from the IG caption so downstream code always gets a usable dict."""
    row = None
    if _use_supabase():
        sb = get_supabase()
        resp = (
            sb.table("captions")
            .select("*, media!inner(category)")
            .eq("media.category", category)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        row = (resp.data or [None])[0]
    else:
        rows = query(
            "SELECT c.* FROM captions c JOIN media m ON c.media_id=m.id "
            "WHERE m.category=? ORDER BY c.created_at DESC LIMIT 1",
            (category,),
        )
        row = rows[0] if rows else None

    if not row:
        return None

    caption_en = row.get("caption_en") or ""
    caption_ar = row.get("caption_ar") or ""
    hashtags_en = row.get("hashtags_en") or []
    hashtags_ar = row.get("hashtags_ar") or []
    if isinstance(hashtags_en, str):
        hashtags_en = json.loads(hashtags_en)
    if isinstance(hashtags_ar, str):
        hashtags_ar = json.loads(hashtags_ar)
    return {
        "caption": caption_en,
        "caption_ar": caption_ar,
        "caption_yt_title": caption_en[:97] if caption_en else "",
        "caption_yt_description": caption_en,
        "caption_tt": caption_en[:150] if caption_en else "",
        "hashtags_en": hashtags_en,
        "hashtags_en_b": hashtags_en,
        "hashtags_ar": hashtags_ar,
        "alt_text": row.get("alt_text") or "",
    }


def _build_generate_user_msg(
    category: str,
    tags: list[str] | None,
    context: str,
    performance_hints: str,
) -> str:
    tags_str = ", ".join(tags) if tags else "N/A"
    return (
        f"Category: {category}\n"
        f"Tags: {tags_str}\n"
        f"Context: {context or 'raw footage'}"
        + performance_hints
    )


def generate(
    category: str,
    tags: list[str] | None = None,
    context: str = "",
    *,
    performance_hints: str = "",
    draft_with_groq: bool = False,
) -> dict:
    user_msg = _build_generate_user_msg(
        category, tags, context, performance_hints,
    )
    # Inject the CTA directive so both Haiku and Groq paths produce the right last line.
    cfg_caption = get_setting("caption") or {}
    cta_style = str(cfg_caption.get("cta_style", "send")).strip().lower()
    if cta_style not in ("send", "save", "follow"):
        cta_style = "send"
    _CTA_DIRECTIVES = {
        "send": "CTA style: send-prompt — write a named-persona send line (e.g. \"Send this to the friend who needs to see this\").",
        "save": "CTA style: save — write a save-worthy last line (e.g. \"Save this for later 📌\").",
        "follow": "CTA style: follow — write a follow CTA (e.g. \"Follow for more like this 🔥\").",
    }
    user_msg = user_msg + f"\n{_CTA_DIRECTIVES[cta_style]}"
    # Groq primary (free, fast), OpenRouter fallback (free tier, best-effort),
    # DB fallback last. draft_with_groq is a no-op now — Groq is always tried
    # first — kept as an accepted param so the caption.draft_with_groq setting
    # doesn't break callers.
    try:
        return _call_groq_json(SYSTEM_GENERATE, user_msg)
    except Exception as primary_exc:
        log.warning("caption: Groq failed (%s), trying OpenRouter fallback", primary_exc)
        _notify_fallback(str(primary_exc), category)

    try:
        return _call_openrouter(SYSTEM_GENERATE, user_msg)
    except (OpenAIBadRequestError, Exception) as or_exc:
        log.warning("caption: OpenRouter fallback failed (%s), trying DB fallback", or_exc)
        _notify_fallback(f"OpenRouter also failed: {or_exc}", category)

    db_result = _fallback_from_db(category)
    if db_result:
        log.warning("caption: using DB fallback caption for %s", category)
        return db_result

    raise RuntimeError(
        f"caption generation failed: Groq, OpenRouter, and DB fallback all exhausted "
        f"(category={category!r})"
    )


def refine(
    original_caption: str,
    feedback: str,
    category: str = "",
    tags: list[str] | None = None,
) -> dict:
    tags_str = ", ".join(tags) if tags else "N/A"
    user_msg = (
        f"Original caption:\n{original_caption}\n\n"
        f"Feedback: {feedback}\n"
        f"Category: {category or 'N/A'}\nTags: {tags_str}"
    )
    return _call_openrouter(SYSTEM_REFINE, user_msg)


# ── Self-critique hook pass (Enhancement J) ───────────────────────────


_CRITIQUE_PRESERVE = (
    "caption_ar", "caption_yt_description", "hashtags_en", "hashtags_en_b",
    "hashtags_ar", "alt_text",
)


def _self_critique(result: dict) -> dict:
    """One extra cheap OpenRouter pass that strengthens weak hooks only.

    Sends the generated set back for a hooks-only edit. Returns the improved set,
    but defensively keeps the body/Arabic/hashtag fields from the original if the
    critic dropped or mangled any of them, and falls back to the original on any
    error so a bad second pass can never break generation."""
    try:
        # Headroom above generate's 1600: the critic must re-emit the whole set
        # verbatim, so it needs more than the original generation did.
        improved = _call_openrouter(
            SYSTEM_CRITIQUE, json.dumps(result, ensure_ascii=False), max_tokens=2200,
        )
    except Exception as exc:
        log.warning("caption: self-critique pass failed (%s), keeping original", exc)
        return result
    if not isinstance(improved, dict) or not improved.get("caption"):
        return result
    # Guard against the critic silently dropping non-hook fields.
    for key in _CRITIQUE_PRESERVE:
        if not improved.get(key) and result.get(key):
            improved[key] = result[key]
    return improved


# ── Hashtag policy (denylist + dedupe, Enh L) ─────────────────────────


# Over-saturated / shadow-ban-prone tags that bury a post in a flooded feed.
# Used when the "hashtags".blocked setting is left empty.
_DEFAULT_BLOCKED_TAGS = {
    "travel", "instatravel", "travelgram", "travelblogger", "traveling",
    "photography", "photooftheday", "picoftheday", "instagood", "beautiful",
    "love", "follow", "followforfollow", "f4f", "likeforlike", "l4l",
    "instadaily", "nature", "happy",
}


def _dedupe_filter(tags: list, blocked: set[str]) -> list:
    """Strip leading '#', drop blocked + duplicate tags (case-insensitive),
    preserve order and original casing."""
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if not isinstance(t, str):
            continue
        norm = t.strip().lstrip("#")
        low = norm.lower()
        if not norm or low in blocked or low in seen:
            continue
        seen.add(low)
        out.append(norm)
    return out


def _apply_hashtag_policy(result: dict) -> dict:
    """Remove shadow-ban-prone / duplicate tags from the English hashtag sets.
    Arabic tags are left untouched (the denylist is English-only)."""
    cfg = get_setting("hashtags") or {}
    configured = cfg.get("blocked") or []
    blocked = {t.lower().lstrip("#") for t in configured} or _DEFAULT_BLOCKED_TAGS
    for key in ("hashtags_en", "hashtags_en_b"):
        tags = result.get(key)
        if isinstance(tags, list):
            result[key] = _dedupe_filter(tags, blocked)
            result[key] = result[key][:5]
    return result


# ── Persistence helpers ───────────────────────────────────────────────


def _persist(media_id: str, mode: str, result: dict) -> None:
    combined = (result.get("caption") or "") + "\n\n" + (result.get("caption_ar") or "")
    update = {
        "caption": combined.strip(),
        "caption_ig": result.get("caption"),
        "caption_ig_ar": result.get("caption_ar"),
        "caption_yt_title": result.get("caption_yt_title"),
        "caption_yt_description": result.get("caption_yt_description"),
        "caption_tt": result.get("caption_tt") or result.get("caption"),
        "alt_text": result.get("alt_text"),
    }
    if _use_supabase():
        update["hashtags_en"] = result.get("hashtags_en")
        update["hashtags_en_b"] = result.get("hashtags_en_b")
        update["hashtags_ar"] = result.get("hashtags_ar")
    else:
        # SQLite stores arrays as JSON strings.
        update["hashtags_en"] = json.dumps(result.get("hashtags_en") or [], ensure_ascii=False)
        update["hashtags_en_b"] = json.dumps(result.get("hashtags_en_b") or [], ensure_ascii=False)
        update["hashtags_ar"] = json.dumps(result.get("hashtags_ar") or [], ensure_ascii=False)
    update_media(media_id, {k: v for k, v in update.items() if v is not None})
    save_caption({
        "media_id": media_id,
        "caption_en": result.get("caption"),
        "caption_ar": result.get("caption_ar"),
        "hashtags_en": result.get("hashtags_en"),
        "hashtags_ar": result.get("hashtags_ar"),
        "alt_text": result.get("alt_text"),
        "mode": mode,
    })


# ── Entry point ────────────────────────────────────────────────────────


def run(
    media_id: str | None = None,
    mode: str = "generate",
    feedback: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    context: str = "",
) -> dict:
    """
    If media_id given: fetch media, generate/refine, persist.
    Otherwise: caller supplies category/tags; returns dict without DB write.
    """
    media = None
    if media_id:
        log.info("caption: mode=%s media_id=%s", mode, media_id)
        media = get_media_by_id(media_id)
        if not media:
            log.error("caption: media_id=%s not found in DB", media_id)
            raise ValueError(f"media_id {media_id!r} not found")
        category = category or media.get("category") or ""
        tags = tags if tags is not None else (media.get("tags") or None)

    if mode == "refine":
        if not feedback:
            raise ValueError("refine mode requires feedback")
        original = (media or {}).get("caption") or ""
        result = refine(original, feedback, category or "", tags)
    else:
        if not category:
            hint = (f"media_id={media_id} has no 'category' set — classify it first "
                    f"(Groq classifier) before generating a caption."
                    if media_id else
                    "generate mode requires a 'category' argument.")
            log.error("caption: %s", hint)
            raise ValueError(hint)
        log.info("caption: generate category=%s tags=%s", category, tags)
        cfg = get_setting("caption") or {}
        hints = ""
        if cfg.get("use_feedback", True):
            try:
                from backend.pipeline.feedback_aggregator import performance_hints_block
                hints += performance_hints_block(category or None)
            except Exception as exc:
                log.warning("caption: performance hints unavailable (%s)", exc)
        _trend_topics: list[str] = []
        if cfg.get("use_trends", True):
            try:
                from backend.pipeline.trends_fetcher import trends_block, fetch_trends
                hints += trends_block()
                _trend_topics = fetch_trends()  # hits day cache
            except Exception as exc:
                log.warning("caption: trend hints unavailable (%s)", exc)
        if cfg.get("use_hook_library", True):
            try:
                from backend.pipeline.hook_library import hook_block
                trend_topic = _trend_topics[0] if _trend_topics else ""
                hints += hook_block(category or None, None, trend_topic)
            except Exception as exc:
                log.warning("caption: hook library unavailable (%s)", exc)
        result = generate(
            category, tags, context,
            performance_hints=hints,
            draft_with_groq=cfg.get("draft_with_groq", False),
        )
        if cfg.get("self_critique", True):
            result = _self_critique(result)

    result = _apply_hashtag_policy(result)

    if media_id and media:
        _persist(media_id, mode, result)
        log.info("caption: persisted for media_id=%s (mode=%s)", media_id, mode)

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--context", default="")
    parser.add_argument("--mode", choices=["generate", "refine"], default="generate")
    parser.add_argument("--feedback", default="")
    parser.add_argument("--media-id", default=None)
    args = parser.parse_args()

    cli_tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    result = run(
        media_id=args.media_id,
        mode=args.mode,
        feedback=args.feedback or None,
        category=args.category or None,
        tags=cli_tags,
        context=args.context,
    )
    print(f"\n=== EN CAPTION (IG) ===\n{result.get('caption', '')}")
    print(f"\n=== AR CAPTION (IG) ===\n{result.get('caption_ar', '')}")
    print(f"\n=== YT TITLE ===\n{result.get('caption_yt_title', '')}")
    print(f"\n=== YT DESCRIPTION ===\n{result.get('caption_yt_description', '')}")
    print(f"\n=== TT CAPTION ===\n{result.get('caption_tt', '')}")
    print(f"\n=== EN HASHTAGS ===\n{' '.join('#' + t for t in (result.get('hashtags_en') or []))}")
    print(f"\n=== AR HASHTAGS ===\n{' '.join('#' + t for t in (result.get('hashtags_ar') or []))}")
    print(f"\n=== ALT TEXT ===\n{result.get('alt_text', '')}")
