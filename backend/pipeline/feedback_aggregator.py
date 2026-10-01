"""
Engagement feedback loop (Enhancement A).

Closes the gap where the `analytics` table is populated daily by pg_cron but
never feeds back into caption generation. Aggregates the best-performing posts
by engagement, traces each back to its category + opening hook, and exposes a
compact prompt fragment that caption_gen injects into the generator so new
captions imitate what actually performs.

Supabase-only (analytics + posts live there). On the SQLite fallback every
function degrades to an empty result, so callers stay safe to call
unconditionally.
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backend.db import _use_supabase, get_supabase

log = logging.getLogger(__name__)

# How many analytics rows to scan, and how many distinct hooks to surface.
_SCAN_LIMIT = 200
_DEFAULT_TOP = 3
# Wider scan for time/variant stats — these aggregate, so more rows = better signal.
_STATS_LIMIT = 500


def _latest_analytics_by_post(limit: int) -> dict[str, dict]:
    """Most-recent analytics row per post_id (deduped), newest first."""
    sb = get_supabase()
    rows = (
        sb.table("analytics")
        .select("post_id,engagement_rate,saves,shares,reach,fetched_at")
        .order("fetched_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    best: dict[str, dict] = {}
    for r in rows:
        pid = r.get("post_id")
        if pid and pid not in best:
            best[pid] = r
    return best


def _parse_dt(raw) -> datetime | None:
    """Parse a TIMESTAMPTZ value (str or datetime) into an aware UTC datetime."""
    if not raw:
        return None
    try:
        if isinstance(raw, str):
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
        else:
            dt = raw
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _score(row: dict) -> float:
    """Rank value for a post. Prefer engagement_rate; fall back to saves+shares
    (the strongest growth signals) so rows missing a computed rate still rank."""
    rate = row.get("engagement_rate")
    if rate:
        return float(rate)
    saves = row.get("saves") or 0
    shares = row.get("shares") or 0
    return float(saves * 2 + shares)


def _hook(caption: str | None) -> str:
    """First non-empty line of a caption, trimmed — the part that stops the scroll."""
    for line in (caption or "").splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return ""


def top_performers(category: str | None = None, limit: int = _DEFAULT_TOP) -> list[dict]:
    """Return the best-performing posts as [{hook, category, score}], ranked.

    Joins analytics → posts → media in three batched queries (no N+1). Filters
    to `category` when given, otherwise returns the global best. Empty list on
    SQLite or any query error."""
    if not _use_supabase():
        return []
    try:
        sb = get_supabase()
        rows = (
            sb.table("analytics")
            .select("post_id,engagement_rate,saves,shares,likes")
            .order("fetched_at", desc=True)
            .limit(_SCAN_LIMIT)
            .execute()
            .data
            or []
        )
        # Keep the most recent analytics row per post, then rank.
        best_by_post: dict[str, dict] = {}
        for r in rows:
            pid = r.get("post_id")
            if pid and pid not in best_by_post:
                best_by_post[pid] = r
        if not best_by_post:
            return []

        post_ids = list(best_by_post.keys())
        posts = (
            sb.table("posts").select("id,media_id").in_("id", post_ids).execute().data
            or []
        )
        media_by_post = {p["id"]: p.get("media_id") for p in posts if p.get("media_id")}
        media_ids = list({mid for mid in media_by_post.values()})
        if not media_ids:
            return []

        media = (
            sb.table("media")
            .select("id,category,caption_ig")
            .in_("id", media_ids)
            .execute()
            .data
            or []
        )
        media_by_id = {m["id"]: m for m in media}

        ranked: list[dict] = []
        for pid, arow in best_by_post.items():
            mid = media_by_post.get(pid)
            m = media_by_id.get(mid) if mid else None
            if not m:
                continue
            hook = _hook(m.get("caption_ig"))
            if not hook:
                continue
            ranked.append({"hook": hook, "category": m.get("category"), "score": _score(arow)})

        if category:
            ranked = [r for r in ranked if r["category"] == category]
        ranked.sort(key=lambda r: r["score"], reverse=True)

        # De-duplicate identical hooks, keep order.
        seen: set[str] = set()
        unique = []
        for r in ranked:
            if r["hook"] in seen:
                continue
            seen.add(r["hook"])
            unique.append(r)
        return unique[:limit]
    except Exception as exc:  # never break caption generation on analytics issues
        log.warning("feedback_aggregator: top_performers failed (%s)", exc)
        return []


def performance_hints_block(category: str | None = None, limit: int = _DEFAULT_TOP) -> str:
    """Prompt fragment listing winning hooks for the generator to imitate.

    Returns "" when there is no engagement data yet (cold start), so the caption
    prompt is unchanged until real performance signal exists."""
    top = top_performers(category, limit)
    if not top:
        return ""
    lines = [
        "",
        "Proven hooks (these scored highest on saves/engagement for this account — "
        "match their energy and structure, do NOT copy them verbatim):",
    ]
    for r in top:
        tag = f" [{r['category']}]" if r.get("category") and not category else ""
        lines.append(f"  - {r['hook']}{tag}")
    return "\n".join(lines)


# ── Optimal-time scheduling (Enhancement C) ───────────────────────────


def slot_engagement_scores(tz_name: str) -> dict[int, float]:
    """Average engagement score per local hour-of-day, from past posts.

    Joins analytics → posts, buckets each post by the local hour it was
    scheduled/published in, and averages the engagement score per hour. Empty
    dict on SQLite, no data, or any error — callers then keep chronological
    slot order (graceful cold start)."""
    if not _use_supabase():
        return {}
    try:
        best_by_post = _latest_analytics_by_post(_STATS_LIMIT)
        if not best_by_post:
            return {}
        post_ids = list(best_by_post.keys())
        sb = get_supabase()
        posts = (
            sb.table("posts")
            .select("id,slot_at,published_at,scheduled_at")
            .in_("id", post_ids)
            .execute()
            .data
            or []
        )
        tz = ZoneInfo(tz_name.strip())
        buckets: dict[int, list[float]] = defaultdict(list)
        for p in posts:
            when = _parse_dt(p.get("slot_at") or p.get("published_at") or p.get("scheduled_at"))
            if not when:
                continue
            hour = when.astimezone(tz).hour
            buckets[hour].append(_score(best_by_post[p["id"]]))
        return {h: sum(v) / len(v) for h, v in buckets.items() if v}
    except Exception as exc:
        log.warning("feedback_aggregator: slot_engagement_scores failed (%s)", exc)
        return {}


# ── Per-category realized performance (Enhancement I) ───────────────────


def category_performance(normalize: bool = True) -> dict[str, float]:
    """Average realized engagement score per category, from past posts.

    Joins analytics → posts → media(category) and averages the engagement score
    per category. With ``normalize`` (default) the top category maps to 1.0 and
    the rest scale proportionally — so the result blends cleanly with the 0-1
    ``hook_score`` during clip selection. Empty dict on SQLite, no data, or any
    error, so callers keep their pre-feedback behaviour (graceful cold start).
    """
    if not _use_supabase():
        return {}
    try:
        best_by_post = _latest_analytics_by_post(_STATS_LIMIT)
        if not best_by_post:
            return {}
        post_ids = list(best_by_post.keys())
        sb = get_supabase()
        posts = (
            sb.table("posts").select("id,media_id").in_("id", post_ids).execute().data
            or []
        )
        media_by_post = {p["id"]: p.get("media_id") for p in posts if p.get("media_id")}
        media_ids = list({mid for mid in media_by_post.values()})
        if not media_ids:
            return {}
        media = (
            sb.table("media").select("id,category").in_("id", media_ids).execute().data
            or []
        )
        category_by_media = {m["id"]: m.get("category") for m in media if m.get("category")}

        buckets: dict[str, list[float]] = defaultdict(list)
        for pid, mid in media_by_post.items():
            category = category_by_media.get(mid)
            if not category:
                continue
            buckets[category].append(_score(best_by_post[pid]))
        avg = {p: sum(v) / len(v) for p, v in buckets.items() if v}
        if not avg or not normalize:
            return avg
        top = max(avg.values())
        if top <= 0:
            return {}
        return {p: round(v / top, 4) for p, v in avg.items()}
    except Exception as exc:
        log.warning("feedback_aggregator: category_performance failed (%s)", exc)
        return {}


# ── Hashtag A/B reporting (Enhancement D) ─────────────────────────────


def hashtag_variant_report() -> dict:
    """Per-variant average reach + engagement, for deciding the A/B winner.

    Returns {variant: {posts, avg_reach, avg_score}}. Empty on SQLite/no data."""
    if not _use_supabase():
        return {}
    try:
        best_by_post = _latest_analytics_by_post(_STATS_LIMIT)
        if not best_by_post:
            return {}
        post_ids = list(best_by_post.keys())
        sb = get_supabase()
        posts = (
            sb.table("posts")
            .select("id,hashtag_variant")
            .in_("id", post_ids)
            .execute()
            .data
            or []
        )
        agg: dict[str, dict] = defaultdict(lambda: {"reach": 0.0, "score": 0.0, "posts": 0})
        for p in posts:
            variant = p.get("hashtag_variant")
            if not variant:
                continue
            arow = best_by_post[p["id"]]
            bucket = agg[variant]
            bucket["reach"] += float(arow.get("reach") or 0)
            bucket["score"] += _score(arow)
            bucket["posts"] += 1
        return {
            v: {
                "posts": b["posts"],
                "avg_reach": round(b["reach"] / b["posts"], 1),
                "avg_score": round(b["score"] / b["posts"], 4),
            }
            for v, b in agg.items()
            if b["posts"]
        }
    except Exception as exc:
        log.warning("feedback_aggregator: hashtag_variant_report failed (%s)", exc)
        return {}
