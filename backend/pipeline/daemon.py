"""
APScheduler daemon — runs inside FastAPI lifespan (single worker only).
Jobs:
  auto_publish — every 60 s, publishes posts whose publish_after has passed.
  auto_create  — every 60 s, fires at each daily slot to auto-create a new post
                 (when pipeline.auto_create_enabled is True).
  nightly_vision — once a night at 03:00 (schedule.timezone), backfills hook_score
                 + category on un-scored footage (when vision.enabled is True).
"""

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.db import get_due_posts, update_post, get_setting, get_media_by_id
from backend.pipeline.scheduler import publish_post, _normalize_platforms

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
# Guard: track last slot key that auto_create already fired for (avoids double-create).
_last_auto_create_slot_key: tuple | None = None


def _send_publish_notify(post: dict, results: dict, error: str | None) -> None:
    """Send Telegram message after auto-publish (success or failure). Non-fatal."""
    try:
        from backend.config import TELEGRAM_CHAT_ID
        from backend.pipeline.telegram_bot import send_message, send_photo
        chat_id = int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None
        if not chat_id:
            return

        if error:
            msg = (
                f"❌ <b>Publish failed</b>\n"
                f"Post: <code>{post['id'][:8]}</code>\n"
                f"{error[:300]}"
            )
            send_message(chat_id, msg)
            return

        # Build platform result lines
        plat_lines = []
        if results.get("youtube"):
            plat_lines.append(f"▶️ YouTube ✅ <code>{results['youtube']}</code>")
        if results.get("instagram"):
            plat_lines.append(f"📸 Instagram ✅ <code>{results['instagram']}</code>")
        if results.get("tiktok"):
            plat_lines.append(f"🎵 TikTok ✅ <code>{results['tiktok']}</code>")
        platforms_str = "\n".join(plat_lines) if plat_lines else "unknown platform"

        slot_str = ""
        raw_slot = post.get("slot_at") or post.get("published_at")
        if raw_slot:
            try:
                s = raw_slot if not isinstance(raw_slot, str) else raw_slot.replace("Z", "+00:00")
                dt = datetime.fromisoformat(s).astimezone(timezone.utc)
                slot_str = f"\n🕐 {dt.strftime('%a %d %b · %H:%M UTC')}"
            except Exception:
                pass

        # Try to load media for rich detail
        tg_cfg = {}
        try:
            tg_cfg = get_setting("telegram") or {}
        except Exception:
            pass
        rich = tg_cfg.get("rich_publish_notify", True)

        media = None
        if rich:
            try:
                media = get_media_by_id(post.get("media_id", ""))
            except Exception:
                pass

        if media and rich:
            category = (media.get("category") or "?").replace("_", " ").title()
            tags = media.get("tags") or []
            tags_str = ", ".join(tags) if isinstance(tags, list) else (tags or "")
            lines = [
                f"✅ <b>Published</b>",
                f"<b>{category}</b>" + (f" — {tags_str}" if tags_str else ""),
                platforms_str,
                slot_str,
            ]
            if media.get("caption"):
                preview = media["caption"][:150].replace("<", "&lt;")
                lines.append(f"\n{preview}…")
            if media.get("r2_url"):
                lines.append(f'\n<a href="{media["r2_url"]}">▶ Watch clip</a>')
            msg = "\n".join(l for l in lines if l)

            thumb = media.get("thumbnail_url", "")
            if thumb and thumb.startswith("http"):
                try:
                    send_photo(chat_id, thumb, caption=msg)
                    return
                except Exception:
                    pass  # fall through to send_message

            send_message(chat_id, msg)
        else:
            # Terse fallback
            msg = f"✅ <b>Published</b>\n{platforms_str}{slot_str}"
            send_message(chat_id, msg)

    except Exception as exc:
        log.warning("Telegram publish notify failed (non-fatal): %s", exc)


