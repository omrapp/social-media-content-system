import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import (
    get_posts, get_post_by_id, create_post, update_post, delete_post, get_media_by_id,
    get_raw_media_for_create, get_setting,
    update_media, update_status,
)
from backend.api.auth import verify_token
from backend.api.ws import broadcast_post_status

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/posts", tags=["posts"], dependencies=[Depends(verify_token)])


class PostCreate(BaseModel):
    media_id: str
    caption: str | None = Field(default=None, max_length=2200)
    hashtags_en: list[str] | None = None
    hashtags_ar: list[str] | None = None
    scheduled_at: str | None = None
    platforms: list[str] | None = None


class PostUpdate(BaseModel):
    caption: str | None = Field(default=None, max_length=2200)
    # Per-platform captions kept in sync on regenerate so IG/TikTok/YouTube
    # don't publish stale text (issue: regen only updated `caption`).
    caption_ig: str | None = Field(default=None, max_length=2200)
    caption_tt: str | None = Field(default=None, max_length=2200)
    caption_yt_title: str | None = Field(default=None, max_length=100)
    caption_yt_description: str | None = Field(default=None, max_length=5000)
    hashtags_en: list[str] | None = None
    hashtags_ar: list[str] | None = None
    scheduled_at: str | None = None
    status: str | None = None
    platforms: list[str] | None = None
    # edit_requests is stored on the media row (not posts), forwarded by the handler.
    edit_requests: list | None = None


class ApprovePlatformsRequest(BaseModel):
    platforms: list[str]


class ReorderItem(BaseModel):
    id: str
    scheduled_at: str


class RescheduleRequest(BaseModel):
    scheduled_at: str
    window_minutes: int = Field(default=60, ge=1, le=1440)  # 1 min – 24 h


class AutoScheduleRequest(BaseModel):
    media_ids: list[str] = Field(..., max_length=100)
    interval_minutes: int = Field(default=120, ge=30, le=1440)
    start_at: str | None = None


@router.get("")
def list_posts(
    status: str | None = None,
    media_id: str | None = None,
    limit: int = Query(default=50, le=1000),
    sort: str = Query(default="scheduled_asc", pattern="^scheduled_(asc|desc)$"),
):
    filters: dict = {}
    if status:
        filters["status"] = status
    if media_id:
        filters["media_id"] = media_id
    return get_posts(filters=filters or None, limit=limit, desc=(sort == "scheduled_desc"))


