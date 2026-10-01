"""
Stock B-roll sourcing — search Pexels/Pixabay stock video APIs by a category
keyword, download matches, and index them as raw media EXACTLY like a manual
upload (source="stock" instead of "upload"). Once indexed as tagged raw VIDEO,
merge_clips.py already auto-blends any raw media matching category/tags filters
— no merge-side changes are needed here.

Feature default-OFF (opt-in via the `stock` settings group).

Usage:
    python -m backend.pipeline.stock_footage --category nature --tags drone,landscape
"""

import argparse
import logging
import re
import uuid
from pathlib import Path

import requests

from backend.config import ORGANIZED_DIR, PEXELS_API_KEY, PIXABAY_API_KEY, UPLOADS_DIR
from backend.db import get_setting
from backend.pipeline.index_content import _ffprobe_video, insert_upload_row

log = logging.getLogger(__name__)

# Mirror of settings.py DEFAULTS["stock"] — used when the settings row is missing
# keys (deep-merge safety) or the settings table is unreachable.
_DEFAULTS = {
    "enabled": False,
    "source": "pexels",         # "pexels" | "pixabay" | "both"
    "per_category_query": {},
    "max_clips_per_search": 5,
    "min_short_side": 720,
    "min_duration_s": 5.0,
}

_SOURCES = {"pexels", "pixabay", "both"}
_ALLOWED_EXT = {".mp4", ".mov", ".m4v", ".webm"}

# Built-in cinematic search phrase per category (see CLAUDE.md taxonomy.categories);
# overridden per-category by the stock.per_category_query setting when present.
DEFAULT_CATEGORY_QUERIES = {
    "hidden_gem": "hidden gem secret place",
    "budget": "budget backpacking",
    "culture": "culture heritage temple",
    "nature": "nature landscape drone",
    "food": "street food cinematic",
    "beach": "beach ocean drone",
}

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/videos/search"
# Get-video-by-id path is /videos/videos/:id (the resource segment IS "videos",
# nested under the videos API base) — the single-"videos" form 404s. Verified live.
PEXELS_SHOW_URL = "https://api.pexels.com/v1/videos/videos/{id}"
PIXABAY_URL = "https://pixabay.com/api/videos/"

_HTTP_TIMEOUT = 20
_DOWNLOAD_TIMEOUT = 60


def _settings() -> dict:
    stored = get_setting("stock") or {}
    if not isinstance(stored, dict):
        stored = {}
    cfg = {**_DEFAULTS, **stored}
    if cfg.get("source") not in _SOURCES:
        cfg["source"] = _DEFAULTS["source"]
    return cfg


def _resolve_query(category: str, tags: list[str] | None, query: str | None, cfg: dict) -> str:
    if query:
        return query
    per_category = cfg.get("per_category_query") or {}
    if category and isinstance(per_category, dict) and per_category.get(category):
        return per_category[category]
    if category and DEFAULT_CATEGORY_QUERIES.get(category):
        base = DEFAULT_CATEGORY_QUERIES[category]
        return f"{base} {' '.join(tags)}".strip() if tags else base
    if tags:
        return " ".join(tags)
    return f"{category} cinematic".strip()


def _sanitize_segment(value: str, fallback: str) -> str:
    """Same sanitize rules as backend/api/routes/downloads.py::_sanitize_segment
    — duplicated locally since pipeline modules must not import from routes."""
    cleaned = re.sub(r"[/\\]", "", (value or "")).replace("..", "").strip()
    cleaned = cleaned.strip(". ")
    return cleaned[:60] or fallback


def _dest_path(category: str, stem: str, ext: str) -> Path:
    """Build a safe, deduped destination under UPLOADS_DIR/<category>/<id>...
    — id-based leaf, not nested by geography (mirrors
    backend/api/routes/downloads.py::_dest_path)."""
    safe_category = _sanitize_segment(category, "uncategorized")
    safe_stem = _sanitize_segment(stem, "clip")
    dest_dir = UPLOADS_DIR / safe_category
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / f"{safe_stem}_{uuid.uuid4().hex[:6]}{ext}"


def _short_side(c: dict) -> int:
    return min(int(c.get("width") or 0), int(c.get("height") or 0))


# HD is plenty for 9:16 reels — download the ~720p rendition, never 4K/UHD, to save
# storage. Prefer the largest file whose height is <= 720; if a provider only exposes
# larger renditions, fall back to the SMALLEST of those so we still never grab 4K.
_TARGET_HEIGHT = 720


def _pick_pexels_file(files: list[dict]) -> dict | None:
    valid = [f for f in files if f.get("link")]
    if not valid:
        return None
    under = [f for f in valid if 0 < (f.get("height") or 0) <= _TARGET_HEIGHT]
    if under:
        return max(under, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
    return min(valid, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))