async def _auto_publish() -> None:
    try:
        pipeline_cfg = get_setting("pipeline", {}) or {}
        if not pipeline_cfg.get("auto_publish_enabled", True):
            log.debug("auto_publish disabled via pipeline.auto_publish_enabled setting")
            return
        due = get_due_posts()
    except Exception as exc:
        # Transient DB/connection blip — skip this tick, retry on the next one.
        log.warning("auto_publish: skipped tick (DB read failed): %s", exc)
        return
    if not due:
        return
    approval_cfg = get_setting("approval") or {}
    manual_categories = approval_cfg.get("require_manual_for_categories") or []
    if isinstance(manual_categories, str):
        manual_categories = [c.strip() for c in manual_categories.split(",") if c.strip()]
    loop = asyncio.get_running_loop()
    for post in due:
        try:
            if manual_categories:
                media = get_media_by_id(post.get("media_id", ""))
                if media and media.get("category") in manual_categories:
                    log.info("auto_publish: skipping post %s — category '%s' requires manual approval",
                             post["id"], media.get("category"))
                    continue
            # The post's own platform selection is authoritative (never override a
            # deliberately single-platform post). YouTube not auto-publishing is
            # fixed at the publish layer (ensure r2_url + surface silent failures),
            # not by force-adding platforms here.
            post_platforms = _normalize_platforms(post.get("platforms"))
            auto_platforms = [
                p for p in post_platforms
                if approval_cfg.get(f"{p}_auto_enabled", True)
            ]
            if not auto_platforms:
                log.debug("auto_publish: skipping post %s — all platforms set to manual-only", post["id"])
                continue
            results = await loop.run_in_executor(None, lambda p=post, ap=auto_platforms: publish_post(p, platforms_override=ap))
            log.info("auto-published post %s → %s", post["id"], results)
            from backend.api.ws import broadcast
            await broadcast("post_status", {
                "post_id": post["id"],
                "status": "posted",
                **{f"{platform}_id": vid for platform, vid in results.items() if vid},
            })
            await loop.run_in_executor(
                None, lambda r=results, p=post: _send_publish_notify(p, r, error=None)
            )
        except Exception as exc:
            log.error("auto-publish failed for post %s: %s", post["id"], exc)
            update_post(post["id"], {"status": "error", "error_message": str(exc)})
            try:
                from backend.api.ws import broadcast
                await broadcast("post_status", {"post_id": post["id"], "status": "error"})
            except Exception:
                pass
            await loop.run_in_executor(
                None, lambda e=exc, p=post: _send_publish_notify(p, {}, error=str(e))
            )


