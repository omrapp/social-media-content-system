"""
Scheduler library — multi-platform publishing primitives.
Called by daemon.py (auto-publish) and API routes (approve/reject/reschedule).
"""

import json
import datetime as dt
import logging
import random
import requests
import time

from backend.config import IG_TOKEN, IG_USER_ID, IG_API_BASE, QUEUE_FILE
from backend.db import (
    create_post, update_post, update_media, get_posts, get_media_by_id, get_setting,
)

log = logging.getLogger(__name__)


# ── IG API ────────────────────────────────────────────────────────────────────

def _post_reel_to_ig(media_url: str, caption: str) -> str:
    """Upload + publish a Reel. Returns the published IG media id."""
    r = requests.post(f"{IG_API_BASE}/{IG_USER_ID}/media", data={
        "media_type": "REELS",
        "video_url": media_url,
        "caption": caption,
        "access_token": IG_TOKEN,
    }).json()
    if "id" not in r:
        raise RuntimeError(f"IG media creation failed: {r.get('error', r)}")
    container_id = r["id"]

    for _ in range(30):
        s = requests.get(
            f"{IG_API_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": IG_TOKEN},
        ).json()
        status_code = s.get("status_code", "")
        if status_code == "FINISHED":
            break
        if status_code == "ERROR":
            raise RuntimeError(f"IG container error: {s}")
        time.sleep(10)

    pub = requests.post(f"{IG_API_BASE}/{IG_USER_ID}/media_publish", data={
        "creation_id": container_id,
        "access_token": IG_TOKEN,
    }).json()
    if "id" not in pub:
        raise RuntimeError(f"IG media publish failed: {pub.get('error', pub)}")
    return pub["id"]


def _build_caption(post: dict) -> str:
    hashtags_en = " ".join("#" + t for t in (post.get("hashtags_en") or []))
    hashtags_ar = " ".join("#" + t for t in (post.get("hashtags_ar") or []))
    parts = [post.get("caption", ""), hashtags_en, hashtags_ar]
    return "\n\n".join(p for p in parts if p).strip()


def _platform_hashtag_suffix(platform: str) -> list[str]:
    """Read per-platform hashtag suffix from settings (story-arc tailoring)."""
    platforms_cfg = get_setting("platforms") or {}
    key_map = {"instagram": "instagram", "youtube": "youtube", "tiktok": "tiktok"}
    sub = platforms_cfg.get(key_map.get(platform, platform), {})
    if isinstance(sub, dict):
        return sub.get("hashtag_suffix") or []
    return []


def _build_platform_caption(post: dict, platform: str) -> str:
    """
    Per-platform caption assembly with hashtag suffix injection.
    Falls back to combined caption if per-platform field is empty.
    """
    if platform == "instagram":
        body = post.get("caption_ig") or post.get("caption") or ""
        body_ar = post.get("caption_ig_ar") or ""
        if body and body_ar and body_ar not in body:
            body = f"{body}\n\n{body_ar}"
    elif platform == "tiktok":
        body = post.get("caption_tt") or post.get("caption_ig") or post.get("caption") or ""
        body_ar = post.get("caption_ig_ar") or ""
        if body and body_ar and body_ar not in body:
            body = f"{body}\n\n{body_ar}"
    else:  # youtube and any future platform
        # Use platform-specific EN description; fall back to combined caption.
        body = post.get("caption_yt_description") or post.get("caption") or ""
        body_ar = post.get("caption_ig_ar") or ""
        if body and body_ar and body_ar not in body:
            body = f"{body}\n\n{body_ar}"

    # CTA injection (monetize settings).
    try:
        from backend.db import get_setting as _get_setting
        monetize = _get_setting("monetize") or {}
        if monetize.get("enabled", False):
            cta_platforms = monetize.get("platforms", ["instagram", "tiktok", "youtube"])
            if platform in cta_platforms:
                cta = monetize.get("cta_text", "").strip()
                if cta:
                    body = body + "\n\n" + cta
                if platform == "youtube":
                    yt_link = monetize.get("youtube_link", "").strip()
                    if yt_link:
                        body = body + "\n" + yt_link
    except Exception as _cta_exc:
        log.warning("scheduler: CTA injection failed (%s)", _cta_exc)

    # Blend curated viral hashtags with LLM-generated tags per platform.
    try:
        from backend.pipeline.hashtag_engine import blend as blend_hashtags
        post_seq = abs(hash(post.get("id", ""))) % 1000 if post.get("id") else 0
        en_tags_raw = _as_tags(post.get("hashtags_en", []))
        en_tags = blend_hashtags(
            llm_tags=en_tags_raw,
            platform=platform,
            category=post.get("category"),
            post_seq=post_seq,
        )
    except Exception as _blend_exc:
        log.warning("scheduler: hashtag blend failed (%s), falling back to raw tags", _blend_exc)
        en_tags = _as_tags(post.get("hashtags_en") or [])

    hashtags_ar = list(post.get("hashtags_ar") or [])
    tags_en = " ".join("#" + t for t in en_tags)
    tags_ar = " ".join("#" + t for t in hashtags_ar)
    # All platforms include Arabic hashtags in visible caption/description.
    parts = [body, tags_en, tags_ar]
    return "\n\n".join(p for p in parts if p).strip()


