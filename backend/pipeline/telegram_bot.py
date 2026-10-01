"""
Telegram manager bot.
Handles preview push, inline approve/reject/reschedule, and commands:
  /queue  /pending  /stats  /settings  /create

/create state machine (in-memory, reset on restart — flows are seconds-long):
  await_category → await_tags → confirm → dispatch

Preview push: thumbnail (photo) + caption + R2 link.
No video upload — stays under Telegram's 50 MB cap.
"""

import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import requests as _req

from backend.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_MODE,
)
from backend.db import (
    get_posts, get_media_by_id, update_post, update_media, update_status, delete_post, get_distinct,
)

log = logging.getLogger(__name__)

_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ── In-memory /create state machine ─────────────────────────────────────────
# {chat_id: {step, category, tags, tried_ids}}
_create_state: dict[int, dict] = {}
_edit_state: dict[int, dict] = {}
# {chat_id: {mode: "refine"|"replace", post_id: str, media_id: str}}

_CREATE_STEPS = ("await_category", "await_tags", "await_merge_count", "confirm", "dispatch")


# ── Low-level Telegram helpers ───────────────────────────────────────────────

def _call(method: str, **kwargs) -> dict:
    resp = _req.post(f"{_API}/{method}", json=kwargs, timeout=10)
    resp.raise_for_status()
    return resp.json()


def send_message(chat_id: int, text: str, reply_markup: dict | None = None, parse_mode: str = "HTML") -> dict:
    params: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return _call("sendMessage", **params)


def send_photo(chat_id: int, photo_url: str, caption: str = "", reply_markup: dict | None = None) -> dict:
    params: dict[str, Any] = {"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return _call("sendPhoto", **params)


def answer_callback(callback_id: str, text: str = "") -> None:
    try:
        _call("answerCallbackQuery", callback_query_id=callback_id, text=text)
    except Exception:
        pass


def inline_keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    """rows: list of lists of (label, callback_data)"""
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row]
            for row in rows
        ]
    }


# ── Preview push ─────────────────────────────────────────────────────────────

