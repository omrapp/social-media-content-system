from fastapi import APIRouter, Depends

from backend.db import get_all_media, _use_supabase, get_supabase
from backend.api.auth import verify_token

router = APIRouter(prefix="/api/statistics", tags=["statistics"], dependencies=[Depends(verify_token)])

FUNNEL_STAGES = ["raw", "resized", "enhanced", "edited", "uploaded", "posted"]


@router.get("/overview")
def statistics_overview():
    media = get_all_media()
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for m in media:
        s = m.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
        p = m.get("category") or "unclassified"
        by_category[p] = by_category.get(p, 0) + 1

    funnel = [{"stage": s, "count": by_status.get(s, 0)} for s in FUNNEL_STAGES]

    return {
        "total_media": len(media),
        "by_status": by_status,
        "by_category": by_category,
        "funnel": funnel,
    }


@router.get("/categories")
def statistics_categories():
    media = get_all_media()
    categories: dict[str, dict] = {}
    for m in media:
        c = m.get("category") or "unclassified"
        if c not in categories:
            categories[c] = {"category": c, "total": 0, "posted": 0, "error": 0, "raw": 0}
        categories[c]["total"] += 1
        s = m.get("status", "raw")
        if s in categories[c]:
            categories[c][s] += 1
    return sorted(categories.values(), key=lambda x: x["total"], reverse=True)[:30]


@router.get("/posts")
def statistics_posts():
    if not _use_supabase():
        return {"total": 0, "by_status": {}, "platforms": {"instagram": 0, "youtube": 0, "tiktok": 0}}
    sb = get_supabase()
    try:
        posts = sb.table("posts").select("status,ig_media_id,yt_video_id,tiktok_video_id").execute().data
    except Exception:
        try:
            posts = sb.table("posts").select("status").execute().data
        except Exception:
            posts = []

    by_status: dict[str, int] = {}
    ig = yt = tt = 0
    for p in posts:
        s = p.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
        if p.get("ig_media_id"):
            ig += 1
        if p.get("yt_video_id"):
            yt += 1
        if p.get("tiktok_video_id"):
            tt += 1

    return {
        "total": len(posts),
        "by_status": by_status,
        "platforms": {"instagram": ig, "youtube": yt, "tiktok": tt},
    }
