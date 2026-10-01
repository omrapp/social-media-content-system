import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query

from backend.db import get_supabase, _use_supabase, get_all_media
from backend.api.auth import verify_token

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"], dependencies=[Depends(verify_token)])


def _safe_supabase_query(fn):
    """Execute a Supabase query, return None on connection errors."""
    try:
        return fn()
    except Exception as exc:
        log.warning("analytics: Supabase query failed (%s), returning empty", exc)
        return None


@router.get("/overview")
def overview():
    if not _use_supabase():
        media = get_all_media()
        return {
            "total_media": len(media),
            "by_status": _count_by(media, "status"),
            "by_category": _count_by(media, "category"),
        }
    sb = get_supabase()
    analytics = _safe_supabase_query(
        lambda: sb.table("analytics").select("*").order("fetched_at", desc=True).limit(100).execute().data
    ) or []
    media = get_all_media()
    return {
        "total_media": len(media),
        "by_status": _count_by(media, "status"),
        "by_category": _count_by(media, "category"),
        "recent_analytics": analytics[:10],
    }


@router.get("/timeseries")
def timeseries(days: int = Query(default=30, le=90)):
    if not _use_supabase():
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sb = get_supabase()
    return _safe_supabase_query(
        lambda: sb.table("analytics")
        .select("reach,impressions,likes,comments,saves,shares,plays,engagement_rate,platform,fetched_at")
        .gte("fetched_at", since)
        .order("fetched_at", desc=False)
        .execute()
        .data
    ) or []


@router.get("/hashtags")
def hashtag_ab():
    """Hashtag A/B test results: per-variant avg reach + engagement (Enh D)."""
    from backend.pipeline.feedback_aggregator import hashtag_variant_report
    return hashtag_variant_report()


@router.get("/categories/performance")
def category_perf():
    """Realized engagement per category, normalized 0-1 (Enh I). This is the
    'what-works' signal that biases auto-create clip selection toward proven
    categories. Empty until enough analytics rows exist (cold start)."""
    from backend.pipeline.feedback_aggregator import category_performance
    return category_performance()


@router.get("/categories")
def by_category():
    media = get_all_media()
    categories = {}
    for item in media:
        c = item.get("category", "unknown")
        if c not in categories:
            categories[c] = {"count": 0, "statuses": {}}
        categories[c]["count"] += 1
        s = item.get("status", "unknown")
        categories[c]["statuses"][s] = categories[c]["statuses"].get(s, 0) + 1
    return categories


def _count_by(items: list[dict], key: str) -> dict:
    counts = {}
    for item in items:
        v = item.get(key, "unknown")
        counts[v] = counts.get(v, 0) + 1
    return counts