def send_preview(media_id: str, chat_id: int | None = None) -> None:
    """
    Push a thumbnail preview to Telegram with approve/reject/reschedule buttons.
    Uses thumbnail_url (photo) to stay under 50 MB cap.
    """
    chat_id = chat_id or (int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None)
    if not chat_id:
        log.warning("send_preview: TELEGRAM_CHAT_ID not set")
        return

    media = get_media_by_id(media_id)
    if not media:
        log.error("send_preview: media_id %s not found", media_id)
        return

    # Find associated preview post
    posts = get_posts(filters={"media_id": media_id}, limit=10)
    post = next((p for p in posts if p["status"] in ("preview", "approved")), None)

    _tags = media.get("tags") or []
    _tags_str = ", ".join(_tags) if isinstance(_tags, list) else (_tags or "?")
    caption_lines = [
        f"<b>{(media.get('category') or '?').replace('_', ' ').title()}</b>",
        f"Tags: {_tags_str}",
        f"Music: {media.get('music_source', '?')}",
    ]
    if media.get("duration"):
        try:
            d = float(media["duration"])
            caption_lines.append(f"Duration: {d:.1f}s")
        except (TypeError, ValueError):
            pass
    if media.get("hook_score") is not None:
        try:
            hs = float(media["hook_score"])
            caption_lines.append(f"Hook score: {hs:.2f}")
        except (TypeError, ValueError):
            pass
    if media.get("caption"):
        preview_text = media["caption"][:200].replace("<", "&lt;")
        caption_lines.append(f"\n{preview_text}…")
    if media.get("r2_url"):
        caption_lines.append(f'\n<a href="{media["r2_url"]}">▶ Watch clip</a>')
    if post and post.get("publish_after"):
        eta = post["publish_after"]
        caption_lines.append(f"⏱ Auto-post: {eta[:16]}Z")

    caption = "\n".join(caption_lines)

    post_id = post["id"] if post else ""
    if post_id:
        raw_platforms = post.get("platforms") or ["instagram"]
        if isinstance(raw_platforms, str):
            post_platforms = [p.strip() for p in raw_platforms.strip("{}").split(",") if p.strip()]
        else:
            post_platforms = list(raw_platforms)

        _PLAT_EMOJI = {"instagram": "📸", "tiktok": "🎵", "youtube": "▶️"}
        _PLAT_LABEL = {"instagram": "IG", "tiktok": "TikTok", "youtube": "YT"}
        _PLAT_ABBREV = {"instagram": "ig", "tiktok": "tt", "youtube": "yt"}

        # One button per enabled platform
        plat_buttons = [
            (f"{_PLAT_EMOJI.get(p, '📤')} Publish {_PLAT_LABEL.get(p, p.title())}",
             f"approve_platform:{post_id}:{p}")
            for p in post_platforms
        ]
        # Approve All button (only when >1 platform)
        abbrevs = ",".join(_PLAT_ABBREV.get(p, p) for p in post_platforms)
        approve_all_row = [("✅ Approve All", f"approve_group:{post_id}:{abbrevs}")] if len(post_platforms) > 1 else []

        # Admin controls — read setting to decide whether to show
        from backend.db import get_setting as _get_setting
        tg_cfg = _get_setting("telegram") or {}
        show_admin = tg_cfg.get("admin_controls", True)

        rows = []
        # Split platform buttons into rows of 2
        for i in range(0, len(plat_buttons), 2):
            rows.append(plat_buttons[i:i+2])
        if approve_all_row:
            rows.append(approve_all_row)
        if show_admin:
            rows.append([("✏️ Edit caption", f"edit_menu:{post_id}"), ("ℹ️ Details", f"details:{post_id}")])
            rows.append([("🕐 Reschedule", f"resched_menu:{post_id}"), ("🔄 Regenerate", f"try_another:{media_id}")])
        rows.append([("🚫 Cancel", f"cancel:{post_id}"), ("❌ Reject", f"reject:{post_id}")])

        keyboard = inline_keyboard(rows)
    else:
        keyboard = None

    thumb = media.get("thumbnail_url", "")
    try:
        if thumb and thumb.startswith("http"):
            send_photo(chat_id, thumb, caption=caption, reply_markup=keyboard)
        else:
            send_message(chat_id, caption, reply_markup=keyboard)
    except Exception as exc:
        log.error("send_preview failed: %s", exc)


# ── Command handlers ─────────────────────────────────────────────────────────

def _cmd_queue(chat_id: int) -> None:
    posts = get_posts(limit=10)
    if not posts:
        send_message(chat_id, "Queue is empty.")
        return
    lines = []
    for p in posts[:8]:
        eta = p.get("publish_after", "?")[:16] if p.get("publish_after") else "?"
        lines.append(f"• [{p['status']}] {p['media_id'][:8]} → {eta}")
    send_message(chat_id, "<b>Queue</b>\n" + "\n".join(lines))


def _cmd_pending(chat_id: int) -> None:
    posts = get_posts(filters={"status": "preview"}, limit=10)
    if not posts:
        send_message(chat_id, "No pending posts.")
        return
    lines = [f"• {p['media_id'][:8]} — auto-post {p.get('publish_after', '?')[:16]}" for p in posts]
    send_message(chat_id, f"<b>Pending ({len(posts)})</b>\n" + "\n".join(lines))


def _cmd_stats(chat_id: int) -> None:
    from backend.db import get_media
    total   = len(get_media(limit=500))
    posted  = len(get_media(filters={"status": "posted"}, limit=500))
    pending = len(get_posts(filters={"status": "preview"}, limit=100))
    send_message(chat_id, f"<b>Stats</b>\nTotal media: {total}\nPosted: {posted}\nPending approval: {pending}")


