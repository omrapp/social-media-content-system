"""
Upload resized reels + thumbnails to Cloudflare R2.
After upload, updates media.r2_url, media.thumbnail_url, media.r2_key, status → 'uploaded'.

Usage:
    python -m backend.pipeline.upload_r2
    python -m backend.pipeline.upload_r2 --media-id abc123
"""

import argparse
import logging
import shutil
import subprocess
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig

from backend.config import (
    R2_ENDPOINT, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET, R2_PUBLIC_URL,
    R2_MAX_GB, REELS_READY_DIR, THUMBS_DIR, FONTS_DIR,
)
from backend.db import get_media, get_media_by_id, update_media, update_status, log_pipeline_run, update_pipeline_run, get_setting

log = logging.getLogger(__name__)
R2_MAX_BYTES = int(R2_MAX_GB * 1024 ** 3)


def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=BotoConfig(
            signature_version="s3v4",
            retries={"mode": "adaptive", "max_attempts": 5},
            connect_timeout=10,
            read_timeout=120,
        ),
        region_name="auto",
    )


def _get_thumbnail(media_id: str, video_path: str, thumb_path: str) -> bool:
    """
    Obtain a thumbnail for the reel, preferring the luma-selected one already
    written by resize_clips (THUMBS_DIR/{media_id}.jpg).  Reusing that file
    avoids overwriting the bright-frame thumbnail with a naive first-frame grab.
    Falls back to luma-based extraction if the pre-existing file is missing.
    """
    existing = THUMBS_DIR / f"{media_id}.jpg"
    if existing.exists():
        shutil.copy2(str(existing), thumb_path)
        return True
    # Fallback: luma-based frame selection (same algorithm as resize_clips)
    from backend.pipeline.thumbnail import pick_bright_frame
    return pick_bright_frame(video_path, thumb_path)


def upload_file(client, local_path: str, r2_key: str, content_type: str) -> bool:
    client.upload_file(
        local_path, R2_BUCKET, r2_key,
        ExtraArgs={"ContentType": content_type},
    )
    return True


def public_url(r2_key: str) -> str:
    if R2_PUBLIC_URL:
        return f"{R2_PUBLIC_URL.rstrip('/')}/{r2_key}"
    return f"{R2_ENDPOINT.rstrip('/')}/{R2_BUCKET}/{r2_key}"


def upload_single(client, media_id: str, reel_path: str, media_item: dict | None = None) -> dict:
    reel_file = Path(reel_path)
    if not reel_file.exists():
        return {"status": "error", "reason": "file_not_found"}

    # Size guard: evict oldest posted media if upload would exceed R2_MAX_GB
    try:
        _evict_oldest_posted(client, reel_file.stat().st_size)
    except Exception as exc:
        log.warning("R2 size guard check failed (non-fatal): %s", exc)

    r2_key = f"media/{media_id}/{reel_file.name}"
    upload_file(client, str(reel_file), r2_key, "video/mp4")
    r2_url = public_url(r2_key)

    thumb_path = reel_file.with_suffix(".jpg")
    thumb_url = None
    if _get_thumbnail(media_id, str(reel_file), str(thumb_path)):
        # Apply branding overlay to the authoritative thumbnail when enabled.
        bcfg = get_setting("branding") or {}
        if bcfg.get("overlay_enabled", False) and bcfg.get("show_on_thumbnail", True):
            from backend.pipeline.thumbnail import brand_thumbnail
            from backend.pipeline.overlay import format_tags
            selected_font = (bcfg.get("font") or "").strip()
            font_path = FONTS_DIR / selected_font if selected_font else FONTS_DIR / "PlayfairDisplay-SemiBold.ttf"
            if not font_path.exists():
                font_path = FONTS_DIR / "PlayfairDisplay-SemiBold.ttf"
            if font_path.exists():
                media = media_item or get_media_by_id(media_id)
                if media:
                    loc = format_tags(media.get("tags"))
                    thumb_handle = (bcfg.get("ig_handle") or "").strip()
                    brand_thumbnail(
                        str(thumb_path), loc, thumb_handle,
                        bar_h=int(bcfg.get("bar_height", 45)),
                        font_path=str(font_path),
                        bar_bg_color=str(bcfg.get("bar_bg_color", "#ffffff")),
                        text_color=str(bcfg.get("text_color", "#000000")),
                        bar_opacity=float(bcfg.get("bar_opacity", 1.0)),
                        bar_position=str(bcfg.get("bar_position", "bottom")),
                        location_side=str(bcfg.get("location_side", "left")),
                        handle_side=str(bcfg.get("handle_side", "right")),
                        custom_text=str(bcfg.get("custom_text", "")),
                        font_size=int(bcfg.get("font_size", 0)),
                    )
            else:
                log.warning(
                    "upload_r2: media_id=%s thumbnail branding skipped — font not found at %s",
                    media_id, font_path,
                )
        thumb_key = f"media/{media_id}/{thumb_path.name}"
        upload_file(client, str(thumb_path), thumb_key, "image/jpeg")
        thumb_url = public_url(thumb_key)
        thumb_path.unlink(missing_ok=True)

    update_media(media_id, {
        "r2_url": r2_url,
        "r2_key": r2_key,
        "thumbnail_url": thumb_url or "",
        "status": "uploaded",
    })

    return {"status": "uploaded", "r2_url": r2_url, "thumbnail_url": thumb_url}