def _as_tags(value) -> list[str]:
    """Hashtag arrays come back as a list (Supabase) or JSON string (SQLite)."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    return list(value or [])


def _pick_hashtag_variant(media: dict) -> tuple[str, list[str]]:
    """A/B hashtag assignment (Enhancement D). Coin-flips between the primary
    set (A) and the model's alternate set (B) when A/B testing is on and an
    alternate exists. Returns (variant_label, hashtags). Falls back to A."""
    primary = _as_tags(media.get("hashtags_en"))
    alt = _as_tags(media.get("hashtags_en_b"))
    cfg = get_setting("hashtags") or {}
    if cfg.get("ab_test", True) and alt and random.random() < 0.5:
        return "B", alt
    return "A", primary


def _default_platforms() -> list[str]:
    """Read platforms settings and return enabled platforms list."""
    platform_settings = get_setting("platforms") or {}
    result = []
    if platform_settings.get("instagram_enabled", True):
        result.append("instagram")
    if platform_settings.get("youtube_enabled"):
        result.append("youtube")
    if platform_settings.get("tiktok_enabled"):
        result.append("tiktok")
    return result or ["instagram"]  # safety: never return empty


def _normalize_platforms(platforms) -> list[str]:
    """Supabase may return postgres array string e.g. '{instagram,youtube}'."""
    if not platforms:
        return ["instagram"]
    if isinstance(platforms, str):
        return [p.strip() for p in platforms.strip("{}").split(",") if p.strip()]
    return list(platforms)


def _ensure_r2_url(media: dict) -> dict:
    """Guarantee the media has a public r2_url before a platform upload.

    Auto-publish can fire after the local reel was cleaned up but before/without
    an R2 upload; YouTube then fails silently. If r2_url is missing but a local
    reel_ready_path exists, upload it and return the refreshed media row.
    """
    if media.get("r2_url"):
        return media
    reel_path = media.get("reel_ready_path") or ""
    if not reel_path:
        return media  # nothing to upload — let the platform uploader surface it
    try:
        from backend.pipeline.upload_r2 import upload_single, get_r2_client
        client = get_r2_client()
        result = upload_single(client, media["id"], reel_path)
        if result.get("status") == "uploaded":
            refreshed = get_media_by_id(media["id"])
            log.info("publish: uploaded missing r2_url for media %s", media["id"])
            return refreshed or media
    except Exception as exc:
        log.warning("publish: r2 ensure failed for media %s: %s", media.get("id"), exc)
    return media


def _notify_platform_failure(post: dict, platform: str, exc: Exception) -> None:
    """Surface a non-fatal platform publish failure (in-app + Telegram) so a
    silently-failing YouTube/TikTok upload doesn't go unnoticed."""
    try:
        from backend.db import create_notification
        create_notification("error", f"{platform} publish failed",
                             f"Post {post.get('id', '')[:8]}: {str(exc)[:300]}")
    except Exception:
        pass
    try:
        from backend.config import TELEGRAM_CHAT_ID
        from backend.pipeline.telegram_bot import send_message
        chat_id = int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None
        if chat_id:
            send_message(chat_id,
                         f"⚠️ <b>{platform} publish failed</b>\n"
                         f"Post <code>{post.get('id', '')[:8]}</code>\n{str(exc)[:300]}")
    except Exception:
        pass


