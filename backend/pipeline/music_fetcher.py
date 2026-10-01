"""
Background-music fetcher. Three-tier source (local-first):
  1. Local packs — Pixabay/Chosic tracks (highest priority) then Jamendo tracks,
                   score-ranked by mood + duration + popularity + source bonus
                   + admin favourite/usage signals. Files live anywhere under
                   assets/music/packs/** (category-named folders, _shared/,
                   _uploads/, or any other pool like travel/) and are
                   catalogued in assets/music/cache.json as a flat, id-keyed
                   manifest — physical location no longer has to match a
                   category name (fixed 1.9.0; see `categories` field below).
  2. Jamendo API  — only called when no local file is found for the category.
                    Downloads saved into the category's local pack so they
                    accumulate and reduce future API calls.
  3. _shared/     — any category, last resort if category pack is empty.

Register a free Jamendo app at https://devportal.jamendo.com/ for
JAMENDO_CLIENT_ID. With no key the fetcher serves local packs only.

cache.json schema (flat, 1.9.0+):
    {
      "tracks": {
        "<track_id>": {
          "filename": "...", "title": "...", "source": "...", "duration": 123.4,
          "popularity": null, "license": "...", "mood": "...",
          "categories": ["nature", "beach"],   # [] = matches any category query
          "favourite": false, "usage_count": 0, "last_used_at": null
        }
      },
      "_recent_picks": [...]
    }
Legacy `{category: [track,...]}` bucket caches are migrated in-memory + persisted
transparently the first time `_load_cache()` runs — no manual migration step.

Usage:
    python -m backend.pipeline.music_fetcher --category hidden_gem
    python -m backend.pipeline.music_fetcher --category nature --tags beach,sunset
"""

import argparse
import hashlib
import json
import logging
import math
import random
import subprocess
import uuid
import requests
from pathlib import Path

from backend.config import JAMENDO_CLIENT_ID, MUSIC_DIR
from backend.db import get_setting
from backend.pipeline.music_mood import MOOD_TAGS

log = logging.getLogger(__name__)

JAMENDO_API = "https://api.jamendo.com/v3.0/tracks/"

# category → Jamendo fuzzytags (mood/genre keywords). Covers all 6 categories;
# unknown categories fall back to hidden_gem.
CATEGORY_TAGS = {
    "hidden_gem": "ambient chill",
    "budget":     "acoustic upbeat",
    "culture":    "cinematic epic",
    "nature":     "ambient cinematic",
    "food":       "jazz lounge",
    "beach":      "tropical chill",
}

CACHE_FILE = MUSIC_DIR / "cache.json"

# Cross-call cooldown: filenames of the last N picked tracks, stored in cache.json
# under this key so consecutive reels never share the same bed (fixes the
# "last 4 videos got the same track" repeat). Not a category — won't collide.
# Overridable at runtime via music.cooldown_recent_cap (falls back to this
# constant when the setting is absent).
RECENT_KEY = "_recent_picks"
RECENT_CAP = 10

# Local royalty-free fallback pack. Drop .mp3 files into
# assets/music/packs/<category>/ (category-specific) or assets/music/packs/_shared/
# (any category). Used when Jamendo returns nothing — no key, offline, or no hits.
PACKS_DIR = MUSIC_DIR / "packs"
UPLOADS_DIR = PACKS_DIR / "_uploads"

AUDIO_FILE_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".ogg")


# ── In-process rglob resolution cache ────────────────────────────────────────
# Filename/stem → resolved Path. Built lazily on first lookup, invalidated by
# discover_new_files() (new/deleted/moved files) and trim_track() (new file).
# Avoids re-walking the filesystem per scored candidate during one merge render.
_RESOLVE_CACHE: dict[str, Path] = {}
_RESOLVE_CACHE_BUILT = False


def _build_resolve_cache() -> None:
    global _RESOLVE_CACHE, _RESOLVE_CACHE_BUILT
    cache: dict[str, Path] = {}
    if PACKS_DIR.exists():
        for f in PACKS_DIR.rglob("*"):
            if f.is_file() and f.suffix.lower() in AUDIO_FILE_EXTS:
                cache.setdefault(f.name, f)
                cache.setdefault(f.stem, f)
    _RESOLVE_CACHE = cache
    _RESOLVE_CACHE_BUILT = True


def _resolve_by_name(needle: str | None) -> Path | None:
    """Resolve a bare filename or track id to its physical path, regardless of
    which folder under PACKS_DIR it actually lives in (the core path-bug fix)."""
    if not needle:
        return None
    global _RESOLVE_CACHE_BUILT
    if not _RESOLVE_CACHE_BUILT:
        _build_resolve_cache()
    return _RESOLVE_CACHE.get(needle) or _RESOLVE_CACHE.get(Path(needle).stem)


def _invalidate_resolve_cache() -> None:
    global _RESOLVE_CACHE_BUILT
    _RESOLVE_CACHE_BUILT = False


