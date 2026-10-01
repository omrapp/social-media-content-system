from fastapi import APIRouter, Depends

from backend.db import get_all_media
from backend.api.auth import verify_token

router = APIRouter(prefix="/api/classification", tags=["classification"], dependencies=[Depends(verify_token)])


def _is_classified(m: dict) -> bool:
    """Groq writes category+tags together and only runs on category IS NULL,
    so a non-empty category is the reliable 'Groq done' marker."""
    return bool(m.get("category"))


def _is_vision_scored(m: dict) -> bool:
    return m.get("hook_score") is not None


def _is_video(m: dict) -> bool:
    return (m.get("media_type") or "").upper() == "VIDEO"


def _pct(done: int, total: int) -> float:
    return round(done / total * 100, 1) if total else 0.0


@router.get("/overview")
def overview():
    media = get_all_media()
    total = len(media)
    videos = [m for m in media if _is_video(m)]
    video_total = len(videos)

    groq_done = sum(1 for m in media if _is_classified(m))
    # Vision only runs on videos — measure remaining against the video subset.
    vision_done = sum(1 for m in videos if _is_vision_scored(m))

    by_category: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for m in media:
        p = m.get("category") or "unclassified"
        by_category[p] = by_category.get(p, 0) + 1
        s = m.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "total_media": total,
        "video_media": video_total,
        "groq": {
            "classified": groq_done,
            "remaining": total - groq_done,
            "pct": _pct(groq_done, total),
        },
        "vision": {
            "scored": vision_done,
            "remaining": video_total - vision_done,
            "pct": _pct(vision_done, video_total),
        },
        "by_category": by_category,
        "by_status": by_status,
    }


@router.get("/breakdown")
def breakdown():
    """Per-category counts with Groq + vision progress per node."""
    media = get_all_media()
    categories: dict[str, dict] = {}

    for m in media:
        category = m.get("category") or "unclassified"
        classified = _is_classified(m)
        scored = _is_vision_scored(m)

        c = categories.setdefault(
            category,
            {"category": category, "total": 0, "groq_classified": 0, "vision_scored": 0},
        )
        c["total"] += 1
        c["groq_classified"] += classified
        c["vision_scored"] += scored

    return sorted(categories.values(), key=lambda x: x["total"], reverse=True)