# ── High-level scheduling library ─────────────────────────────────────────────

def enqueue_post(
    media_id: str,
    publish_after_minutes: int = 60,
    scheduled_at: dt.datetime | None = None,
    platforms: list[str] | None = None,
) -> dict | None:
    """
    Create a post record in 'preview' status.
    publish_after = now + publish_after_minutes (default 60 min approval window).
    The post sits in preview for that window so a human can review it; if not
    approved/rejected, the daemon auto-publishes once publish_after <= now.
    Clicking Approve publishes immediately (bypasses the window).
    platforms defaults to all enabled platforms from settings.
    """
    media = get_media_by_id(media_id)
    if not media:
        raise ValueError(f"media_id {media_id!r} not found")
    if platforms is None:
        platforms = _default_platforms()
    now = dt.datetime.now(dt.timezone.utc)
    base = scheduled_at or now
    # 1-hour (configurable) approval window: daemon auto-publishes after this passes.
    publish_after = (now + dt.timedelta(minutes=publish_after_minutes)).isoformat()
    variant, hashtags_en = _pick_hashtag_variant(media)
    return create_post({
        "media_id": media_id,
        "caption": media.get("caption", ""),
        "caption_ig": media.get("caption_ig"),
        "caption_tt": media.get("caption_tt"),
        "caption_yt_title": media.get("caption_yt_title"),
        "caption_yt_description": media.get("caption_yt_description"),
        "hashtags_en": hashtags_en,
        "hashtag_variant": variant,
        "hashtags_ar": media.get("hashtags_ar"),
        "status": "preview",
        "scheduled_at": base.isoformat(),
        "publish_after": publish_after,
        "platforms": platforms,
    })