def _cmd_settings(chat_id: int) -> None:
    from backend.db import get_all_settings
    s = get_all_settings()
    sched = s.get("schedule", {})
    appr  = s.get("approval", {})
    lines = [
        "<b>Settings</b>",
        f"Slots: {', '.join(sched.get('daily_slots', []))}",
        f"Timezone: {sched.get('timezone', '?')}",
        f"Auto-post window: {appr.get('auto_post_after_minutes', 60)} min",
    ]
    send_message(chat_id, "\n".join(lines))


def _cmd_create(chat_id: int) -> None:
    categories = get_distinct("category")
    if not categories:
        send_message(chat_id, "No categories in DB yet. Run the indexer first.")
        return
    _create_state[chat_id] = {"step": "await_category", "tried_ids": []}
    # Build 2-per-row keyboard
    rows = [categories[i:i+2] for i in range(0, len(categories), 2)]
    kbd = inline_keyboard([[(_c.replace("_", " ").title(), f"create_category:{_c}") for _c in row] for row in rows])
    send_message(chat_id, "🏷 <b>Which category?</b>", reply_markup=kbd)


def _prompt_create_confirm(chat_id: int, state: dict) -> None:
    """Confirm step of the /create wizard: single clip vs. merge N."""
    category = state.get("category", "?")
    tags = state.get("tags") or []
    tags_csv = ",".join(tags)
    tags_line = f"Tags: {', '.join(tags)}" if tags else "Tags: (none)"
    kbd = inline_keyboard([
        [("1 clip", f"create_dispatch:{category}:{tags_csv}"),
         ("🎬 Merge 3", f"create_count:{category}:{tags_csv}:3")],
        [("🎬 Merge 4", f"create_count:{category}:{tags_csv}:4"),
         ("🎬 Merge 5", f"create_count:{category}:{tags_csv}:5")],
        [("❌ Cancel", "create_cancel")],
    ])
    send_message(
        chat_id,
        f"📋 <b>Category: {category.replace('_', ' ').title()}</b>\n{tags_line}\n"
        "Single clip, or merge several into one reel?",
        reply_markup=kbd,
    )


# ── Callback handlers ─────────────────────────────────────────────────────────