# Pixabay tiers are fixed sizes (large≈1080p, medium≈720p, small≈540p, tiny≈360p) and
# never 4K. Prefer the 720p "medium" tier for the HD-not-4K storage win; fall back up
# to large only when medium is missing.
_PIXABAY_TIER_ORDER = ("medium", "large", "small", "tiny")


def _pexels_candidates(query: str, count: int) -> list[dict]:
    if not PEXELS_API_KEY:
        return []
    try:
        resp = requests.get(
            PEXELS_SEARCH_URL,
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": max(1, min(count, 80))},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("stock_footage: pexels search failed for %r: %s", query, exc)
        return []

    out = []
    for v in data.get("videos", []):
        files = v.get("video_files") or []
        best = _pick_pexels_file(files)
        if not best:
            continue
        out.append({
            "id": str(v["id"]),
            "provider": "pexels",
            "thumbnail_url": v.get("image", ""),
            "preview_url": best.get("link", ""),
            "duration_s": float(v.get("duration") or 0),
            "width": best.get("width") or v.get("width") or 0,
            "height": best.get("height") or v.get("height") or 0,
        })
    return out


def _pixabay_candidates(query: str, count: int) -> list[dict]:
    if not PIXABAY_API_KEY:
        return []
    try:
        resp = requests.get(
            PIXABAY_URL,
            params={
                "key": PIXABAY_API_KEY,
                "q": query,
                # Pixabay rejects per_page<3 even when fewer results are wanted.
                "per_page": max(3, min(count, 200)),
            },
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("stock_footage: pixabay search failed for %r: %s", query, exc)
        return []

    out = []
    for hit in data.get("hits", []):
        videos = hit.get("videos") or {}
        tier = None
        for name in _PIXABAY_TIER_ORDER:
            if videos.get(name, {}).get("url"):
                tier = videos[name]
                break
        if not tier:
            continue
        out.append({
            "id": str(hit["id"]),
            "provider": "pixabay",
            "thumbnail_url": tier.get("thumbnail", ""),
            "preview_url": tier.get("url", ""),
            "duration_s": float(hit.get("duration") or 0),
            "width": tier.get("width") or 0,
            "height": tier.get("height") or 0,
        })
    return out


def _pexels_lookup(video_id: str) -> dict | None:
    if not PEXELS_API_KEY:
        return None
    try:
        resp = requests.get(
            PEXELS_SHOW_URL.format(id=video_id),
            headers={"Authorization": PEXELS_API_KEY},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        v = resp.json()
    except Exception as exc:
        log.warning("stock_footage: pexels lookup failed for id=%s: %s", video_id, exc)
        return None
    best = _pick_pexels_file(v.get("video_files") or [])
    if not best:
        return None
    return {
        "id": str(v["id"]),
        "provider": "pexels",
        "thumbnail_url": v.get("image", ""),
        "preview_url": best.get("link", ""),
        "duration_s": float(v.get("duration") or 0),
        "width": best.get("width") or v.get("width") or 0,
        "height": best.get("height") or v.get("height") or 0,
    }


def _pixabay_lookup(video_id: str) -> dict | None:
    if not PIXABAY_API_KEY:
        return None
    try:
        resp = requests.get(
            PIXABAY_URL,
            # Pixabay's search endpoint accepts a comma-separated `id` list to
            # fetch specific items directly — no separate "show" endpoint exists.
            params={"key": PIXABAY_API_KEY, "id": video_id, "per_page": 3},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
    except Exception as exc:
        log.warning("stock_footage: pixabay lookup failed for id=%s: %s", video_id, exc)
        return None
    if not hits:
        return None
    hit = hits[0]
    videos = hit.get("videos") or {}
    tier = None
    for name in _PIXABAY_TIER_ORDER:
        if videos.get(name, {}).get("url"):
            tier = videos[name]
            break
    if not tier:
        return None
    return {
        "id": str(hit["id"]),
        "provider": "pixabay",
        "thumbnail_url": tier.get("thumbnail", ""),
        "preview_url": tier.get("url", ""),
        "duration_s": float(hit.get("duration") or 0),
        "width": tier.get("width") or 0,
        "height": tier.get("height") or 0,
    }


def search_stock(
    category: str = "",
    tags: list[str] | None = None,
    query: str | None = None,
    count: int | None = None,
    source: str | None = None,
) -> list[dict]:
    """Search-only step (no download/index) — returns filtered candidate metadata
    for a preview grid: [{id, provider, thumbnail_url, preview_url, duration_s,
    width, height}]. Does NOT self-gate on stock.enabled — callers (the API
    routes) decide whether search is allowed at all."""
    cfg = _settings()
    provider = source if source in _SOURCES else cfg["source"]
    n = count or cfg["max_clips_per_search"]
    q = _resolve_query(category, tags, query, cfg)

    candidates: list[dict] = []
    if provider in ("pexels", "both"):
        candidates += _pexels_candidates(q, n)
    if provider in ("pixabay", "both"):
        candidates += _pixabay_candidates(q, n)

    min_short = int(cfg.get("min_short_side") or 0)
    min_dur = float(cfg.get("min_duration_s") or 0)
    return [c for c in candidates if _short_side(c) >= min_short and c["duration_s"] >= min_dur]


def _download_and_index(candidate: dict, category: str, tags: list[str] | None) -> dict:
    """Shared by run() and import_stock_clip(): download one candidate's
    preview_url, ffprobe-verify, index as a raw stock media row. Raises on any
    failure — callers count it as failed and move on."""
    preview_url = candidate.get("preview_url")
    if not preview_url:
        raise ValueError("candidate has no preview_url")

    ext = Path(preview_url.split("?")[0]).suffix.lower()
    if ext not in _ALLOWED_EXT:
        ext = ".mp4"
    stem = f"{candidate.get('provider', 'stock')}_{candidate.get('id', 'clip')}"
    dest = _dest_path(category, stem, ext)

    try:
        with requests.get(preview_url, stream=True, timeout=_DOWNLOAD_TIMEOUT) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)
        if _ffprobe_video(dest) is None:
            raise ValueError("downloaded file is not a valid video")
        rel = str(dest.relative_to(ORGANIZED_DIR))
        return insert_upload_row(rel, category, tags, source="stock")
    except Exception:
        dest.unlink(missing_ok=True)
        raise


def import_stock_clip(id: str, provider: str, category: str, tags: list[str] | None = None) -> dict:
    """Import exactly one previously-searched candidate by (id, provider). Looks
    the candidate back up (search results aren't cached across requests) then
    downloads + indexes it. Raises ValueError on lookup/download failure."""
    lookup = _pexels_lookup(id) if provider == "pexels" else _pixabay_lookup(id) if provider == "pixabay" else None
    if not lookup:
        raise ValueError(f"could not resolve {provider} video id={id}")
    return _download_and_index(lookup, category, tags)


def auto_fetch(category: str, tags: list[str] | None = None,
               pexels_n: int = 3, pixabay_n: int = 3) -> dict:
    """Download a few stock clips PER PROVIDER for a category with no stock yet, so
    a merge can blend them in. Uses the same category→query resolution as
    search_stock. Best-effort: a provider with no key or a failing call is skipped
    (never raises). Returns {"pexels": n_imported, "pixabay": n_imported}."""
    out = {"pexels": 0, "pixabay": 0}
    plans: list[tuple[str, int]] = []
    if PEXELS_API_KEY and pexels_n > 0:
        plans.append(("pexels", pexels_n))
    if PIXABAY_API_KEY and pixabay_n > 0:
        plans.append(("pixabay", pixabay_n))
    for provider, n in plans:
        try:
            candidates = search_stock(category=category, tags=tags,
                                      count=n, source=provider)
        except Exception as exc:
            log.warning("auto_fetch: %s search failed for %s: %s", provider, category, exc)
            continue
        for c in candidates[:n]:
            try:
                _download_and_index(c, category, tags)
                out[provider] += 1
            except Exception as exc:
                log.warning("auto_fetch: %s import failed for %s: %s", provider, category, exc)
    log.info("auto_fetch: %s → pexels=%d pixabay=%d", category, out["pexels"], out["pixabay"])
    return out


def run(
    category: str,
    tags: list[str] | None = None,
    query: str | None = None,
    count: int | None = None,
    source: str | None = None,
) -> dict:
    """Orchestrator/CLI stage entry. Self-gates on stock.enabled (same pattern as
    decaption.run) — the API routes gate /search and /import separately since
    those are immediate user-triggered actions, not the batch stage."""
    cfg = _settings()
    if not cfg.get("enabled"):
        return {"processed": 0, "failed": 0, "total": 0, "skipped": "disabled"}

    candidates = search_stock(category=category, tags=tags, query=query, count=count, source=source)
    processed = failed = 0
    for c in candidates:
        try:
            _download_and_index(c, category, tags)
            processed += 1
        except Exception as exc:
            log.warning("stock_footage: failed to import %s/%s: %s", c.get("provider"), c.get("id"), exc)
            failed += 1

    log.info("stock_footage: processed=%d failed=%d total=%d", processed, failed, len(candidates))
    return {"processed": processed, "failed": failed, "total": len(candidates)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Search + import stock B-roll for a category/tags")
    parser.add_argument("--category", required=True)
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--query", default=None)
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--source", default=None, choices=sorted(_SOURCES))
    args = parser.parse_args()
    cli_tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    result = run(category=args.category, tags=cli_tags,
                 query=args.query, count=args.count, source=args.source)
    print(f"Imported {result.get('processed', 0)}/{result.get('total', 0)}"
          + (f" — {result['skipped']}" if result.get("skipped") else ""))
