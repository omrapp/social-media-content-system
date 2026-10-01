"""
Taxonomy endpoints — feed inline keyboards for the Telegram /create flow.
"""

from fastapi import APIRouter, Depends
from backend.api.auth import verify_token
from backend.db import get_distinct, get_setting

router = APIRouter(prefix="/api/taxonomy", tags=["taxonomy"], dependencies=[Depends(verify_token)])

_DEFAULT_CATEGORIES = ["hidden_gem", "budget", "culture", "nature", "food", "beach"]


def _configured_categories() -> list[str]:
    """Configured category taxonomy, falling back to the legacy settings key,
    falling back to the built-in placeholder list. Mirrors
    backend/pipeline/classify_groq.py::_category_options."""
    cats = (get_setting("taxonomy") or {}).get("categories")
    if cats:
        return list(cats)
    cats = (get_setting("pillars") or {}).get("taxonomy")
    if cats:
        return list(cats)
    return _DEFAULT_CATEGORIES


def _distinct_tags() -> list[str]:
    """Distinct observed values of the media.tags TEXT[]/JSON-list column,
    flattened. No generic get_distinct-equivalent exists for array columns
    (get_distinct is scalar-column only), so this queries + flattens directly."""
    from backend.db import _use_supabase, get_supabase, db_retry, query as sqlite_query

    values: set = set()
    if _use_supabase():
        start, page = 0, 1000
        while True:
            def _fetch_page(s=start):
                return (
                    get_supabase()
                    .table("media")
                    .select("tags")
                    .not_.is_("tags", "null")
                    .range(s, s + page - 1)
                    .execute()
                    .data
                )
            rows = db_retry(_fetch_page)
            for r in rows:
                for t in (r.get("tags") or []):
                    if t:
                        values.add(t)
            if len(rows) < page:
                break
            start += page
    else:
        import json as _json
        for r in sqlite_query("SELECT tags FROM media WHERE tags IS NOT NULL"):
            raw = r.get("tags") if isinstance(r, dict) else r["tags"]
            try:
                tags = raw if isinstance(raw, list) else _json.loads(raw or "[]")
            except (ValueError, TypeError):
                tags = []
            for t in tags:
                if t:
                    values.add(t)
    return sorted(values)


@router.get("/tags")
def tags():
    return {"tags": _distinct_tags()}


@router.get("/categories")
def categories():
    db_categories = get_distinct("category")
    merged = sorted(set(_configured_categories()) | set(db_categories))
    return {"categories": merged}