def _score_track(entry: dict, category: str, clip_len: float | None,
                 mood: str | None = None,
                 avoid_names: set[str] | None = None,
                 music_cfg: dict | None = None) -> float:
    """Score a cached manifest entry for category + clip fit.

    Higher = better match.  Jitter ensures variety on repeated calls even
    when all scores are equal (e.g. old-format entries with no metadata).

    Scoring components:
      +2.0  mood keywords overlap with category's CATEGORY_TAGS string
      +2.0  caption-mood match (Enh G) — track mood/title matches the clip's mood
      +1.5  track duration covers full clip length (proportional if shorter)
      +1.0  popularity (capped; Jamendo scale ~10 000 per unit)
      +favourite_boost  admin-flagged favourite (default 3.0)
      +usage_weight * log1p(usage_count)  proven-track lift (default weight 0.3)
      +0–0.5 random jitter for variety
    """
    score = 0.0
    if music_cfg is None:
        music_cfg = get_setting("music") or {}

    # Source priority: Pixabay (pxb_audio) > Chosic > Jamendo trending. Local
    # packs win over the API; within local packs pxb_audio ranks highest.
    source = (entry.get("source") or "").lower()
    if source in ("pixabay", "pxb_audio", "pxb"):
        score += 2.0
    elif source == "chosic":
        score += 1.5
    elif source == "jamendo":
        score += 0.5

    # Mood match — entry["mood"] is stored by scraper; old entries lack it (0 pts).
    entry_mood = (entry.get("mood") or "").lower()
    expected = CATEGORY_TAGS.get(category, CATEGORY_TAGS["hidden_gem"])
    if entry_mood and any(w in expected for w in entry_mood.split()):
        score += 2.0

    # Caption-mood match (Enh G): reward tracks whose mood/title words overlap
    # the clip's detected mood keywords. Looks at both the scraped mood tag and
    # the track title so it works on entries lacking explicit mood metadata.
    if mood:
        mood_words = MOOD_TAGS.get(mood, "").split()
        haystack = f"{entry_mood} {(entry.get('title') or '').lower()}"
        if any(w in haystack for w in mood_words):
            score += 2.0

    # Duration preference — prefer tracks that cover the full clip.
    if clip_len and clip_len > 0:
        dur = entry.get("duration") or 0
        if dur >= clip_len:
            score += 1.5
        elif dur > 0:
            score += 1.5 * (dur / clip_len)

    # Popularity contribution — cap at 1.0 to avoid dominating other signals.
    pop = entry.get("popularity") or 0
    if pop > 0:
        score += min(pop / 10_000.0, 1.0)

    # Admin-manageable signals: favourite boost + usage-proven lift.
    if entry.get("favourite"):
        score += float(music_cfg.get("favourite_boost", 3.0))
    usage = entry.get("usage_count") or 0
    if usage:
        score += float(music_cfg.get("usage_weight", 0.3)) * math.log1p(usage)

    # Recently-used cooldown: a track picked in the last RECENT_CAP reels is
    # pushed far down so it isn't reused back-to-back. Still selectable as a last
    # resort (negative offset, not a hard skip) when the pool is exhausted.
    if avoid_names and (entry.get("filename") or "") in avoid_names:
        score -= 10.0

    # Jitter: keeps picks varied across calls with similar scores. Raised from
    # 0.5 so it can break ties between equally-good tracks (deterministic mood +
    # source bonuses total ~5.5, which 0.5 jitter could never overcome — that's
    # why the same top track won every same-category reel).
    score += random.random() * 1.5

    return score


def _overlay_asset_fields(tracks: dict) -> dict:
    """Shallow-merge favourite/usage_count/categories/mood/last_used_at from the
    `assets` table (source of truth as of 1.11.0) onto a COPY of the raw
    cache.json tracks dict, matched by filename. `cache.json` itself is never
    mutated by this — it stays the physical bookkeeping store (filename/
    source/duration/license) plus a stale-but-present fallback copy of these 5
    fields for offline/no-Supabase use.

    Best-effort: on any failure, or when Supabase isn't configured / has no
    music rows yet, returns *tracks* unchanged so callers (list_all_tracks's
    display and _select_track's scoring) always have a value to work with —
    this is the one shared code path both use, so there's no second,
    diverging overlay implementation.
    """
    try:
        from backend.db import list_assets
        rows = list_assets("music")
    except Exception as exc:
        log.debug("music_fetcher: asset overlay skipped (non-fatal): %s", exc)
        return tracks
    if not rows:
        return tracks
    by_filename = {r["filename"]: r for r in rows if r.get("filename")}
    if not by_filename:
        return tracks

    out: dict = {}
    for tid, entry in tracks.items():
        merged = dict(entry)
        row = by_filename.get(entry.get("filename"))
        if row:
            merged["favourite"] = bool(row.get("favourite", entry.get("favourite", False)))
            merged["usage_count"] = int(row.get("usage_count") or entry.get("usage_count") or 0)
            merged["last_used_at"] = row.get("last_used_at") or entry.get("last_used_at")
            # The old dedicated `pillars` column on `assets` was merged into
            # `tags` by the generic-taxonomy migration — that's now the source
            # of truth for which categories/tags a track is eligible for.
            merged["categories"] = row.get("tags") or entry.get("categories") or []
            merged["mood"] = row.get("mood") or entry.get("mood")
        out[tid] = merged
    return out


def _get_recent(cache: dict) -> list[str]:
    """Filenames of the last N tracks picked across all categories (N from
    music.cooldown_recent_cap, falling back to RECENT_CAP)."""
    cap = int((get_setting("music") or {}).get("cooldown_recent_cap", RECENT_CAP))
    return list(cache.get(RECENT_KEY, []))[:cap]


