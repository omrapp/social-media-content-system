import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.db import get_media, get_media_by_id, update_media, update_status, STATUS_FLOW
from backend.api.auth import verify_token
from backend.config import R2_BUCKET

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"], dependencies=[Depends(verify_token)])


class MediaUpdate(BaseModel):
    caption: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    hook_score: float | None = None
    metadata: dict | None = None


class ReprocessRequest(BaseModel):
    target_status: str = "raw"


class EnhanceRequest(BaseModel):
    remove_watermarks: bool = False     # watermark blur off by default
    watermark_position: Literal["bottom", "top", "both"] = "bottom"
    stabilize: bool = False              # False = fast re-enhance (no vidstab)


@router.get("")
def list_media(
    status: str | None = None,
    category: str | None = None,
    source: str | None = None,
    tags: list[str] | None = Query(default=None),
    media_type: str | None = None,
    sort: str = "taken_at_desc",
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    from backend.db import _use_supabase, get_supabase, db_retry

    # Supabase path — supports multi-status, sort
    if _use_supabase():
        def _fetch():
            q = get_supabase().table("media").select("*")
            if status:
                statuses = [s.strip() for s in status.split(",") if s.strip()]
                if len(statuses) == 1:
                    q = q.eq("status", statuses[0])
                elif statuses:
                    q = q.in_("status", statuses)
            else:
                q = q.neq("status", "deleted")
            if category:
                q = q.eq("category", category)
            if source:
                q = q.eq("source", source)
            if tags:
                q = q.contains("tags", tags)
            if media_type:
                q = q.eq("media_type", media_type)
            if sort == "taken_at_asc":
                q = q.order("taken_at", desc=False)
            else:
                q = q.order("taken_at", desc=True)
            return q.range(offset, offset + limit - 1).execute().data or []
        return db_retry(_fetch)

    # SQLite fallback
    filters: dict = {}
    statuses_list: list[str] = []
    if status:
        parts = [s.strip() for s in status.split(",") if s.strip()]
        if len(parts) == 1:
            filters["status"] = parts[0]
        elif parts:
            statuses_list = parts
    if category:
        filters["category"] = category
    if source:
        filters["source"] = source
    if media_type:
        filters["media_type"] = media_type
    rows = get_media(filters=filters, limit=limit, offset=offset)
    if statuses_list:
        rows = [r for r in rows if r.get("status") in statuses_list]
    if tags:
        rows = [r for r in rows if set(tags) & set(r.get("tags") or [])]
    return rows


@router.get("/count")
def count(category: str | None = None, tags: list[str] | None = Query(default=None)):
    """Count unposted raw VIDEO clips available for a merge montage. Drives the
    Create-page availability indicator. Declared before /{media_id} so the
    literal path isn't captured as a media_id."""
    from backend.db import count_raw_videos
    return {"count": count_raw_videos(category, tags)}


@router.get("/{media_id}")
def get_single(media_id: str):
    item = get_media_by_id(media_id)
    if not item:
        raise HTTPException(404, "Media not found")
    return item


@router.put("/{media_id}")
def update_single(media_id: str, body: MediaUpdate):
    item = get_media_by_id(media_id)
    if not item:
        raise HTTPException(404, "Media not found")
    data = body.model_dump(exclude_none=True)
    # Merge metadata patch into existing JSONB — never replace wholesale
    if "metadata" in data:
        existing = item.get("metadata") or {}
        if not isinstance(existing, dict):
            existing = {}
        data["metadata"] = {**existing, **data["metadata"]}
    if data:
        update_media(media_id, data)
    return get_media_by_id(media_id)


@router.delete("/{media_id}")
def delete_single(media_id: str):
    item = get_media_by_id(media_id)
    if not item:
        raise HTTPException(404, "Media not found")
    # Delete R2 objects before soft-deleting the DB row (best-effort)
    r2_key = item.get("r2_key") or ""
    if r2_key:
        try:
            from backend.pipeline.upload_r2 import get_r2_client
            client = get_r2_client()
            client.delete_object(Bucket=R2_BUCKET, Key=r2_key)
            thumb_key = r2_key.rsplit(".", 1)[0] + ".jpg"
            client.delete_object(Bucket=R2_BUCKET, Key=thumb_key)
            log.info("Deleted R2 objects for media_id=%s key=%s", media_id, r2_key)
        except Exception as exc:
            log.warning("R2 delete failed for media_id=%s (non-fatal): %s", media_id, exc)
    update_status(media_id, "deleted")
    return {"ok": True}


@router.post("/{media_id}/reprocess")
def reprocess(media_id: str, body: ReprocessRequest):
    if body.target_status not in STATUS_FLOW:
        raise HTTPException(400, f"Invalid status '{body.target_status}'. Allowed: {STATUS_FLOW}")
    item = get_media_by_id(media_id)
    if not item:
        raise HTTPException(404, "Media not found")
    update_status(media_id, body.target_status)
    return {"media_id": media_id, "status": body.target_status}


@router.post("/{media_id}/enhance")
async def trigger_enhance(media_id: str, body: EnhanceRequest):
    """
    Re-run the enhance stage with custom watermark/stabilize settings.
    Designed for Preview page re-enhancement (stabilize=False by default = fast).
    Runs synchronously in a thread pool to avoid blocking the event loop.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from backend.pipeline.enhance_video import enhance_single

    item = get_media_by_id(media_id)
    if not item:
        raise HTTPException(404, "Media not found")
    if item.get("media_type") != "VIDEO":
        raise HTTPException(400, "Only VIDEO media can be enhanced")

    settings = {
        "stabilize": body.stabilize,
        "remove_watermarks": body.remove_watermarks,
        "watermark_position": body.watermark_position,
    }

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(pool, lambda: enhance_single(item, settings))

    if result.get("status") == "error":
        raise HTTPException(500, f"Enhancement failed: {result.get('reason')}")

    updated = get_media_by_id(media_id)
    return {"ok": True, "reel_ready_path": result.get("output"), "media": updated}