def _handle_callback(callback_id: str, chat_id: int, data: str) -> None:
    answer_callback(callback_id)

    if data.startswith("approve:"):
        post_id = data.split(":", 1)[1]
        send_message(chat_id, "✅ Approved — publishing now…")

        # Publish immediately to all enabled platforms in a background thread
        # (callback handler must return fast; IG container poll can take minutes).
        def _bg_publish():
            try:
                from backend.db import get_post_by_id
                from backend.pipeline.scheduler import publish_post
                post = get_post_by_id(post_id)
                if not post:
                    send_message(chat_id, "⚠️ Publish failed: post not found")
                    return
                update_post(post_id, {"status": "publishing"})
                results = publish_post(post)
                parts = [f"{p.title()} ✅" for p, vid in results.items() if vid]
                send_message(chat_id, "📤 Published: " + (" · ".join(parts) or "done"))
            except Exception as exc:
                update_post(post_id, {"status": "error", "error_message": str(exc)})
                send_message(chat_id, f"⚠️ Publish failed: {exc}")
        threading.Thread(target=_bg_publish, daemon=True).start()

    elif data.startswith("approve_group:"):
        # approve_group:{post_id}:{p1,p2,...}  (platforms may be abbreviated: ig/tt/yt)
        parts = data.split(":", 2)
        post_id, platforms_str = parts[1], parts[2]
        _PLAT_SHORT = {"ig": "instagram", "tt": "tiktok", "yt": "youtube"}
        platforms = [_PLAT_SHORT.get(p, p) for p in platforms_str.split(",") if p]
        send_message(chat_id, f"📤 Publishing to {' + '.join(p.title() for p in platforms)}…")

        def _bg_publish_group(pid=post_id, plats=platforms):
            try:
                from backend.db import get_post_by_id
                from backend.pipeline.scheduler import publish_post
                p = get_post_by_id(pid)
                if not p:
                    send_message(chat_id, "⚠️ Post not found")
                    return
                update_post(pid, {"status": "publishing"})
                results = publish_post(p, platforms_override=plats)
                parts_ok = [f"{pl.title()} ✅" for pl, vid in results.items() if vid]
                send_message(chat_id, "📤 Published: " + (" · ".join(parts_ok) or "done"))
            except Exception as exc:
                update_post(pid, {"status": "error", "error_message": str(exc)})
                send_message(chat_id, f"⚠️ Publish failed: {exc}")
        threading.Thread(target=_bg_publish_group, daemon=True).start()

    elif data.startswith("approve_platform:"):
        parts = data.split(":", 2)
        post_id, platform = parts[1], parts[2]
        _PLAT_EMOJI = {"instagram": "📸", "tiktok": "🎵", "youtube": "▶️"}
        emoji = _PLAT_EMOJI.get(platform, "📤")
        send_message(chat_id, f"{emoji} Publishing to {platform.title()}…")

        def _bg_publish_platform(pid=post_id, plat=platform):
            try:
                from backend.db import get_post_by_id
                from backend.pipeline.scheduler import publish_post
                p = get_post_by_id(pid)
                if not p:
                    send_message(chat_id, "⚠️ Post not found")
                    return
                update_post(pid, {"status": "publishing"})
                results = publish_post(p, platforms_override=[plat])
                if results.get(plat):
                    send_message(chat_id, f"{emoji} {plat.title()} published ✅")
                else:
                    send_message(chat_id, f"⚠️ {plat.title()} returned no result")
            except Exception as exc:
                send_message(chat_id, f"⚠️ {plat.title()} failed: {exc}")
        threading.Thread(target=_bg_publish_platform, daemon=True).start()

    elif data.startswith("cancel:"):
        post_id = data.split(":", 1)[1]
        try:
            from backend.db import get_post_by_id
            p = get_post_by_id(post_id)
            update_post(post_id, {"status": "cancelled"})
            if p and p.get("media_id"):
                update_media(p["media_id"], {"do_not_use": True})
            send_message(chat_id, "🚫 Cancelled — clip won't be reused.")
        except Exception as exc:
            send_message(chat_id, f"⚠️ Cancel failed: {exc}")

    elif data.startswith("reject:"):
        post_id = data.split(":", 1)[1]
        try:
            from backend.db import get_post_by_id
            p = get_post_by_id(post_id)
            if p and p.get("media_id"):
                update_status(p["media_id"], "deleted")
            delete_post(post_id)
            send_message(chat_id, "❌ Rejected — clip permanently removed.")
        except Exception as exc:
            send_message(chat_id, f"⚠️ Reject failed: {exc}")

    elif data.startswith("reschedule:"):
        _, post_id, mins_str = data.split(":")
        mins = int(mins_str)
        new_after = (datetime.now(timezone.utc) + timedelta(minutes=mins)).isoformat()
        update_post(post_id, {"publish_after": new_after, "status": "preview"})
        send_message(chat_id, f"🔁 Rescheduled +{mins} min.")

    elif data.startswith("try_another:"):
        media_id = data.split(":", 1)[1]
        media = get_media_by_id(media_id)
        if not media:
            send_message(chat_id, "Media not found.")
            return
        state = _create_state.get(chat_id, {"tried_ids": []})
        state["tried_ids"].append(media_id)
        from backend.db import get_raw_media_for_create
        alt = get_raw_media_for_create(
            media.get("category", ""), media.get("tags") or None,
            exclude_ids=state["tried_ids"], strategy="random",
        )
        if not alt:
            send_message(chat_id, "No more unposted clips for this filter.")
            return
        state["tried_ids"].append(alt["id"])
        _create_state[chat_id] = state
        send_preview(alt["id"], chat_id)

    elif data.startswith("details:"):
        post_id = data.split(":", 1)[1]
        try:
            from backend.db import get_post_by_id
            p = get_post_by_id(post_id)
            if not p:
                send_message(chat_id, "⚠️ Post not found.")
                return
            m = get_media_by_id(p.get("media_id", ""))
            lines = [f"<b>ℹ️ Post Details</b>"]
            if m:
                _m_tags = m.get("tags") or []
                _m_tags_str = ", ".join(_m_tags) if isinstance(_m_tags, list) else (_m_tags or "?")
                lines += [
                    f"Category: {(m.get('category') or '?').replace('_', ' ').title()}",
                    f"Tags: {_m_tags_str}",
                ]
                if m.get("duration"):
                    try:
                        lines.append(f"Duration: {float(m['duration']):.1f}s")
                    except (TypeError, ValueError):
                        pass
                if m.get("hook_score") is not None:
                    try:
                        lines.append(f"Hook score: {float(m['hook_score']):.2f}")
                    except (TypeError, ValueError):
                        pass
                if m.get("music_source"):
                    lines.append(f"Music: {m['music_source']}")
            lines += [
                f"Status: {p.get('status', '?')}",
                f"Platforms: {', '.join(p.get('platforms') or ['instagram'])}",
            ]
            if p.get("scheduled_at"):
                lines.append(f"Scheduled: {p['scheduled_at'][:16]}Z")
            if p.get("publish_after"):
                lines.append(f"Auto-post: {p['publish_after'][:16]}Z")
            # Per-platform publish IDs
            if p.get("ig_media_id"):
                lines.append(f"IG ID: <code>{p['ig_media_id']}</code>")
            if p.get("yt_video_id"):
                lines.append(f"YT ID: <code>{p['yt_video_id']}</code>")
            if p.get("tiktok_video_id"):
                lines.append(f"TikTok ID: <code>{p['tiktok_video_id']}</code>")
            # Errors
            for ekey in ("yt_error", "tiktok_error", "error_message"):
                if p.get(ekey):
                    lines.append(f"⚠️ {ekey}: {str(p[ekey])[:120]}")
            if m and m.get("r2_url"):
                lines.append(f'\n<a href="{m["r2_url"]}">▶ Watch clip</a>')
            send_message(chat_id, "\n".join(lines))
        except Exception as exc:
            send_message(chat_id, f"⚠️ Details failed: {exc}")

    elif data.startswith("edit_menu:"):
        post_id = data.split(":", 1)[1]
        kbd = inline_keyboard([
            [("🤖 Refine (AI)", f"edit_refine:{post_id}"), ("✏️ Replace text", f"edit_replace:{post_id}")],
        ])
        send_message(chat_id, "Choose edit mode:", reply_markup=kbd)

    elif data.startswith("edit_refine:") or data.startswith("edit_replace:"):
        mode_str = data.split(":", 1)[0].replace("edit_", "")
        post_id = data.split(":", 1)[1]
        try:
            from backend.db import get_post_by_id
            p = get_post_by_id(post_id)
            if not p or not p.get("media_id"):
                send_message(chat_id, "⚠️ Post not found.")
                return
            _edit_state[chat_id] = {"mode": mode_str, "post_id": post_id, "media_id": p["media_id"]}
            if mode_str == "refine":
                send_message(chat_id, "✏️ Send feedback for AI refine (e.g. 'shorter, add cost estimate'):")
            else:
                send_message(chat_id, "✏️ Send the new caption text to replace the current one:")
        except Exception as exc:
            send_message(chat_id, f"⚠️ Edit setup failed: {exc}")

    elif data.startswith("resched_menu:"):
        post_id = data.split(":", 1)[1]
        kbd = inline_keyboard([
            [("🕐 +1h", f"reschedule:{post_id}:60"), ("🕒 +3h", f"reschedule:{post_id}:180"), ("📅 +1d", f"reschedule:{post_id}:1440")],
        ])
        send_message(chat_id, "Reschedule by how much?", reply_markup=kbd)

    # /create flow callbacks
    elif data.startswith("create_category:"):
        category = data.split(":", 1)[1]
        state = _create_state.get(chat_id, {"tried_ids": []})
        state.update({"step": "await_tags", "category": category, "tags": []})
        _create_state[chat_id] = state
        kbd = inline_keyboard([[("⏭ Skip (no tags)", "create_tags_skip")]])
        send_message(
            chat_id,
            "🏷 <b>Any tags?</b> Reply with comma-separated tags, or tap Skip.",
            reply_markup=kbd,
        )

    elif data == "create_tags_skip":
        state = _create_state.get(chat_id)
        if not state:
            send_message(chat_id, "Session expired. Use /create to start again.")
            return
        state.update({"step": "await_merge_count", "tags": []})
        _create_state[chat_id] = state
        _prompt_create_confirm(chat_id, state)

    elif data.startswith("create_dispatch:"):
        _, category, tags_csv = data.split(":", 2)
        tags = [t for t in tags_csv.split(",") if t] or None
        state = _create_state.pop(chat_id, {"tried_ids": []})
        from backend.db import get_raw_media_for_create
        media = get_raw_media_for_create(category, tags, exclude_ids=state.get("tried_ids", []), strategy="best")
        if not media:
            send_message(chat_id, f"😕 No unposted clips for category={category}. Try /queue.")
            return
        send_message(chat_id, f"⚙️ Pipeline started for <code>{media['id'][:8]}</code>…\nPreview incoming shortly.")
        # Fire pipeline in background thread (bot handler must return quickly)
        def _bg():
            try:
                from backend.pipeline.orchestrator import run as orch_run
                orch_run(stages=["resize", "caption"], media_id=media["id"])
                from backend.pipeline.scheduler import enqueue_post
                from backend.db import get_setting
                window = (get_setting("approval") or {}).get("auto_post_after_minutes", 60)
                enqueue_post(media["id"], publish_after_minutes=int(window))
                send_preview(media["id"], chat_id)
            except Exception as exc:
                send_message(chat_id, f"❌ Pipeline failed: {exc}")
        threading.Thread(target=_bg, daemon=True).start()

    elif data.startswith("create_count:"):
        _, category, tags_csv, cnt = data.split(":", 3)
        tags = [t for t in tags_csv.split(",") if t] or None
        try:
            count = max(2, min(8, int(cnt)))
        except ValueError:
            count = 3
        _create_state.pop(chat_id, None)
        send_message(chat_id, f"🎬 Merging {count} clips for <b>{category.replace('_', ' ')}</b>…\nPreview incoming shortly.")

        def _bg_merge():
            try:
                from backend.pipeline.merge_clips import run as merge_run
                res = merge_run(category=category, tags=tags, count=count)
                if res.get("status") != "completed":
                    send_message(chat_id, f"😕 Merge failed: {res.get('error', 'no clips')}")
                    return
                mid = res["media_id"]
                # Merged file is already 9:16 'resized' — skip quality_probe/resize.
                from backend.pipeline.orchestrator import run as orch_run
                orch_run(stages=["enhance", "caption", "edit", "upload"], media_id=mid)
                from backend.pipeline.scheduler import enqueue_post
                from backend.db import get_setting
                window = (get_setting("approval") or {}).get("auto_post_after_minutes", 60)
                enqueue_post(mid, publish_after_minutes=int(window))
                send_preview(mid, chat_id)
            except Exception as exc:
                send_message(chat_id, f"❌ Merge pipeline failed: {exc}")
        threading.Thread(target=_bg_merge, daemon=True).start()

    elif data == "create_cancel":
        _create_state.pop(chat_id, None)
        _edit_state.pop(chat_id, None)
        send_message(chat_id, "Cancelled.")