async def _auto_create() -> None:
    """
    Fires every 60 s. When pipeline.auto_create_enabled is True and *now* falls
    within a daily slot window, picks a raw clip and runs the full pipeline.

    mode='approval' (default): Telegram preview pushed, human approves → publish.
    mode='publish':            post auto-published at slot time, no human gate.
    """
    global _last_auto_create_slot_key

    try:
        pipeline_cfg = get_setting("pipeline") or {}
        if not pipeline_cfg.get("auto_create_enabled", True):
            return

        from backend.pipeline.slots import is_slot_due
        now = datetime.now(timezone.utc)
        slot = is_slot_due(now)
    except Exception as exc:
        # Transient DB/connection blip — skip this tick, retry on the next one.
        log.warning("auto_create: skipped tick (DB read failed): %s", exc)
        return
    if slot is None:
        return  # not a slot window — nothing to do

    # Build a hashable key for this slot to prevent duplicate creates.
    slot_key = (slot.year, slot.month, slot.day, slot.hour, slot.minute)
    if slot_key == _last_auto_create_slot_key:
        log.debug("auto_create: slot %s already fired — skipping", slot.isoformat())
        return
    _last_auto_create_slot_key = slot_key

    mode = pipeline_cfg.get("auto_create_mode", "approval")
    auto_publish_slot = slot if mode == "publish" else None
    reel_type = pipeline_cfg.get("auto_create_reel_type", "merge")

    if reel_type == "merge" and (get_setting("merge") or {}).get("enabled"):
        category = pipeline_cfg.get("auto_create_category") or None
        started = await _start_merge_auto_create(category, "auto", auto_publish_slot)
        if started:
            return
        log.info("auto_create: merge had no eligible category/pool for slot %s — falling back to single-clip", slot.isoformat())
        # fall through to single-clip pick below (thin footage / no configured category)

    strategy = pipeline_cfg.get("auto_create_strategy", "diverse")
    category = pipeline_cfg.get("auto_create_category") or None

    log.info("auto_create: slot=%s strategy=%s mode=%s category=%s",
             slot.isoformat(), strategy, mode, category)

    # Pick a raw clip using the existing helper (imported lazily to avoid circular import).
    from backend.api.routes.posts import _pick_media_for_create, _pipeline_and_enqueue
    media = _pick_media_for_create(
        strategy=strategy,
        category=category,
        tags=None,
        exclude_ids=[],
    )
    if not media:
        log.info("auto_create: no available clip for slot %s (strategy=%s, category=%s)",
                 slot.isoformat(), strategy, category)
        return

    log.info("auto_create: picked media_id=%s — starting pipeline", media["id"])
    asyncio.create_task(
        _pipeline_and_enqueue(media["id"], source="auto", auto_publish_slot=auto_publish_slot)
    )


async def _start_merge_auto_create(
    category: str | None, source: str, auto_publish_slot: "datetime | None",
) -> bool:
    """Kick off a merge (multi-clip) reel for auto-create. Resolves a category when
    none is configured (random pick weighted by pool size, cooldown-aware) so
    pipeline.auto_create_reel_type='merge' works out of the box. Returns False
    (never raises) when no category has any footage, so the caller can fall back
    to the single-clip path instead of silently doing nothing."""
    if not category:
        from backend.db import get_random_category_for_merge
        category = get_random_category_for_merge()
    if not category:
        return False

    merge_cfg = get_setting("merge") or {}
    mk: dict = {"category": category}
    if not merge_cfg.get("auto_count", True):
        mk["count"] = int(merge_cfg.get("clips_per_reel", 4))

    from backend.api.routes.posts import _merge_and_enqueue
    log.info("auto_create: merge reel — category=%s auto_publish=%s", category, bool(auto_publish_slot))
    asyncio.create_task(_merge_and_enqueue(mk, source, auto_publish_slot=auto_publish_slot))
    return True


async def _nightly_vision() -> None:
    """
    Nightly hook-scoring backfill. Runs classify_vision over footage that still
    lacks a hook_score (raw clips, freshly downloaded). Gated by vision.enabled;
    provider + batch size configurable via the vision settings group. Runs the
    sync batch in a thread executor so it never blocks the event loop.
    """
    vision_cfg = get_setting("vision", {}) or {}
    if not vision_cfg.get("enabled", True):
        log.debug("nightly_vision disabled via vision.enabled setting")
        return

    provider = vision_cfg.get("provider", "auto")
    try:
        limit = int(vision_cfg.get("nightly_limit", 50))
    except (TypeError, ValueError):
        limit = 50

    loop = asyncio.get_running_loop()
    try:
        from backend.pipeline.classify_vision import run as run_vision
        summary = await loop.run_in_executor(
            None, lambda: run_vision(provider=provider, limit=limit)
        )
        log.info("nightly_vision: %s", summary)
    except Exception as exc:
        log.error("nightly_vision run failed: %s", exc)