def _record_recent(filename: str) -> None:
    """Push *filename* to the front of the recently-picked list (deduped,
    capped) — this stays local (cooldown mechanics, not admin-facing data).

    Usage-count bump (1.11.0): the `assets` row is now the source of truth
    for usage_count/last_used_at, so cache.json's copies of those two fields
    are no longer written here (vestigial going forward). The bump itself is
    best-effort via increment_asset_usage — wrapped so a Supabase hiccup can
    never fail reel creation."""
    if not filename:
        return
    cache = _load_cache()
    cap = int((get_setting("music") or {}).get("cooldown_recent_cap", RECENT_CAP))
    recent = [f for f in cache.get(RECENT_KEY, []) if f != filename]
    recent.insert(0, filename)
    cache[RECENT_KEY] = recent[:cap]
    _save_cache(cache)

    try:
        from backend.db import list_assets, increment_asset_usage
        row = next((r for r in list_assets("music") if r.get("filename") == filename), None)
        if row and row.get("id"):
            increment_asset_usage(row["id"])
    except Exception as exc:
        log.warning("music_fetcher: usage-count bump failed (non-fatal) for %s: %s", filename, exc)


def _local_pack_track(category: str, avoid_names: set[str] | None = None) -> str | None:
    """Random mp3 from the local pack: category folder first, then _shared, then
    (last resort) anywhere under PACKS_DIR — covers pools like travel/ that
    don't match any single category name.

    Skips recently-picked files (*avoid_names*) when alternatives exist, so the
    no-cache fallback path also rotates instead of repeating a track.
    """
    for sub in (category, "_shared"):
        d = PACKS_DIR / sub
        if d.is_dir():
            mp3s = sorted(d.glob("*.mp3"))
            if not mp3s:
                continue
            fresh = [m for m in mp3s if not avoid_names or m.name not in avoid_names]
            return str(random.choice(fresh or mp3s))

    if PACKS_DIR.exists():
        all_files = [f for f in PACKS_DIR.rglob("*")
                    if f.is_file() and f.suffix.lower() in (".mp3", ".m4a", ".wav")]
        if all_files:
            fresh = [f for f in all_files if not avoid_names or f.name not in avoid_names]
            return str(random.choice(fresh or all_files))
    return None


def _migrate_legacy_cache(cache: dict) -> dict:
    """Convert the old `{category: [track,...]}` bucket cache into the flat,
    id-keyed schema. Same id appearing in multiple category buckets is deduped —
    its categories list becomes the union. `_recent_picks` is preserved untouched."""
    tracks: dict = {}
    for key, value in cache.items():
        if key == RECENT_KEY or not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("id") or item.get("filename") or uuid.uuid4().hex[:12])
            if tid in tracks:
                existing = set(tracks[tid].get("categories") or [])
                existing.add(key)
                tracks[tid]["categories"] = sorted(existing)
                continue
            tracks[tid] = {
                "filename": item.get("filename", ""),
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "duration": item.get("duration"),
                "popularity": item.get("popularity"),
                "license": item.get("license", ""),
                "mood": item.get("mood"),
                "categories": [key],
                "favourite": False,
                "usage_count": 0,
                "last_used_at": None,
            }
    migrated: dict = {"tracks": tracks}
    if RECENT_KEY in cache:
        migrated[RECENT_KEY] = cache[RECENT_KEY]
    return migrated


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {"tracks": {}}
    try:
        raw = json.loads(CACHE_FILE.read_text())
    except (ValueError, OSError):
        return {"tracks": {}}
    if "tracks" not in raw:
        migrated = _migrate_legacy_cache(raw)
        _save_cache(migrated)
        log.info("music_fetcher: migrated legacy bucket cache.json to flat schema (%d tracks)",
                 len(migrated.get("tracks", {})))
        return migrated
    return raw


def _save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _category_matches(entry: dict, category: str) -> bool:
    categories = entry.get("categories") or []
    return not categories or category in categories


def search_tracks(category: str, tags: list[str] | None = None, per_page=20,
                  mood: str | None = None) -> list[dict]:
    if not JAMENDO_CLIENT_ID:
        return []

    fuzzytags = CATEGORY_TAGS.get(category, CATEGORY_TAGS["hidden_gem"])
    if mood and mood in MOOD_TAGS:
        # Caption mood (Enh G) leads the search so the bed matches the clip's tone.
        fuzzytags = f"{MOOD_TAGS[mood]} {fuzzytags}"
    if tags:
        # Bias the mood search toward the clip's descriptive tags.
        fuzzytags = f"{fuzzytags} {' '.join(tags)}"

    params = {
        "client_id": JAMENDO_CLIENT_ID,
        "format": "json",
        "limit": per_page,
        "fuzzytags": fuzzytags,
        "vocalinstrumental": "instrumental",  # instrumental beds suit reels
        "audiodownload_allowed": "true",       # only downloadable tracks
        "include": "musicinfo licenses",
        "order": "popularity_total",
    }

    resp = requests.get(JAMENDO_API, params=params, timeout=15)
    if resp.status_code != 200:
        return []

    data = resp.json()
    return data.get("results", [])