# ── Update dispatcher ─────────────────────────────────────────────────────────

_AUTHORIZED_CHAT_ID: int | None = int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None


def _is_authorized(chat_id: int) -> bool:
    return _AUTHORIZED_CHAT_ID is None or chat_id == _AUTHORIZED_CHAT_ID


def handle_update(update: dict) -> None:
    try:
        if "callback_query" in update:
            cq = update["callback_query"]
            cq_chat_id = cq["message"]["chat"]["id"]
            if not _is_authorized(cq_chat_id):
                log.warning("Unauthorized callback from chat_id=%s", cq_chat_id)
                return
            _handle_callback(cq["id"], cq_chat_id, cq.get("data", ""))
            return

        msg = update.get("message", {})
        chat_id: int = msg.get("chat", {}).get("id", 0)
        text: str = msg.get("text", "").strip()
        if not chat_id or not text:
            return

        if not _is_authorized(chat_id):
            log.warning("Unauthorized message from chat_id=%s", chat_id)
            return

        # Edit-caption state machine — consume text if waiting for user input
        if chat_id in _edit_state:
            es = _edit_state.pop(chat_id)
            edit_mode = es.get("mode")
            media_id_edit = es.get("media_id", "")
            def _bg_edit(m=edit_mode, mid=media_id_edit, t=text):
                try:
                    if m == "refine":
                        from backend.pipeline.caption_gen import run as caption_run
                        caption_run(media_id=mid, mode="refine", feedback=t)
                        send_message(chat_id, "✅ Caption refined. Refreshing preview…")
                    else:
                        update_media(mid, {"caption": t})
                        send_message(chat_id, "✅ Caption replaced.")
                    send_preview(mid, chat_id)
                except Exception as exc:
                    send_message(chat_id, f"⚠️ Edit failed: {exc}")

            threading.Thread(target=_bg_edit, daemon=True).start()
            return  # don't fall through to command dispatch

        # /create flow — consume free-text tags when waiting for them
        if chat_id in _create_state and _create_state[chat_id].get("step") == "await_tags":
            state = _create_state[chat_id]
            tags = [t.strip() for t in text.split(",") if t.strip()][:5]
            state.update({"step": "await_merge_count", "tags": tags})
            _prompt_create_confirm(chat_id, state)
            return

        if text.startswith("/queue"):
            _cmd_queue(chat_id)
        elif text.startswith("/pending"):
            _cmd_pending(chat_id)
        elif text.startswith("/stats"):
            _cmd_stats(chat_id)
        elif text.startswith("/settings"):
            _cmd_settings(chat_id)
        elif text.startswith("/create"):
            _cmd_create(chat_id)
        elif text.startswith("/start") or text.startswith("/help"):
            send_message(chat_id, (
                "<b>Travel CMS Bot</b>\n"
                "/queue — show scheduled posts\n"
                "/pending — posts awaiting approval\n"
                "/stats — media statistics\n"
                "/settings — current settings\n"
                "/create — interactive reel creator\n\n"
                "Tap ℹ️ Details · ✏️ Edit · 🕐 Reschedule on any preview."
            ))
    except Exception as exc:
        log.error("handle_update error: %s", exc)


# ── Long-poll runner (dev mode) ───────────────────────────────────────────────

def run_poll() -> None:
    """Blocking long-poll loop. Run in a daemon thread."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set — bot disabled")
        return
    offset = 0
    log.info("Telegram long-poll started")
    while True:
        try:
            resp = _req.get(
                f"{_API}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35,
            ).json()
            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                handle_update(upd)
        except Exception as exc:
            log.error("poll error: %s", exc)
            time.sleep(5)


def start_poll_thread() -> threading.Thread:
    t = threading.Thread(target=run_poll, daemon=True, name="telegram-poll")
    t.start()
    return t
