"""
Content-aware LUT (colour grade) selection.

Picks the best-fitting .cube for a clip instead of the flat category→LUT map. The
curated cinematic LUTs live in assets/luts/cinematic/ and are described by
assets/luts/catalog.json (mood + category tags). select_lut() runs a layered
cascade, gated by the "color" settings group, and ALWAYS degrades to the legacy
CATEGORY_LUT map (or None) — it never grades worse than before and never raises
into the edit stage.

Cascade (first hit wins), per color.lut_mode:
    override   — a manual pick (Preview edit drawer) trumps everything.
    fixed      — always use color.fixed_lut.
    vision     — AI vision picks a category → catalog match (only when enabled).
    mood       — mood_from_text(caption) → catalog tag match.
    category   — catalog categories[] match → legacy CATEGORY_LUT fallback.

This module deliberately keeps CATEGORY_LUT in video_edit.py (its long-standing
home) and imports it lazily to avoid an import cycle (video_edit imports
select_lut at module load).
"""
import json
import logging
from pathlib import Path

from backend.config import LUT_CATALOG_PATH, LUTS_DIR
from backend.db import get_setting
from backend.pipeline.music_mood import mood_from_text

log = logging.getLogger(__name__)

_CATALOG_CACHE: list[dict] | None = None


def _reset_cache() -> None:
    """Test hook — drop the in-process catalog cache."""
    global _CATALOG_CACHE
    _CATALOG_CACHE = None


def load_catalog() -> list[dict]:
    """Read + cache catalog.json. Returns the list of LUT entries whose .cube
    file actually exists on disk (a catalog/disk drift just hides the entry — the
    selector then falls through to the next cascade tier). [] when absent/invalid."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    entries: list[dict] = []
    try:
        if LUT_CATALOG_PATH.exists():
            data = json.loads(LUT_CATALOG_PATH.read_text())
            for e in data.get("luts", []):
                f = e.get("file")
                if f and (LUTS_DIR / f).exists():
                    entries.append(e)
    except Exception as exc:
        log.warning("lut_select: failed to load catalog (%s) — running category-only", exc)
        entries = []
    _CATALOG_CACHE = entries
    return entries


def _safe_lut(name: str | None) -> str | None:
    """Validate a settings/catalog-sourced LUT path resolves UNDER LUTS_DIR and
    the file exists. Guards against path traversal in fixed_lut / a manual pick."""
    if not name:
        return None
    try:
        candidate = (LUTS_DIR / name).resolve()
        root = LUTS_DIR.resolve()
        if not candidate.is_relative_to(root):
            log.warning("lut_select: rejected out-of-root LUT path %r", name)
            return None
        return name if candidate.exists() else None
    except Exception:
        return None


def _catalog_by_mood(catalog: list[dict], mood: str | None) -> str | None:
    if not mood:
        return None
    for e in catalog:
        if mood in (e.get("tags") or []):
            return e.get("file")
    return None


def _catalog_by_category(catalog: list[dict], category: str | None) -> str | None:
    if not category:
        return None
    for e in catalog:
        if category in (e.get("categories") or []):
            return e.get("file")
    return None


def _category_fallback(category: str | None) -> str | None:
    """The legacy flat map — the floor the cascade can never sink below."""
    try:
        from backend.pipeline.video_edit import CATEGORY_LUT
        return CATEGORY_LUT.get(category)
    except Exception:
        return None


def _vision_lut(item: dict, catalog: list[dict]) -> str | None:
    """Map the clip's visual category to a catalog LUT. Prefers a cached vision
    category (from a prior classify_vision run, stored on media.metadata.vision) to
    avoid a second Groq call; only invokes the classifier when none is cached.
    Fully guarded — any failure returns None so the cascade continues."""
    try:
        category = ((item.get("metadata") or {}).get("vision") or {}).get("category")
        if not category:
            reel_path = item.get("reel_ready_path")
            if not reel_path or not Path(reel_path).exists():
                return None
            from backend.pipeline.classify_vision import _extract_keyframes, classify_frames
            frames = _extract_keyframes(reel_path)
            if not frames:
                return None
            category = classify_frames(frames, provider="auto").get("category")
        return _catalog_by_category(catalog, category)
    except Exception as exc:
        log.warning("lut_select: vision LUT pick failed (%s) — falling through", exc)
        return None


def _mood_for(item: dict) -> str | None:
    """Derive a mood from the text the raw clip already has (mirrors
    _music_decision in video_edit.py)."""
    tags = item.get("tags")
    tags_text = " ".join(tags) if isinstance(tags, list) else (tags or "")
    return mood_from_text(item.get("original_caption"), tags_text)


def _track_lut_usage(lut_path: str) -> None:
    """Best-effort usage_count bump on the matching `assets` row (type=lut),
    matched by filename — one list_assets call per select_lut() invocation
    (once per reel, never per-frame). Never raises; purely analytics, must
    never affect which LUT was already chosen and returned."""
    try:
        from backend.db import list_assets, increment_asset_usage
        filename = Path(lut_path).name
        row = next((r for r in list_assets("lut") if r.get("filename") == filename), None)
        if row and row.get("id"):
            increment_asset_usage(row["id"])
    except Exception as exc:
        log.debug("lut_select: usage tracking skipped (non-fatal): %s", exc)


def select_lut(item: dict, settings: dict | None = None,
               override: str | None = None) -> str | None:
    """Return a LUTS_DIR-relative .cube path (e.g. "cinematic/teal_orange.cube"
    or legacy "warm.cube"), or None to skip the grade. Never raises."""
    picked = _select_lut(item, settings, override)
    if picked:
        _track_lut_usage(picked)
    return picked


def _select_lut(item: dict, settings: dict | None = None,
                override: str | None = None) -> str | None:
    try:
        cfg = settings if settings is not None else (get_setting("color") or {})

        # 1. Manual pick (Preview edit drawer) trumps automatic selection.
        if override:
            picked = _safe_lut(override)
            if picked:
                return picked

        mode = cfg.get("lut_mode", "category")
        category = item.get("category")

        # 2. Fixed: always one LUT (fall through to category floor if it's gone).
        if mode == "fixed":
            return _safe_lut(cfg.get("fixed_lut")) or _category_fallback(category)

        catalog = load_catalog()

        # 3. Vision override — only when explicitly enabled (adds an AI call).
        if cfg.get("use_vision") or mode == "vision":
            v = _vision_lut(item, catalog)
            if v:
                return v

        # 4. Caption-mood match. Only in mood/vision modes — category mode stays
        #    deterministic (category → legacy) so the default never surprises.
        if mode in ("mood", "vision"):
            m = _catalog_by_mood(catalog, _mood_for(item))
            if m:
                return m

        # 5. Category: catalog tag match → legacy flat map floor.
        return _catalog_by_category(catalog, category) or _category_fallback(category)
    except Exception as exc:
        log.warning("lut_select: select_lut failed (%s) — using category fallback", exc)
        return _category_fallback(item.get("category"))