def download_track(track: dict, category: str = "_shared") -> str | None:
    audio_url = track.get("audiodownload") or track.get("audio")
    if not audio_url:
        return None

    track_id = str(track.get("id", hashlib.md5(audio_url.encode()).hexdigest()))
    # Save into the category's local pack so Jamendo downloads accumulate by
    # music type and get reused by _local_pack_track on later runs.
    dest_dir = PACKS_DIR / category
    dest_dir.mkdir(parents=True, exist_ok=True)
    local_path = dest_dir / f"{track_id}.mp3"

    if local_path.exists():
        return str(local_path)

    resp = requests.get(audio_url, timeout=30)
    if resp.status_code != 200:
        return None

    local_path.write_bytes(resp.content)
    _invalidate_resolve_cache()
    return str(local_path)


def get_track_for_category(category: str, tags: list[str] | None = None,
                         avoid_ids: list[str] | None = None,
                         clip_len: float | None = None,
                         mood: str | None = None,
                         avoid_names: list[str] | None = None) -> str | None:
    """Return a local mp3 path best matching *category* and optional *clip_len*.

    Selection order (local-first):
      1. Score-rank cached entries (source bonus: Pixabay/Chosic > Jamendo,
         then category-mood + caption-mood + duration + popularity + favourite/
         usage + jitter). Path resolved via rglob regardless of which pack
         folder the file physically lives in.
      2. Jamendo API — only if no local file was found. Downloads and caches.
      3. _local_pack_track fallback (random from packs/ without cache).

    tags: optional descriptive tags for the clip; folded into the Jamendo
      search bias when present (was a country bias pre-refactor). None → no bias.
    clip_len (seconds): pass clip duration so the selector prefers tracks that
      cover the full clip. None → duration ignored (backward-compatible).
    mood (Enh G): caption-derived mood key; biases local scoring + the Jamendo
      search. None → category-only behaviour (backward-compatible).
    avoid_names: extra filenames to deprioritize on top of the built-in
      recently-picked cooldown (caller override). None → cooldown only.
    """
    cache = _load_cache()
    # Recently-picked cooldown (across all categories) so consecutive reels don't
    # reuse the same bed. Merge with any caller-supplied names.
    avoid = set(_get_recent(cache)) | set(avoid_names or [])

    path = _select_track(cache, category, tags, avoid_ids, clip_len, mood, avoid)
    if path:
        _record_recent(Path(path).name)
    return path


def _select_track(cache: dict, category: str, tags: list[str] | None,
                  avoid_ids: list[str] | None, clip_len: float | None,
                  mood: str | None, avoid_names: set[str]) -> str | None:
    raw_tracks = cache.setdefault("tracks", {})
    # Scoring/candidate view: favourite/usage_count/categories/mood overlaid from
    # the assets table (1.11.0 source of truth) — filename/source/duration
    # still come from the raw cache entry via this same overlaid dict (only
    # the 5 overlay fields are replaced, everything else passes through).
    tracks = _overlay_asset_fields(raw_tracks)
    music_cfg = get_setting("music") or {}

    candidates = [(tid, e) for tid, e in tracks.items() if _category_matches(e, category)]
    if avoid_ids:
        candidates = [(tid, e) for tid, e in candidates if tid not in avoid_ids]

    # Score-rank cached entries (Pixabay/Chosic > Jamendo via source bonus;
    # favourite/usage lift; recently-picked tracks pushed down by avoid_names).
    # Try in score order until one resolves to a real file on disk — resolution
    # is rglob-based (_resolve_by_name) so physical folder location no longer
    # has to match the category key.
    if candidates:
        scored = sorted(candidates,
                        key=lambda te: _score_track(te[1], category, clip_len, mood, avoid_names, music_cfg),
                        reverse=True)
        for _tid, entry in scored:
            local_path = _resolve_by_name(entry.get("filename"))
            if local_path and local_path.exists():
                return str(local_path)

    # No local file found — try Jamendo API as fallback.
    api_tracks = search_tracks(category, tags=tags, mood=mood)
    if not api_tracks:
        # API unavailable: try all cached entries for this category ignoring avoid_ids.
        all_candidates = [(tid, e) for tid, e in tracks.items() if _category_matches(e, category)]
        if all_candidates:
            scored = sorted(all_candidates,
                            key=lambda te: _score_track(te[1], category, clip_len, mood, avoid_names, music_cfg),
                            reverse=True)
            for _tid, entry in scored:
                local_path = _resolve_by_name(entry.get("filename"))
                if local_path and local_path.exists():
                    return str(local_path)
        return _local_pack_track(category, avoid_names)

    random.shuffle(api_tracks)
    for track in api_tracks:
        track_id = str(track.get("id", ""))
        if avoid_ids and track_id in avoid_ids:
            continue

        path = download_track(track, category)
        if path:
            # Written to raw_tracks (not the overlaid `tracks` view) so a
            # freshly-downloaded entry's physical bookkeeping is what
            # actually lands in cache.json — the overlay stays a read-only
            # scoring/display projection, never persisted back to disk.
            if track_id not in raw_tracks:
                raw_tracks[track_id] = {
                    "filename": Path(path).name, "title": track.get("name", ""),
                    "source": "jamendo", "duration": None, "popularity": None,
                    "license": "", "mood": None, "categories": [category],
                    "favourite": False, "usage_count": 0, "last_used_at": None,
                }
            cache["tracks"] = raw_tracks
            _save_cache(cache)
            return path

    # Jamendo had hits but all downloads failed — last resort.
    return _local_pack_track(category, avoid_names)