@router.post("")
def create(body: PostCreate):
    media = get_media_by_id(body.media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    data = body.model_dump(exclude_none=True)
    if "platforms" not in data:
        from backend.pipeline.scheduler import _default_platforms
        data["platforms"] = _default_platforms()
    return create_post(data)


@router.put("/{post_id}")
def update(post_id: str, body: PostUpdate):
    data = body.model_dump(exclude_none=True)
    # edit_requests lives on the media row — pop before writing to posts table.
    edit_reqs = data.pop("edit_requests", None)

    if not data and edit_reqs is None:
        raise HTTPException(400, "No fields to update")

    if data:
        update_post(post_id, data)

    if edit_reqs is not None:
        post = get_post_by_id(post_id)
        if post and post.get("media_id"):
            update_media(post["media_id"], {"edit_requests": edit_reqs})

    return {"ok": True}


@router.delete("/{post_id}")
async def delete(post_id: str):
    delete_post(post_id)
    asyncio.create_task(broadcast_post_status(post_id, "deleted"))
    return {"ok": True}


async def _publish_post_now(post_id: str) -> None:
    """Publish a post to all its platforms now (background task)."""
    from backend.pipeline.scheduler import publish_post
    loop = asyncio.get_running_loop()
    try:
        post = get_post_by_id(post_id)
        if not post:
            log.error("_publish_post_now: post %s not found", post_id)
            return
        results = await loop.run_in_executor(None, lambda: publish_post(post))
        log.info("approve-published post %s → %s", post_id, results)
        await broadcast_post_status(
            post_id, "posted",
            **{f"{platform}_id": vid for platform, vid in results.items() if vid},
        )
    except Exception as exc:
        log.error("_publish_post_now: publish failed for %s: %s", post_id, exc)
        update_post(post_id, {"status": "error", "error_message": str(exc)})
        await broadcast_post_status(post_id, "error")


async def _publish_post_platforms(post_id: str, platforms: list[str]) -> None:
    """Publish a post to specific platforms only (background task)."""
    from backend.pipeline.scheduler import publish_post
    loop = asyncio.get_running_loop()
    try:
        post = get_post_by_id(post_id)
        if not post:
            log.error("_publish_post_platforms: post %s not found", post_id)
            return
        results = await loop.run_in_executor(None, lambda: publish_post(post, platforms_override=platforms))
        log.info("approve-platforms published post %s to %s → %s", post_id, platforms, results)
        await broadcast_post_status(
            post_id, "posted",
            **{f"{platform}_id": vid for platform, vid in results.items() if vid},
        )
    except Exception as exc:
        log.error("_publish_post_platforms: publish failed for %s: %s", post_id, exc)
        update_post(post_id, {"status": "error", "error_message": str(exc)})
        await broadcast_post_status(post_id, "error")


@router.post("/{post_id}/approve")
async def approve(post_id: str):
    """Approve — publish immediately to all enabled platforms (bypass window)."""
    post = get_post_by_id(post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    # Flip out of 'preview' so the daemon won't also pick it up (no double-publish).
    update_post(post_id, {"status": "publishing"})
    asyncio.create_task(broadcast_post_status(post_id, "publishing"))
    asyncio.create_task(_publish_post_now(post_id))
    return {"post_id": post_id, "status": "publishing"}


@router.post("/{post_id}/approve-platforms")
async def approve_platforms_route(post_id: str, body: ApprovePlatformsRequest):
    """Approve and publish to specific platforms only (e.g. IG+TikTok without YouTube)."""
    if not body.platforms:
        raise HTTPException(400, "platforms list cannot be empty")
    post = get_post_by_id(post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    update_post(post_id, {"status": "publishing"})
    asyncio.create_task(broadcast_post_status(post_id, "publishing"))
    asyncio.create_task(_publish_post_platforms(post_id, body.platforms))
    return {"post_id": post_id, "status": "publishing", "platforms": body.platforms}


@router.post("/{post_id}/cancel")
async def cancel(post_id: str):
    """Soft-cancel: shelve the post and flag media as do_not_use so it never
    re-enters the create queue. The media row is kept in the DB."""
    post = get_post_by_id(post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    update_post(post_id, {"status": "cancelled"})
    if post.get("media_id"):
        update_media(post["media_id"], {"do_not_use": True})
    asyncio.create_task(broadcast_post_status(post_id, "cancelled"))
    return {"post_id": post_id, "status": "cancelled"}


@router.post("/{post_id}/reject")
async def reject(post_id: str):
    """
    Hard-reject: permanently delete the post record, mark media as deleted,
    remove local reel + thumbnail files, and delete R2 objects (best-effort).
    Use when this video clip is unwanted and should never be reused.
    """
    post = get_post_by_id(post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    media_id = post.get("media_id", "")
    media = get_media_by_id(media_id) if media_id else None

    if media:
        # 1. Delete R2 objects (best-effort — non-fatal)
        r2_key = media.get("r2_key") or ""
        if r2_key:
            try:
                from backend.config import R2_BUCKET
                from backend.pipeline.upload_r2 import get_r2_client
                client = get_r2_client()
                client.delete_object(Bucket=R2_BUCKET, Key=r2_key)
                thumb_key = r2_key.rsplit(".", 1)[0] + ".jpg"
                client.delete_object(Bucket=R2_BUCKET, Key=thumb_key)
            except Exception as exc:
                log.warning("reject: R2 delete failed for post %s (non-fatal): %s", post_id, exc)

        # 2. Delete local reel file
        reel_path = media.get("reel_ready_path") or ""
        if reel_path:
            try:
                from pathlib import Path as _Path
                _Path(reel_path).unlink(missing_ok=True)
            except Exception as exc:
                log.warning("reject: local reel delete failed for post %s (non-fatal): %s", post_id, exc)

        # 3. Delete local thumbnail
        if media_id:
            try:
                from backend.config import THUMBS_DIR
                (THUMBS_DIR / f"{media_id}.jpg").unlink(missing_ok=True)
            except Exception as exc:
                log.warning("reject: thumb delete failed for post %s (non-fatal): %s", post_id, exc)

        # 4. Soft-delete media row so it's never re-selected
        update_status(media_id, "deleted")

    # 5. Hard-delete post record
    delete_post(post_id)
    asyncio.create_task(broadcast_post_status(post_id, "deleted"))
    return {"post_id": post_id, "status": "deleted"}


@router.post("/{post_id}/reschedule")
async def reschedule(post_id: str, body: RescheduleRequest):
    new_at = datetime.fromisoformat(body.scheduled_at)
    publish_after = new_at + timedelta(minutes=body.window_minutes)
    update_post(post_id, {
        "scheduled_at": new_at.isoformat(),
        "publish_after": publish_after.isoformat(),
        "status": "preview",
    })
    asyncio.create_task(broadcast_post_status(
        post_id, "preview",
        scheduled_at=new_at.isoformat(),
        publish_after=publish_after.isoformat(),
    ))
    return {"post_id": post_id, "scheduled_at": new_at.isoformat()}


@router.post("/{post_id}/publish")
async def publish_now(post_id: str):
    """Publish immediately to all enabled platforms (alias for approve)."""
    post = get_post_by_id(post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    update_post(post_id, {"status": "publishing"})
    asyncio.create_task(broadcast_post_status(post_id, "publishing"))
    asyncio.create_task(_publish_post_now(post_id))
    return {"post_id": post_id, "status": "publishing"}


class PostCreateFromFilter(BaseModel):
    category: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = Field(default=None, max_length=20)
    strategy: Literal["best", "random", "diverse", "story"] = "diverse"
    exclude_ids: list[str] = Field(default=[], max_length=50)
    source: Literal["api", "telegram"] = "api"
    # Pre-selected clip from the Create wizard's preview step. When set the
    # backend skips its own strategy pick and processes exactly this clip.
    media_id: str | None = Field(default=None, max_length=64)
    # Optional per-post overrides picked in the wizard's customize step.
    # music_path: a served /assets/music/<file> URL (validated under MUSIC_DIR).
    # lut: a LUTS_DIR-relative .cube file ("warm.cube" | "cinematic/x.cube").
    music_path: str | None = Field(default=None, max_length=500)
    lut: str | None = Field(default=None, max_length=200)
    # Manual-wizard "keep original" intent (auto/timer flow leaves these False):
    # no track picked → keep the clip's own audio (skip auto music); no LUT picked
    # → keep the original video look (skip colour grade).
    keep_original_audio: bool = False
    no_lut: bool = False
    # Per-run decaption override: None = respect global decaption.enabled,
    # True/False = force on/off for this reel only.
    decaption: bool | None = None
    # Per-run voiceover override: None = respect global voiceover.enabled,
    # True/False = force on/off for this reel only (1.8.0).
    voiceover: bool | None = None


class SelectPreview(BaseModel):
    """Dry-run clip selection for the Create wizard: pick a clip by strategy/
    filters WITHOUT running the pipeline, so the user can preview it first."""
    category: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = Field(default=None, max_length=20)
    strategy: Literal["best", "random", "diverse", "story"] = "diverse"
    exclude_ids: list[str] = Field(default=[], max_length=50)


class MergeCreate(BaseModel):
    # hand-pick path: explicit clips (+ optional order). Client sends media IDs
    # only — never file paths; merge_clips resolves paths from the DB.
    media_ids: list[str] | None = Field(default=None, max_length=8)
    order: list[str] | None = Field(default=None, max_length=8)
    # auto-select path: filter + count
    category: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = Field(default=None, max_length=20)
    count: int | None = Field(default=None, ge=2, le=8)
    # per-request merge.* overrides (transition, target_duration_s, etc.)
    overrides: dict | None = None
    # Per-run decaption override (manual wizard): None = respect global setting.
    decaption: bool | None = None
    # Per-run voiceover override (manual wizard): None = respect global setting (1.8.0).
    voiceover: bool | None = None
    source: Literal["api", "telegram"] = "api"


def _pick_media_for_create(
    strategy: str,
    category: str | None,
    tags: list[str] | None,
    exclude_ids: list[str],
) -> dict | None:
    """
    Pick one unposted raw media clip according to *strategy*.
    Returns the media dict or None if nothing is available (never raises).
    Reused by both the HTTP endpoint, the daemon auto-create job, and
    merge_clips._resolve_clips' no-category fallback — this exact positional
    shape (strategy, category, tags, exclude_ids) is load-bearing.
    """
    try:
        if strategy == "story":
            log.warning("_pick_media_for_create: strategy='story' is no longer supported (series feature removed)")
            return None
        elif strategy == "diverse":
            from backend.db import get_diverse_raw_media
            return get_diverse_raw_media(exclude_ids=exclude_ids, strategy="random")
        else:
            if not category:
                log.warning("_pick_media_for_create: strategy=%s requires category", strategy)
                return None
            return get_raw_media_for_create(
                category, tags,
                exclude_ids=exclude_ids,
                strategy=strategy,
            )
    except Exception as exc:
        log.error("_pick_media_for_create: unhandled error: %s", exc)
        return None


@router.post("/select-preview")
async def select_preview(body: SelectPreview):
    """Dry-run: pick one unposted raw clip by strategy/filters and return its id +
    path WITHOUT processing. Powers the Create wizard's preview step so the user
    can review the clip (and re-pick a different one) before running the pipeline.
    exclude_ids lets 'Pick a new video' cycle past the currently-shown clip."""
    if body.strategy == "story":
        raise HTTPException(400, "strategy='story' is no longer supported — the series/story-arc feature has been removed")
    media = _pick_media_for_create(
        body.strategy, body.category, body.tags, body.exclude_ids,
    )
    if not media:
        if body.strategy == "diverse":
            raise HTTPException(404, "No unposted clips available (diverse — all categories in cooldown or unclassified)")
        if not body.category:
            raise HTTPException(400, "category required for strategy='best'|'random'")
        raise HTTPException(404, f"No unposted clips for category={body.category}")
    return {
        "media_id": media["id"],
        "local_path": media.get("local_path"),
        "category": media.get("category"),
        "tags": media.get("tags"),
        "duration_s": media.get("duration_s"),
    }


@router.post("/create")
async def create_from_filter(body: PostCreateFromFilter):
    """
    Pick one unposted raw media, run resize+caption pipeline, create a preview post.

    strategy='diverse' (default): cross-category pick with category cooldown.
    strategy='best'|'random': hook_score/random pick — requires category.
    """
    if body.strategy == "story":
        raise HTTPException(400, "strategy='story' is no longer supported — the series/story-arc feature has been removed")

    # Auto-run merge gate: when enabled, build a merged reel instead of a single
    # clip. Off by default → existing single-clip behavior is untouched.
    merge_cfg = get_setting("merge") or {}
    if merge_cfg.get("enabled") and merge_cfg.get("auto_run"):
        # auto_count on → let merge_clips derive the count from target duration.
        mk = {"category": body.category, "tags": body.tags}
        if not merge_cfg.get("auto_count", True):
            mk["count"] = int(merge_cfg.get("clips_per_reel", 4))
        asyncio.create_task(_merge_and_enqueue(mk, body.source))
        return {"status": "merge_started", "source": body.source, "mode": "merge"}

    # media_id set → the wizard already previewed and locked this exact clip;
    # honor it instead of re-picking. Otherwise fall back to a strategy pick.
    if body.media_id:
        media = get_media_by_id(body.media_id)
        if not media:
            raise HTTPException(404, f"media_id {body.media_id} not found")
    else:
        media = _pick_media_for_create(
            body.strategy, body.category, body.tags, body.exclude_ids,
        )
        if not media:
            if body.strategy == "diverse":
                raise HTTPException(404, "No unposted clips available (diverse — all categories in cooldown or unclassified)")
            else:
                if not body.category:
                    raise HTTPException(400, "category required for strategy='best'|'random'")
                raise HTTPException(404, f"No unposted clips for category={body.category}")

    # Resolve optional per-post overrides picked in the wizard. music_path is a
    # served URL → validated + resolved to an absolute file under MUSIC_DIR; lut
    # is a LUTS_DIR-relative .cube passed straight through to the edit stage.
    music_override = None
    if body.music_path:
        from backend.pipeline.merge_clips import _safe_music_path
        music_override = _safe_music_path(body.music_path)
        if not music_override:
            raise HTTPException(400, "music_path must resolve under the music library")
    lut_override = body.lut or None

    log.info("create: picked media_id=%s strategy=%s source=%s category=%s music=%s lut=%s keep_audio=%s no_lut=%s decap=%s",
             media["id"], body.strategy, body.source, body.category,
             bool(music_override), lut_override or "-",
             body.keep_original_audio, body.no_lut, body.decaption)

    # Run resize + caption pipeline stages async (non-blocking response)
    asyncio.create_task(_pipeline_and_enqueue(
        media["id"], body.source,
        music_override=music_override, lut_override=lut_override,
        keep_original_audio=body.keep_original_audio, no_lut=body.no_lut,
        decaption_force=body.decaption, voiceover_force=body.voiceover,
    ))

    return {"media_id": media["id"], "status": "pipeline_started", "source": body.source}


async def _merge_and_enqueue(
    merge_kwargs: dict, source: str, no_lut: bool = False,
    voiceover_force: bool | None = None, auto_publish_slot: "datetime | None" = None,
) -> None:
    """Render a merged reel (heavy FFmpeg — offloaded), then run the edit→upload
    tail and enqueue a preview post on the merged media row."""
    import asyncio
    from backend.api.ws import broadcast
    from backend.pipeline.merge_clips import run as merge_run

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, lambda: merge_run(**merge_kwargs))
    except Exception as exc:
        log.exception("merge: render crashed")
        await broadcast("pipeline_failed", {"error": f"merge crashed: {exc}", "source": source})
        return
    if result.get("status") != "completed":
        err = result.get("error", "merge failed")
        log.error("merge: %s", err)
        await broadcast("pipeline_failed", {"error": err, "source": source})
        return
    # Merged file is already a 9:16 'resized' reel — skip quality_probe/resize.
    # music_path (if any) was muxed at the merge stage; a wizard-picked LUT rides
    # the edit tail (skipped automatically when merge.grade already graded).
    lut_override = (merge_kwargs.get("settings") or {}).get("lut") or None
    # no_lut (manual merge, no LUT picked) skips the edit-tail colour grade so the
    # montage keeps its native look. Decaption for merge runs inside merge_clips
    # (per-source pre-pass), driven by settings.decaption_force — not the tail.
    await _pipeline_and_enqueue(
        result["media_id"], source,
        auto_publish_slot=auto_publish_slot,
        stages=["enhance", "caption", "voiceover", "edit", "upload"],
        lut_override=lut_override, no_lut=no_lut and not lut_override,
        voiceover_force=voiceover_force,
    )


@router.post("/create-merge")
async def create_merge(body: MergeCreate):
    """Stitch N clips into one reel (hand-pick via media_ids, or auto-select via
    category + tags + count), then run the edit→upload pipeline and enqueue a
    preview post. Heavy render runs in the background (non-blocking response)."""
    # Hand-pick needs media_ids; auto-select REQUIRES a category (tags
    # optional — the montage mixes tags within that one category).
    if not body.media_ids and not body.category:
        raise HTTPException(400, "category is required for auto-select merge")
    # Defense in depth: a caller-supplied music_path must resolve under the music
    # library before it ever reaches FFmpeg (merge_clips re-validates too).
    ov = dict(body.overrides or {})
    if ov.get("music_path"):
        from backend.pipeline.merge_clips import _safe_music_path
        if not _safe_music_path(ov["music_path"]):
            raise HTTPException(400, "music_path must resolve under the music library")
    # Per-run decaption override → merge_clips reads settings.decaption_force.
    if body.decaption is not None:
        ov["decaption_force"] = body.decaption
    # Manual merge with no LUT picked → skip the edit-tail colour grade (keep the
    # montage's native look). "keep original music" is handled via the caller's
    # overrides.audio_mode="original" (muxed at the merge stage).
    no_lut = not ov.get("lut")
    merge_kwargs = {
        "media_ids": body.media_ids,
        "order": body.order,
        "category": body.category,
        "tags": body.tags,
        "count": body.count,
        "settings": ov or None,
    }
    asyncio.create_task(_merge_and_enqueue(merge_kwargs, body.source, no_lut=no_lut, voiceover_force=body.voiceover))
    return {"status": "merge_started", "source": body.source}


async def _pipeline_and_enqueue(
    media_id: str,
    source: str,
    auto_publish_slot: "datetime | None" = None,
    stages: list[str] | None = None,
    music_override: str | None = None,
    lut_override: str | None = None,
    keep_original_audio: bool = False,
    no_lut: bool = False,
    decaption_force: bool | None = None,
    voiceover_force: bool | None = None,
) -> None:
    """
    Run the resize+upload+caption pipeline then enqueue a preview post.

    auto_publish_slot: when set (publish mode), the created post's publish_after is
        set to this slot datetime so the daemon auto-publishes without human approval.
        When None (approval mode), a Telegram preview is pushed for human approval.
    stages: override the stage list — merged reels skip quality_probe/resize since
        merge_clips already produced a 9:16 'resized' file.
    """
    import asyncio
    from backend.api.ws import broadcast

    # quality_probe runs FIRST: junk footage is scored and (when
    # selection.min_quality_score>0) rejected before any resize/enhance/edit.
    # caption runs BEFORE edit so the edit stage's hook + hashtag overlays (Enh F)
    # have real text to draw — caption only needs category/tags.
    # decaption runs AFTER quality_probe, BEFORE resize: it cleans burned-in IG
    # captions/watermarks off the raw clip (cached, no-op when disabled) so resize
    # consumes the cleaned file. Feature default-OFF; the stage self-gates.
    _stages = stages or ["quality_probe", "decaption", "resize", "enhance", "caption", "voiceover", "edit", "upload"]

    def _sync():
        from backend.pipeline.orchestrator import run as orch_run
        return orch_run(
            stages=_stages, media_id=media_id,
            music_override=music_override, lut_override=lut_override,
            keep_original_audio=keep_original_audio, no_lut=no_lut,
            decaption_force=decaption_force, voiceover_force=voiceover_force,
        )

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _sync)

        # Orchestrator returns status='failed' without raising — don't enqueue a
        # half-processed clip; surface the failing stage instead.
        if result.get("status") != "completed":
            failed = ", ".join(result.get("failed_stages") or []) or "unknown"
            stage_errs = {
                s: r.get("error")
                for s, r in (result.get("stages") or {}).items()
                if isinstance(r, dict) and r.get("error")
            }
            msg = f"pipeline failed at stage(s): {failed}"
            log.error("create: media_id=%s %s — details=%s", media_id, msg, stage_errs)
            await broadcast("pipeline_failed", {
                "media_id": media_id, "source": source,
                "error": msg, "stages": stage_errs,
            })
            return

        # Enqueue as preview post
        from backend.pipeline.scheduler import enqueue_post
        from backend.db import get_setting, update_post
        approval = get_setting("approval") or {}
        platforms_cfg = get_setting("platforms") or {}
        _all_platforms = ["instagram", "tiktok", "youtube"]
        enabled_minutes = [
            approval.get(f"{p}_auto_minutes", 60)
            for p in _all_platforms
            if platforms_cfg.get(f"{p}_enabled", p == "instagram")
            and approval.get(f"{p}_auto_enabled", True)
        ]
        # Use the longest window across auto-enabled platforms so all go out together.
        # Fall back to legacy key or 60 min if everything is manual.
        window = max(enabled_minutes) if enabled_minutes else approval.get("auto_post_after_minutes", 60)
        post = enqueue_post(media_id, publish_after_minutes=int(window))
        log.info("create: media_id=%s pipeline complete, enqueued as preview", media_id)

        if auto_publish_slot is not None:
            # Publish mode: set real slot so daemon picks it up without human approval.
            if post:
                post_id = post[0]["id"] if isinstance(post, list) else post.get("id")
                if post_id:
                    slot_iso = auto_publish_slot.isoformat()
                    update_post(post_id, {"slot_at": slot_iso, "publish_after": slot_iso})
                    log.info("create: media_id=%s auto-publish slot set to %s", media_id, slot_iso)

        # Push Telegram preview (both approval mode and auto-publish mode when always_preview=True).
        tg_cfg = get_setting("telegram") or {}
        push_preview = tg_cfg.get("preview_push_enabled", True) and (
            auto_publish_slot is None or tg_cfg.get("always_preview", True)
        )
        if push_preview:
            try:
                from backend.pipeline.telegram_bot import send_preview
                await loop.run_in_executor(None, lambda: send_preview(media_id))
                log.info("create: media_id=%s Telegram preview pushed", media_id)
            except Exception as tg_exc:
                log.warning("create: media_id=%s Telegram preview push failed (non-fatal): %s", media_id, tg_exc)

        await broadcast("pipeline_complete", {"media_id": media_id, "source": source})
    except Exception as exc:
        log.exception("create: media_id=%s pipeline crashed", media_id)
        await broadcast("pipeline_failed", {"media_id": media_id, "error": str(exc)})


@router.post("/auto-schedule")
def auto_schedule(body: AutoScheduleRequest):
    from backend.pipeline.slots import next_free_slot
    from backend.pipeline.scheduler import _default_platforms

    cursor = datetime.now(timezone.utc)
    if body.start_at:
        try:
            cursor = datetime.fromisoformat(body.start_at)
        except ValueError:
            pass

    scheduled = []
    for mid in body.media_ids:
        media = get_media_by_id(mid)
        if not media:
            continue
        try:
            slot = next_free_slot(cursor)
        except RuntimeError as exc:
            log.error("auto_schedule: no slot available after %s: %s", cursor, exc)
            break
        post = create_post({
            "media_id": mid,
            "caption": media.get("caption", ""),
            "status": "preview",
            "scheduled_at": slot.isoformat(),
            "publish_after": slot.isoformat(),
            "slot_at": slot.isoformat(),
            "platforms": _default_platforms(),
        })
        scheduled.append({"media_id": mid, "slot_at": slot.isoformat(), "post": post})
        # Advance cursor past this slot so the next iteration picks the next free one
        cursor = slot + timedelta(minutes=1)

    return {"scheduled": len(scheduled), "posts": scheduled}


@router.post("/{post_id}/retry-youtube")
async def retry_youtube(post_id: str):
    """
    Retry YouTube upload for a post that failed with yt_error.
    If media lacks r2_url but has reel_ready_path, uploads to R2 first.
    """
    post = get_post_by_id(post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    media = get_media_by_id(post["media_id"])
    if not media:
        raise HTTPException(404, "Media not found")

    # Upload to R2 first if missing r2_url but local file exists
    r2_url = media.get("r2_url") or ""
    if not r2_url:
        reel_path = media.get("reel_ready_path") or ""
        if not reel_path:
            raise HTTPException(400, f"Media {media['id']} has no reel_ready_path — run resize stage first")
        try:
            from backend.pipeline.upload_r2 import upload_single, get_r2_client
            client = get_r2_client()
            result = upload_single(client, media["id"], reel_path)
            if result["status"] != "uploaded":
                raise HTTPException(500, f"R2 upload failed: {result.get('reason', 'unknown')}")
            r2_url = result["r2_url"]
            # Refresh media after upload
            media = get_media_by_id(post["media_id"])
        except HTTPException:
            raise
        except Exception as exc:
            log.error("retry_youtube: R2 upload failed for media %s: %s", media["id"], exc)
            raise HTTPException(500, f"R2 upload error: {exc}")

    try:
        from backend.pipeline.youtube_publish import upload_short as yt_upload
        from backend.pipeline.scheduler import _build_platform_caption
        yt_title = post.get("caption_yt_title") or (post.get("caption", "").split("\n", 1)[0] or "")
        # Merge AR caption from media so bilingual description is built correctly.
        _post_ar = {**post, "caption_ig_ar": media.get("caption_ig_ar") or ""}
        yt_description = _build_platform_caption(_post_ar, "youtube")
        yt_id = yt_upload(
            media,
            yt_description,
            post.get("hashtags_en") or [],
            title_override=yt_title,
            hashtags_ar=post.get("hashtags_ar") or [],
        )
        update_post(post_id, {"yt_video_id": yt_id, "yt_error": None})
        log.info("retry_youtube: uploaded post %s → yt_id=%s", post_id, yt_id)
        return {"post_id": post_id, "yt_video_id": yt_id, "r2_url": r2_url}
    except Exception as exc:
        log.error("retry_youtube: YouTube upload failed for post %s: %s", post_id, exc)
        update_post(post_id, {"yt_error": str(exc)[:500]})
        raise HTTPException(500, f"YouTube upload failed: {exc}")


@router.put("/reorder")
def reorder(items: list[ReorderItem]):
    for item in items:
        update_post(item.id, {"scheduled_at": item.scheduled_at})
    return {"reordered": len(items)}