def publish_post(post: dict, platforms_override: list[str] | None = None) -> dict:
    """
    Publish a post to all selected platforms (or to platforms_override only).
    IG is primary: raises if IG publish fails.
    YouTube failures are logged but non-fatal (stored in yt_error).
    TikTok via Zernio failures are non-fatal (stored in zernio_tt_error).
    Returns dict: {platform: id} for successfully published platforms.
    Handles all DB status updates internally.
    """
    media = get_media_by_id(post["media_id"])
    if not media:
        raise ValueError(f"media_id {post['media_id']!r} not found")

    _post_ar = {**post, "caption_ig_ar": media.get("caption_ig_ar") or ""}

    platforms = platforms_override if platforms_override is not None else _normalize_platforms(post.get("platforms"))
    updates: dict = {}
    results: dict = {}

    from backend.config import ZERNIO_API_KEY

    # ── Instagram ─────────────────────────────────────────────────────────────
    if "instagram" in platforms:
        # Idempotency guard (never post the same media twice): if this post already
        # carries an IG id, report it and skip re-publishing.
        existing_ig = post.get("ig_media_id") or post.get("zernio_ig_id")
        if existing_ig:
            results["instagram"] = existing_ig
            log.info("Instagram already published for post %s (%s) — skipping", post["id"], existing_ig)
        else:
            media_url = media.get("r2_url") or media.get("media_preview_url") or ""
            if not media_url:
                raise ValueError("No public media URL for IG publishing")
            caption = _build_platform_caption(_post_ar, "instagram")
            if ZERNIO_API_KEY:
                from backend.pipeline.zernio_publish import upload_short as zernio_upload
                zernio_id = zernio_upload(media, caption, "instagram")
                updates["zernio_ig_id"] = zernio_id
                results["instagram"] = zernio_id
                log.info("Published to Instagram via Zernio: %s", zernio_id)
            else:
                ig_id = _post_reel_to_ig(media_url, caption)
                updates["ig_media_id"] = ig_id
                results["instagram"] = ig_id
                log.info("Published to Instagram (native): %s", ig_id)

    # ── YouTube Shorts ────────────────────────────────────────────────────────
    if "youtube" in platforms:
        existing_yt = post.get("yt_video_id")
        if existing_yt:
            results["youtube"] = existing_yt
            log.info("YouTube already published for post %s (%s) — skipping", post["id"], existing_yt)
        else:
            try:
                # YouTube needs a public URL or a local file. IG shares r2_url, but
                # an auto-publish tick can run after the local reel was cleaned up
                # AND before r2_url was set — ensure a public URL exists first
                # (mirrors the retry-youtube endpoint) so YT doesn't silently fail.
                media = _ensure_r2_url(media)
                from backend.pipeline.youtube_publish import upload_short as yt_upload
                yt_title = post.get("caption_yt_title") or (post.get("caption", "").split("\n", 1)[0] or "")
                yt_description = _build_platform_caption(_post_ar, "youtube")
                yt_id = yt_upload(
                    media,
                    yt_description,
                    post.get("hashtags_en") or [],
                    title_override=yt_title,
                    hashtags_ar=post.get("hashtags_ar") or [],
                )
                updates["yt_video_id"] = yt_id
                updates["yt_error"] = None
                results["youtube"] = yt_id
            except Exception as exc:
                log.error("YouTube publish failed for post %s: %s", post["id"], exc)
                updates["yt_error"] = str(exc)[:500]
                _notify_platform_failure(post, "YouTube", exc)

    # ── TikTok (via Zernio) ───────────────────────────────────────────────────
    if "tiktok" in platforms:
        existing_tt = post.get("tiktok_video_id") or post.get("zernio_tt_id")
        if existing_tt:
            results["tiktok"] = existing_tt
            log.info("TikTok already published for post %s (%s) — skipping", post["id"], existing_tt)
        else:
            try:
                tt_caption = _build_platform_caption(_post_ar, "tiktok")
                if ZERNIO_API_KEY:
                    from backend.pipeline.zernio_publish import upload_short as zernio_upload
                    zernio_id = zernio_upload(media, tt_caption, "tiktok")
                    updates["zernio_tt_id"] = zernio_id
                    results["tiktok"] = zernio_id
                else:
                    from backend.pipeline.tiktok_publish import upload_short as tt_upload
                    tt_id = tt_upload(media, tt_caption, post.get("hashtags_en") or [])
                    updates["tiktok_video_id"] = tt_id
                    results["tiktok"] = tt_id
            except Exception as exc:
                log.error("TikTok publish failed for post %s: %s", post["id"], exc)
                updates["zernio_tt_error" if ZERNIO_API_KEY else "tiktok_error"] = str(exc)[:500]
                _notify_platform_failure(post, "TikTok", exc)

    updates["status"] = "posted"
    update_post(post["id"], updates)
    try:
        update_media(post["media_id"], {"status": "posted"})
    except Exception as exc:
        log.warning("publish_post: could not update media status to posted for %s: %s", post["media_id"], exc)
    return results


def cancel_post(post_id: str) -> None:
    update_post(post_id, {"status": "cancelled"})


def reschedule(post_id: str, new_scheduled_at: dt.datetime, window_minutes: int = 60) -> None:
    update_post(post_id, {
        "scheduled_at": new_scheduled_at.isoformat(),
        "publish_after": (new_scheduled_at + dt.timedelta(minutes=window_minutes)).isoformat(),
        "status": "preview",
    })


# ── Legacy queue.json runner (kept for pipeline orchestrator compat) ──────────

def run() -> dict:
    if not QUEUE_FILE.exists():
        return {"published": 0, "errors": 0}

    with open(QUEUE_FILE) as f:
        queue = json.load(f)

    now = dt.datetime.now(dt.timezone.utc)
    published = 0
    errors = 0

    for item in queue:
        if item["status"] != "pending":
            continue
        scheduled = dt.datetime.fromisoformat(item["scheduled_at"])
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=dt.timezone.utc)
        if scheduled > now:
            continue

        caption_full = _build_caption(item)
        try:
            mid = _post_reel_to_ig(item["media_url"], caption_full)
            item["status"] = "posted"
            item["ig_media_id"] = mid
            published += 1
        except Exception as e:
            item["status"] = "error"
            item["error"] = str(e)
            errors += 1

    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)

    return {"published": published, "errors": errors}


if __name__ == "__main__":
    result = run()
    print(f"Done. {result['published']} published, {result['errors']} errors.")