def resolve_local_track(url: str | None = None, track_id: str | None = None) -> str | None:
    """Resolve a music picker selection (served URL and/or track id) to a local
    absolute file path usable by the video pipeline.

    Handles three cases:
      1. A `/static/assets/…` served URL → maps back under ASSETS_DIR.
      2. A bare filename or track id → resolved via the shared rglob cache
         (_resolve_by_name), so it works regardless of which pack folder the
         file actually lives in.
      3. A remote http(s) URL → downloaded into packs/_shared and cached.
    Returns None when nothing resolvable is found.
    """
    from backend.config import ASSETS_DIR

    # Case 1: served static URL (…/static/assets/music/…).
    if url:
        marker = "static/assets/"
        if marker in url:
            rel = url.split(marker, 1)[1].lstrip("/")
            cand = (ASSETS_DIR / rel).resolve()
            try:
                cand.relative_to(MUSIC_DIR.resolve())  # keep inside MUSIC_DIR
                if cand.exists():
                    return str(cand)
            except ValueError:
                pass

    # Case 2: locate by filename / track id anywhere under the packs.
    needle = None
    if url and not url.startswith("http"):
        needle = Path(url).name
    if not needle and track_id:
        needle = track_id
    if needle:
        found = _resolve_by_name(needle)
        if found:
            return str(found)

    # Case 3: remote URL → download into the shared pack.
    if url and url.startswith("http"):
        try:
            dest_dir = PACKS_DIR / "_shared"
            dest_dir.mkdir(parents=True, exist_ok=True)
            name = track_id or hashlib.md5(url.encode()).hexdigest()
            local_path = dest_dir / f"{Path(name).stem}.mp3"
            if local_path.exists():
                return str(local_path)
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                local_path.write_bytes(resp.content)
                _invalidate_resolve_cache()
                return str(local_path)
        except Exception:
            return None
    return None


# ── Admin management (audio.py route surface) ────────────────────────────────

def _guess_source(stem: str) -> str:
    s = stem.lower()
    if s.startswith("pxb"):
        return "pixabay"
    if s.startswith("chosic"):
        return "chosic"
    if s.startswith("jamendo"):
        return "jamendo"
    return "local"