def _bucket_size_bytes(client) -> int:
    """Sum of all object sizes in the bucket (paginated)."""
    paginator = client.get_paginator("list_objects_v2")
    total = 0
    for page in paginator.paginate(Bucket=R2_BUCKET):
        for obj in page.get("Contents", []):
            total += obj["Size"]
    return total


def _evict_oldest_posted(client, needed_bytes: int) -> None:
    """
    Delete R2 objects for oldest posted media until bucket has room for needed_bytes.
    Queries posts table for status='posted' ordered by published_at ASC.
    """
    from backend.db import get_supabase, _use_supabase
    if not _use_supabase():
        return

    current = _bucket_size_bytes(client)
    if current + needed_bytes <= R2_MAX_BYTES:
        return

    log.warning(
        "R2 size guard: current=%.1fMB needed=%.1fMB cap=%.1fGB — evicting oldest posted",
        current / 1024**2, needed_bytes / 1024**2, R2_MAX_GB,
    )

    sb = get_supabase()
    # Fetch oldest posted media (via posts table joined manually)
    posts = (
        sb.table("posts")
        .select("media_id,published_at")
        .eq("status", "posted")
        .not_.is_("published_at", "null")
        .order("published_at")
        .limit(50)
        .execute()
        .data or []
    )

    freed = 0
    for post in posts:
        if current + needed_bytes - freed <= R2_MAX_BYTES:
            break
        mid = post.get("media_id")
        if not mid:
            continue
        media = get_media_by_id(mid)
        if not media or not media.get("r2_key"):
            continue
        r2_key = media["r2_key"]
        thumb_key = r2_key.rsplit(".", 1)[0] + ".jpg"
        try:
            obj_size = 0
            try:
                head = client.head_object(Bucket=R2_BUCKET, Key=r2_key)
                obj_size = head.get("ContentLength", 0)
            except Exception:
                pass
            client.delete_object(Bucket=R2_BUCKET, Key=r2_key)
            client.delete_object(Bucket=R2_BUCKET, Key=thumb_key)
            update_media(mid, {"r2_url": None, "r2_key": None, "thumbnail_url": None})
            freed += obj_size
            log.info("R2 evicted media_id=%s r2_key=%s (%.1fMB)", mid, r2_key, obj_size / 1024**2)
        except Exception as exc:
            log.error("R2 eviction failed for media_id=%s: %s", mid, exc)


def cleanup_old(client, days=90):
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    posted = get_media(filters={"status": "posted"})
    deleted = 0
    for item in posted:
        posted_at = item.get("updated_at") or item.get("taken_at")
        if not posted_at or posted_at > cutoff:
            continue
        r2_key = item.get("r2_key")
        if not r2_key:
            continue
        try:
            client.delete_object(Bucket=R2_BUCKET, Key=r2_key)
            thumb_key = r2_key.rsplit(".", 1)[0] + ".jpg"
            client.delete_object(Bucket=R2_BUCKET, Key=thumb_key)
            update_media(item["id"], {"r2_url": "", "r2_key": "", "thumbnail_url": ""})
            deleted += 1
        except Exception:
            pass
    return deleted


def run(media_id=None, cleanup=False):
    if not R2_ENDPOINT or not R2_ACCESS_KEY:
        return {"error": "R2 not configured — set R2_ENDPOINT + R2_ACCESS_KEY in .env"}

    run_log = log_pipeline_run("upload_r2")
    client = get_r2_client()
    uploaded = 0
    failed = 0
    errors = []

    if media_id:
        items = [get_media_by_id(media_id)] if get_media_by_id(media_id) else []
    else:
        items = get_media(filters={"status": "resized"})

    for item in items:
        reel_path = item.get("reel_ready_path")
        if not reel_path:
            if media_id:
                # Specific media requested — surface the gap rather than silently skip
                update_status(item["id"], "error", "no_reel_ready_path")
                failed += 1
                errors.append(item["id"])
            continue
        try:
            result = upload_single(client, item["id"], reel_path, media_item=item)
            if result["status"] == "uploaded":
                uploaded += 1
            else:
                update_status(item["id"], "error", result.get("reason"))
                failed += 1
                errors.append(item["id"])
        except Exception as e:
            update_status(item["id"], "error", str(e))
            failed += 1
            errors.append(item["id"])

    cleaned = 0
    if cleanup:
        cleaned = cleanup_old(client)

    # Purge old local files if any uploads succeeded
    if uploaded > 0:
        try:
            from backend.pipeline.purge_reels import purge_local
            purge_local(dry_run=False)
        except Exception as exc:
            log.warning("purge_reels (non-fatal): %s", exc)

    result = {"uploaded": uploaded, "failed": failed, "cleaned": cleaned, "total": len(items)}
    if run_log:
        from datetime import datetime, timezone
        update_pipeline_run(run_log["id"], {
            "status": "completed" if not failed else "failed",
            "items_processed": uploaded,
            "items_failed": failed,
            "metadata": {"errors": errors} if errors else None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-id", help="Upload single media item")
    parser.add_argument("--cleanup", action="store_true", help="Delete R2 objects >90 days after posting")
    args = parser.parse_args()
    result = run(media_id=args.media_id, cleanup=args.cleanup)
    print(f"Uploaded: {result['uploaded']}/{result['total']}. Failed: {result['failed']}. Cleaned: {result['cleaned']}")