async def _editor_proxy_sweep() -> None:
    """
    Nightly disk reclaim for the Reel Editor's 480p proxy cache. Deletes proxies
    whose mtime is older than editor.proxy_ttl_days (ensure_proxy() touches on a
    cache hit, so a reel someone keeps reopening never expires under them).
    Gated by editor.enabled; runs the sync sweep in a thread executor.
    """
    editor_cfg = get_setting("editor", {}) or {}
    if not editor_cfg.get("enabled", True):
        log.debug("editor_proxy_sweep disabled via editor.enabled setting")
        return

    try:
        ttl_days = float(editor_cfg.get("proxy_ttl_days", 7))
    except (TypeError, ValueError):
        ttl_days = 7.0

    loop = asyncio.get_running_loop()
    try:
        from backend.pipeline.editor_proxy import sweep
        removed = await loop.run_in_executor(None, lambda: sweep(ttl_days))
        log.info("editor_proxy_sweep: removed %d proxies (ttl=%.1fd)", removed, ttl_days)
    except Exception as exc:
        log.error("editor_proxy_sweep run failed: %s", exc)


def start() -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_auto_publish, "interval", seconds=60, id="auto_publish", max_instances=1, misfire_grace_time=30)
    _scheduler.add_job(_auto_create, "interval", seconds=60, id="auto_create", max_instances=1, misfire_grace_time=30)

    # Nightly vision backfill at 03:00 in the configured schedule timezone.
    tz_name = (get_setting("schedule", {}) or {}).get("timezone", "Asia/Beirut")
    try:
        vision_tz = ZoneInfo(tz_name.strip())
    except Exception:
        log.warning("nightly_vision: bad timezone %r, falling back to UTC", tz_name)
        vision_tz = timezone.utc
    _scheduler.add_job(
        _nightly_vision,
        CronTrigger(hour=3, minute=0, timezone=vision_tz),
        id="nightly_vision", max_instances=1,
        misfire_grace_time=3600,  # if the worker was busy/restarting, still run within the hour
    )

    # Editor proxy TTL sweep at 04:00, right after the vision backfill, in the
    # same configured timezone (reuses vision_tz resolved above).
    _scheduler.add_job(
        _editor_proxy_sweep,
        CronTrigger(hour=4, minute=0, timezone=vision_tz),
        id="editor_proxy_sweep", max_instances=1,
        misfire_grace_time=3600,
    )

    _scheduler.start()
    log.info(
        "Daemon started — auto_publish + auto_create every 60 s, "
        "nightly_vision at 03:00 %s, editor_proxy_sweep at 04:00 %s",
        tz_name, tz_name,
    )


def stop() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Daemon stopped")


async def trigger_auto_create_now() -> dict:
    """Manually trigger one auto-create cycle, bypassing slot gating."""
    pipeline_cfg = get_setting("pipeline") or {}
    strategy = pipeline_cfg.get("auto_create_strategy", "diverse")
    category = pipeline_cfg.get("auto_create_category") or None
    mode = pipeline_cfg.get("auto_create_mode", "approval")
    reel_type = pipeline_cfg.get("auto_create_reel_type", "merge")

    if reel_type == "merge" and (get_setting("merge") or {}).get("enabled"):
        started = await _start_merge_auto_create(category, "manual", None)
        if started:
            log.info("trigger_auto_create_now: merge reel started (category=%s)", category or "auto-picked")
            return {"ok": True, "mode": mode, "reel_type": "merge"}
        log.info("trigger_auto_create_now: merge had no eligible category/pool — falling back to single-clip")

    from backend.api.routes.posts import _pick_media_for_create, _pipeline_and_enqueue
    media = _pick_media_for_create(
        strategy=strategy,
        category=category,
        tags=None,
        exclude_ids=[],
    )
    if not media:
        return {"ok": False, "reason": "no_available_clip"}

    log.info("trigger_auto_create_now: picked media_id=%s mode=%s", media["id"], mode)
    asyncio.create_task(
        _pipeline_and_enqueue(media["id"], source="manual", auto_publish_slot=None)
    )
    return {"ok": True, "media_id": media["id"], "mode": mode, "reel_type": "single"}