def _probe_duration(path: Path) -> float | None:
    """ffprobe media duration in seconds, or None on failure. Subprocess
    invocation mirrors audio_probe.py's `_probe_duration` (list-form args,
    never shell=True)."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            stderr=subprocess.DEVNULL, timeout=15,
        )
        return round(float(out.strip()), 2)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            ValueError, OSError):
        return None


def register_local_file(path: Path) -> str:
    """Ensure *path* has a flat-cache entry (bare, categories=[] → selectable
    everywhere), returning its track_id. Idempotent — if an entry already
    exists for this filename, returns its existing id unchanged. Used both by
    discover_new_files() and by the upload routes so a freshly-uploaded track
    appears in list_all_tracks() immediately, without waiting for a refresh."""
    cache = _load_cache()
    tracks = cache.setdefault("tracks", {})
    for tid, e in tracks.items():
        if e.get("filename") == path.name:
            return tid
    tid = f"local_{uuid.uuid4().hex[:12]}"
    tracks[tid] = {
        "filename": path.name,
        "title": path.stem.replace("_", " ").replace("-", " ").title(),
        "source": _guess_source(path.stem), "duration": None, "popularity": None,
        "license": "", "mood": None, "categories": [],
        "favourite": False, "usage_count": 0, "last_used_at": None,
    }
    cache["tracks"] = tracks
    _save_cache(cache)
    _invalidate_resolve_cache()
    return tid


def list_all_tracks() -> list[dict]:
    """Every track in the flat cache with resolved url/local_path + all
    metadata. Backs GET /api/audio and (as a thinner projection) GET /api/assets/music.

    favourite/usage_count/categories/mood/last_used_at are overlaid from the
    assets table (1.11.0 source of truth) via the same `_overlay_asset_fields`
    helper `_select_track` uses for scoring — one shared code path."""
    cache = _load_cache()
    raw_tracks = cache.get("tracks", {})
    tracks = _overlay_asset_fields(raw_tracks)
    out = []
    for tid, entry in tracks.items():
        resolved = _resolve_by_name(entry.get("filename"))
        url = None
        if resolved:
            try:
                rel = resolved.relative_to(MUSIC_DIR.parent)  # relative to assets/
                url = f"/static/assets/{rel.as_posix()}"
            except ValueError:
                url = None
        out.append({
            "id": tid,
            "filename": entry.get("filename", ""),
            "title": entry.get("title", ""),
            "source": entry.get("source", ""),
            "duration": entry.get("duration"),
            "popularity": entry.get("popularity"),
            "license": entry.get("license", ""),
            "mood": entry.get("mood"),
            "categories": entry.get("categories", []),
            "favourite": bool(entry.get("favourite", False)),
            "usage_count": int(entry.get("usage_count") or 0),
            "last_used_at": entry.get("last_used_at"),
            "url": url,
            "local_path": str(resolved) if resolved else None,
            "exists": bool(resolved and resolved.exists()),
        })
    _mirror_tracks_to_assets(out)
    return out


# ── assets table mirror (1.10.0) ─────────────────────────────────────────────
# One-directional sync: cache.json remains the working set _select_track()
# reads for category/hook-score selection (untouched); the `assets` table is a
# separate admin/public-URL index that reconcile()/the Assets admin page read.
# In-memory signature avoids re-writing on every list_all_tracks() call (hit by
# both GET /api/audio and GET /api/assets/music) when nothing actually changed.
_LAST_MIRRORED_SIGNATURE: str | None = None


def _track_to_asset_row(t: dict) -> dict:
    local_path = None
    if t.get("local_path"):
        try:
            from backend.config import ASSETS_DIR
            local_path = str(Path(t["local_path"]).relative_to(ASSETS_DIR))
        except ValueError:
            local_path = None
    return {
        "id": f"music_{t['id']}",
        "type": "music",
        "name": t.get("title") or t.get("filename", ""),
        "filename": t.get("filename", ""),
        "local_path": local_path,
        "size_bytes": None,
        "meta": {
            "duration": t.get("duration"),
            "categories": t.get("categories", []),
            "mood": t.get("mood"),
            "favourite": t.get("favourite", False),
            "usage_count": t.get("usage_count", 0),
            "last_used_at": t.get("last_used_at"),
            "source": t.get("source", ""),
        },
    }


def _mirror_tracks_to_assets(tracks: list[dict]) -> None:
    """Best-effort, non-blocking mirror of the flat cache into `assets` rows
    (type=music) — never raises, never affects list_all_tracks()'s return
    value. No-op when Supabase isn't configured.

    Matches existing rows by filename (not id) before upserting, so a row
    that assets_index.reconcile() already created for the same physical file
    (with its own generated id) gets updated in place instead of duplicated —
    this mirror and reconcile() write the same table from two different id
    schemes and must converge on one row per filename."""
    global _LAST_MIRRORED_SIGNATURE
    try:
        from backend.db import _use_supabase, list_assets, bulk_upsert_assets
        if not _use_supabase() or not tracks:
            return
        signature = hashlib.md5(
            json.dumps(tracks, sort_keys=True, default=str).encode()
        ).hexdigest()
        if signature == _LAST_MIRRORED_SIGNATURE:
            return
        existing_by_filename = {r["filename"]: r["id"] for r in list_assets("music") if r.get("filename")}
        rows = []
        for t in tracks:
            if not t.get("exists"):
                continue
            row = _track_to_asset_row(t)
            existing_id = existing_by_filename.get(row["filename"])
            if existing_id:
                row["id"] = existing_id
            rows.append(row)
        bulk_upsert_assets(rows)
        _LAST_MIRRORED_SIGNATURE = signature
    except Exception as exc:
        log.warning("music_fetcher: assets-table mirror failed (non-fatal): %s", exc)


def _scan_pack_files() -> list[Path]:
    if not PACKS_DIR.exists():
        return []
    return [f for f in PACKS_DIR.rglob("*")
            if f.is_file() and f.suffix.lower() in AUDIO_FILE_EXTS]


def _group_by_hash(files: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for f in files:
        try:
            h = hashlib.md5()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            groups.setdefault(h.hexdigest(), []).append(f)
        except OSError:
            continue
    return groups


def _pick_keep(paths: list[Path]) -> tuple[Path, list[Path], list[str]]:
    """Among duplicate-content files, prefer a copy already in _shared/, else
    the alphabetically-first category folder. Returns (keep, delete, categories_merged)."""
    shared_copy = next((p for p in paths if p.parent.name == "_shared"), None)
    keep = shared_copy or sorted(paths, key=lambda p: (p.parent.name, p.name))[0]
    delete = [p for p in paths if p != keep]
    categories_merged = sorted({p.parent.name for p in paths
                            if p.parent.name not in ("_shared", "_uploads")})
    return keep, delete, categories_merged


def _backfill_durations(tracks: dict, filename_map: dict[str, Path]) -> bool:
    """Fill in `duration` for any entry missing it, ffprobing the physical
    file when resolvable. Returns True if anything changed."""
    changed = False
    for entry in tracks.values():
        if entry.get("duration"):
            continue
        fp = filename_map.get(entry.get("filename")) or _resolve_by_name(entry.get("filename"))
        if not fp or not fp.exists():
            continue
        dur = _probe_duration(fp)
        if dur:
            entry["duration"] = dur
            changed = True
    return changed


def discover_new_files(dry_run: bool = True) -> dict:
    """Rglob assets/music/packs/** (all subfolders incl. travel/, _shared/,
    _uploads/) and:
      1. Register any file not yet in the flat cache as a bare entry
         (categories=[] → selectable everywhere until tagged).
      2. Dedupe pass: group files by content hash; where duplicates exist,
         keep one physical copy (prefer _shared/, else alphabetically-first
         category folder) and merge every source folder name into the surviving
         entry's `categories`.
      3. Orphan prune: cache entries whose file no longer exists anywhere on
         disk (manually deleted from packs/) are dropped from the cache so
         stale tracks stop showing up as unplayable ghosts in the Audio page.
      4. Duration backfill: ffprobe any entry missing `duration` and fill it
         in — always runs (non-destructive) regardless of dry_run.

    dry_run=True (default): preview only — no deletes, no new-entry/dedupe/
    prune cache writes (duration backfill on already-known entries still
    persists, since it's purely additive).
    dry_run=False: executes the deletes/prunes + registers new entries + persists.

    Returns {"new_files": [...], "dup_groups": [...], "would_delete_count": N,
    "orphaned": [...], "orphaned_count": N}.
    """
    cache = _load_cache()
    tracks = cache.setdefault("tracks", {})
    known_filenames = {e.get("filename") for e in tracks.values() if e.get("filename")}

    all_files = _scan_pack_files()
    on_disk_names = {f.name for f in all_files}
    new_files = [f for f in all_files if f.name not in known_filenames]

    hash_groups = _group_by_hash(all_files)
    dup_groups_report = []
    would_delete_count = 0
    for _h, paths in hash_groups.items():
        if len(paths) < 2:
            continue
        keep, delete, categories_merged = _pick_keep(paths)
        would_delete_count += len(delete)
        dup_groups_report.append({
            "keep": str(keep), "delete": [str(p) for p in delete],
            "categories_merged": categories_merged,
        })

    orphans_report = [
        {"id": tid, "filename": e.get("filename", ""), "title": e.get("title", "")}
        for tid, e in tracks.items() if e.get("filename") not in on_disk_names
    ]

    if dry_run:
        filename_map = {f.name: f for f in all_files}
        if _backfill_durations(tracks, filename_map):
            cache["tracks"] = tracks
            _save_cache(cache)
        return {
            "new_files": [str(f) for f in new_files],
            "dup_groups": dup_groups_report,
            "would_delete_count": would_delete_count,
            "orphaned": orphans_report,
            "orphaned_count": len(orphans_report),
        }

    # Real pass: register new bare entries.
    for f in new_files:
        if f.name not in {e.get("filename") for e in tracks.values()}:
            tid = f"local_{uuid.uuid4().hex[:12]}"
            tracks[tid] = {
                "filename": f.name,
                "title": f.stem.replace("_", " ").replace("-", " ").title(),
                "source": _guess_source(f.stem), "duration": None, "popularity": None,
                "license": "", "mood": None, "categories": [],
                "favourite": False, "usage_count": 0, "last_used_at": None,
            }

    # Execute dedup deletes + category merge.
    for group in dup_groups_report:
        keep_path = Path(group["keep"])
        keep_tid = next((t for t, e in tracks.items() if e.get("filename") == keep_path.name), None)
        if keep_tid is None:
            keep_tid = f"local_{uuid.uuid4().hex[:12]}"
            tracks[keep_tid] = {
                "filename": keep_path.name,
                "title": keep_path.stem.replace("_", " ").title(),
                "source": _guess_source(keep_path.stem), "duration": None, "popularity": None,
                "license": "", "mood": None, "categories": [],
                "favourite": False, "usage_count": 0, "last_used_at": None,
            }
        keep_entry = tracks[keep_tid]
        keep_entry["categories"] = sorted(set(keep_entry.get("categories") or []) | set(group["categories_merged"]))

        for dp_str in group["delete"]:
            dp = Path(dp_str)
            for tid in [t for t, e in list(tracks.items()) if e.get("filename") == dp.name]:
                tracks.pop(tid, None)
            try:
                dp.unlink(missing_ok=True)
            except OSError:
                log.warning("discover_new_files: failed to delete dup %s", dp)

    deleted_names = {Path(p).name for g in dup_groups_report for p in g["delete"]}
    filename_map = {f.name: f for f in all_files if f.name not in deleted_names}
    _backfill_durations(tracks, filename_map)

    # Prune orphaned entries — computed against the pre-dedupe on_disk_names,
    # so files just removed by the dedupe pass above (already popped in the
    # loop) are never double-reported here.
    for orphan in orphans_report:
        tracks.pop(orphan["id"], None)

    cache["tracks"] = tracks
    _save_cache(cache)
    _invalidate_resolve_cache()

    return {
        "new_files": [str(f) for f in new_files],
        "dup_groups": dup_groups_report,
        "would_delete_count": would_delete_count,
        "orphaned": orphans_report,
        "orphaned_count": len(orphans_report),
    }


def trim_track(
    track_id: str,
    start_s: float,
    end_s: float,
    fade_in_s: float = 0.0,
    fade_out_s: float = 0.0,
) -> str | None:
    """Trim an existing track into a new file (packs/_uploads/), registering a
    new flat-cache entry that inherits the source track's categories/mood.
    Returns the new track_id, or None on validation/ffmpeg failure."""
    if start_s is None or end_s is None or start_s < 0 or end_s <= start_s:
        return None

    # Clamp fades to sane bounds rather than raising — this is called from an
    # API route. 0-5s each, and neither fade may exceed half the trimmed
    # clip's length.
    clip_len = end_s - start_s
    try:
        fade_in_s = float(fade_in_s or 0.0)
    except (TypeError, ValueError):
        fade_in_s = 0.0
    try:
        fade_out_s = float(fade_out_s or 0.0)
    except (TypeError, ValueError):
        fade_out_s = 0.0
    fade_in_s = max(0.0, min(fade_in_s, 5.0, clip_len / 2))
    fade_out_s = max(0.0, min(fade_out_s, 5.0, clip_len / 2))

    cache = _load_cache()
    tracks = cache.setdefault("tracks", {})
    entry = tracks.get(track_id)
    if not entry:
        return None

    src_path = _resolve_by_name(entry.get("filename"))
    if not src_path or not src_path.exists():
        return None

    duration = entry.get("duration") or _probe_duration(src_path)
    if duration and (start_s >= duration or end_s > duration + 0.5):
        return None

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOADS_DIR / f"trim_{uuid.uuid4().hex[:10]}{src_path.suffix.lower()}"

    def _run_ffmpeg(extra: list[str]) -> bool:
        cmd = ["ffmpeg", "-hide_banner", "-y", "-ss", str(start_s), "-to", str(end_s),
              "-i", str(src_path), *extra, str(dest)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0 and dest.exists()

    if fade_in_s > 0 or fade_out_s > 0:
        # Fades require an audio filter, which the stream-copy fast path
        # can't apply — go straight to the re-encode path.
        if fade_in_s > 0 and fade_out_s > 0:
            af = (
                f"afade=t=in:st=0:d={fade_in_s},"
                f"afade=t=out:st={max(0, clip_len - fade_out_s)}:d={fade_out_s}"
            )
        elif fade_in_s > 0:
            af = f"afade=t=in:st=0:d={fade_in_s}"
        else:
            af = f"afade=t=out:st={max(0, clip_len - fade_out_s)}:d={fade_out_s}"
        ok = _run_ffmpeg(["-af", af])
    else:
        # Stream-copy trim first (fast); fall back to re-encode if copy fails
        # or produces a file whose duration is way off (non-keyframe-aligned
        # cut).
        ok = _run_ffmpeg(["-c", "copy"])
        if ok:
            got_dur = _probe_duration(dest)
            expected = end_s - start_s
            if got_dur is None or abs(got_dur - expected) > 1.5:
                dest.unlink(missing_ok=True)
                ok = False
        if not ok:
            ok = _run_ffmpeg([])
    if not ok:
        dest.unlink(missing_ok=True)
        return None

    new_tid = f"trim_{uuid.uuid4().hex[:10]}"
    tracks[new_tid] = {
        "filename": dest.name,
        "title": f"{entry.get('title') or 'Track'} (trim)",
        "source": "trimmed",
        "duration": round(end_s - start_s, 2),
        "popularity": entry.get("popularity"),
        "license": entry.get("license", ""),
        "mood": entry.get("mood"),
        "categories": list(entry.get("categories") or []),
        "favourite": False, "usage_count": 0, "last_used_at": None,
    }
    cache["tracks"] = tracks
    _save_cache(cache)
    _invalidate_resolve_cache()

    # Additive (1.10.0): also mirror the trimmed file into Supabase Storage +
    # the assets table when configured, linking back to the source track via
    # parent_asset_id. Best-effort and non-fatal — the local trim above has
    # already succeeded and new_tid is returned either way, so audio.py's
    # trim route and WaveformTrimModal.tsx need no changes.
    try:
        from backend.config import ASSETS_DIR
        from backend.pipeline.storage_supabase import storage_configured, upload_file
        from backend.db import create_asset, list_assets
        if storage_configured():
            content_type = {
                ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav",
                ".aac": "audio/aac", ".ogg": "audio/ogg",
            }.get(dest.suffix.lower(), "application/octet-stream")
            storage_path = f"music/packs/_uploads/{dest.name}"
            public_url = upload_file(str(dest), storage_path, content_type)
            # Only link parent_asset_id when the source track has actually
            # been mirrored into `assets` already (e.g. via a prior
            # list_all_tracks() call) — the table has a FK to assets(id), so
            # guessing an unmirrored id here would fail the whole insert
            # instead of just leaving the lineage field empty.
            parent_id = next(
                (r["id"] for r in list_assets("music") if r.get("filename") == entry.get("filename")),
                None,
            )
            create_asset({
                "id": f"music_{new_tid}",
                "type": "music",
                "name": f"{entry.get('title') or 'Track'} (trim)",
                "filename": dest.name,
                "storage_path": storage_path,
                "public_url": public_url,
                "local_path": str(dest.relative_to(ASSETS_DIR)),
                "size_bytes": dest.stat().st_size,
                "parent_asset_id": parent_id,
                "meta": {
                    "duration": round(end_s - start_s, 2),
                    "categories": list(entry.get("categories") or []),
                    "mood": entry.get("mood"),
                    "source": "trimmed",
                },
            })
    except Exception as exc:
        log.warning("music_fetcher: trim_track Storage mirror failed (non-fatal) for %s: %s", new_tid, exc)

    return new_tid


def run(category="hidden_gem", tags=None, clip_len=None, mood=None):
    # Works even without JAMENDO_CLIENT_ID — falls back to the local pack.
    path = get_track_for_category(category, tags=tags, clip_len=clip_len, mood=mood)
    if path:
        return {"track": path, "category": category, "mood": mood}
    return {"error": "no_tracks_found", "category": category, "mood": mood}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="hidden_gem",
                        choices=list(CATEGORY_TAGS.keys()))
    parser.add_argument("--tags", default=None,
                        help="Comma-separated descriptive tags to bias the search")
    parser.add_argument("--clip-len", type=float, default=None,
                        help="Clip duration in seconds (for smart matching test)")
    parser.add_argument("--mood", default=None, choices=list(MOOD_TAGS.keys()),
                        help="Caption mood to bias selection (Enh G)")
    args = parser.parse_args()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    result = run(category=args.category, tags=tags,
                 clip_len=args.clip_len, mood=args.mood)
    print(result)
