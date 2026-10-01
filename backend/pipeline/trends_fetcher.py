"""
Trending-topic injection (Enhancement B).

Pulls rising search queries from Google Trends (via the free, unofficial
`pytrends` library) once per day and exposes them as a short prompt fragment
that caption_gen weaves into generation, so captions ride current interest
instead of staying static at generation time.

Deliberately best-effort: pytrends is unofficial and can break when Google
changes its endpoints, so every failure degrades to an empty result and the
caption prompt is simply unchanged. Results are cached for the day to avoid
hammering the endpoint (and getting rate-limited) on every caption.
"""

import logging
from datetime import date

log = logging.getLogger(__name__)

_SEED = "travel"
_cache: dict = {}


def fetch_trends(limit: int = 8) -> list[str]:
    """Rising search queries this week (global, ungeo-targeted). Cached per
    calendar day. Empty list if pytrends is missing or the request fails.

    Args:
        limit: Maximum number of trend strings to return.
    """
    today = date.today().isoformat()

    if today in _cache:
        return _cache[today][:limit]

    trends: list[str] = []
    try:
        from pytrends.request import TrendReq

        pt = TrendReq(hl="en-US", tz=0)
        pt.build_payload([_SEED], timeframe="now 7-d")
        related = pt.related_queries() or {}
        rising = (related.get(_SEED) or {}).get("rising")
        if rising is not None and not rising.empty:
            trends = [str(q) for q in rising["query"].tolist()]
    except Exception as exc:
        log.warning("trends_fetcher: fetch failed (%s) — captions run without trends", exc)
        trends = []

    _cache[today] = trends
    return trends[:limit]


def trends_block() -> str:
    """Prompt fragment listing current trends, or "" when none."""
    trends = fetch_trends()
    if not trends:
        return ""
    return (
        "\n\nTrending searches this week (weave in ONLY if naturally relevant "
        "to this clip — never force it): " + ", ".join(trends)
    )
