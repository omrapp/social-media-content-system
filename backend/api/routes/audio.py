"""
Audio (music) management endpoints — admin-manageable metadata (favourite,
usage stats, category tags, mood, trim) layered on top of the flat music_fetcher
manifest (assets/music/cache.json).

Complements /api/assets/music, which stays read-only and shape-frozen so
MusicPicker.tsx keeps working unchanged — this router is the admin surface
the Assets page's Music tab drives (formerly a standalone Audio page).
"""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel

from backend.config import MUSIC_DIR
from backend.api.auth import verify_token
from backend.pipeline.music_fetcher import (
    UPLOADS_DIR, list_all_tracks, register_local_file, discover_new_files,
    trim_track, _load_cache, _save_cache, _resolve_by_name, _invalidate_resolve_cache,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audio", tags=["audio"], dependencies=[Depends(verify_token)])

AUDIO_EXTS = (".mp3", ".m4a", ".wav")
MAX_AUDIO_BYTES = 50 * 1024 * 1024  # 50 MB cap, matches the screens-upload convention


async def _read_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Read upload in 1 MB chunks, rejecting at max_bytes to avoid RAM exhaustion."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"File exceeds {max_bytes // (1024 * 1024)} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _find(track_id: str) -> dict | None:
    return next((t for t in list_all_tracks() if t["id"] == track_id), None)


@router.get("")
def list_audio(
    category: str | None = Query(default=None),
    favourite: bool | None = Query(default=None),
    sort: str = Query(default="title"),
):
    """List every track in the flat manifest, optionally filtered by category /
    favourite and sorted. `category` matches tracks explicitly tagged to it OR
    untagged (categories=[] → matches-any, same semantics as selection scoring)."""
    tracks = list_all_tracks()
    if category:
        tracks = [t for t in tracks if not t.get("categories") or category in t["categories"]]
    if favourite is not None:
        tracks = [t for t in tracks if bool(t.get("favourite")) == favourite]

    sort_keys = {
        "title": lambda t: (t.get("title") or "").lower(),
        "favourite": lambda t: (0 if t.get("favourite") else 1, (t.get("title") or "").lower()),
        "usage_count": lambda t: -(t.get("usage_count") or 0),
        "duration": lambda t: t.get("duration") or 0,
        # Most-recently-used first; never-used tracks (empty string) sort last.
        "last_used_at": lambda t: t.get("last_used_at") or "",
    }
    tracks.sort(key=sort_keys.get(sort, sort_keys["title"]), reverse=(sort == "last_used_at"))
    return {"tracks": tracks}


@router.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    """Upload a custom track — mirrors assets.py's upload_music validation
    (extension allowlist, uuid-suffixed filename) plus a size cap, and
    registers it in the flat cache immediately so it's selectable right away."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXTS:
        raise HTTPException(400, f"Unsupported audio format '{ext}'. Allowed: {AUDIO_EXTS}")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(file.filename or "upload").stem[:60]
    dest = UPLOADS_DIR / f"{stem}_{uuid.uuid4().hex[:6]}{ext}"

    try:
        content = await _read_bounded(file, MAX_AUDIO_BYTES)
        dest.write_bytes(content)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("audio upload failed")
        raise HTTPException(500, f"Upload failed: {exc}")

    track_id = register_local_file(dest)
    log.info("audio upload: saved %s (%d bytes) as %s", dest, len(content), track_id)
    return {"track": _find(track_id)}


class TrackPatch(BaseModel):
    title: str | None = None
    categories: list[str] | None = None
    mood: str | None = None
    favourite: bool | None = None


@router.put("/{track_id}")
def update_audio(track_id: str, body: TrackPatch):
    cache = _load_cache()
    tracks = cache.setdefault("tracks", {})
    entry = tracks.get(track_id)
    if not entry:
        raise HTTPException(404, "Track not found")

    if body.title is not None:
        entry["title"] = body.title
    if body.categories is not None:
        entry["categories"] = list(body.categories)
    if body.mood is not None:
        entry["mood"] = body.mood
    if body.favourite is not None:
        entry["favourite"] = bool(body.favourite)

    cache["tracks"] = tracks
    _save_cache(cache)

    # Assets table is now the source of truth for favourite/tags/mood
    # (1.11.0) — best-effort mirror onto the matching row, matched by
    # filename. Never raises; the cache.json write above already succeeded
    # either way, so this endpoint's behavior is unchanged when Supabase
    # isn't configured.
    if body.favourite is not None or body.categories is not None or body.mood is not None:
        try:
            from backend.db import list_assets, update_asset
            row = next(
                (r for r in list_assets("music") if r.get("filename") == entry.get("filename")),
                None,
            )
            if row and row.get("id"):
                patch: dict = {}
                if body.favourite is not None:
                    patch["favourite"] = bool(body.favourite)
                if body.categories is not None:
                    patch["tags"] = list(body.categories)
                if body.mood is not None:
                    patch["mood"] = body.mood
                update_asset(row["id"], patch)
        except Exception as exc:
            log.warning("update_audio: assets row patch failed (non-fatal) for %s: %s", track_id, exc)

    return {"track": _find(track_id)}


@router.delete("/{track_id}")
def delete_audio(track_id: str):
    """Hard-delete a track: remove the physical file (scoped-contained under
    MUSIC_DIR — mirrors merge_clips._safe_music_path's containment check) AND
    the flat-cache entry."""
    cache = _load_cache()
    tracks = cache.setdefault("tracks", {})
    entry = tracks.get(track_id)
    if not entry:
        raise HTTPException(404, "Track not found")

    resolved = _resolve_by_name(entry.get("filename"))
    if resolved:
        try:
            cand = resolved.resolve()
            if cand.is_relative_to(MUSIC_DIR.resolve()):
                cand.unlink(missing_ok=True)
        except Exception as exc:
            log.warning("audio delete: file unlink failed for %s: %s", track_id, exc)

    tracks.pop(track_id, None)
    cache["tracks"] = tracks
    _save_cache(cache)
    _invalidate_resolve_cache()
    return {"ok": True, "id": track_id}


class TrimRequest(BaseModel):
    start_s: float
    end_s: float
    fade_in_s: float = 0.0
    fade_out_s: float = 0.0


@router.post("/{track_id}/trim")
def trim_audio(track_id: str, body: TrimRequest):
    new_id = trim_track(track_id, body.start_s, body.end_s, body.fade_in_s, body.fade_out_s)
    if not new_id:
        raise HTTPException(
            400, "Trim failed — check start_s/end_s are within the source duration and start_s < end_s"
        )
    return {"track": _find(new_id)}


@router.post("/refresh")
def refresh_audio(confirm: bool = Query(default=False)):
    """Dry-run preview (default, confirm=false) of discover_new_files — new
    files + duplicate groups found under assets/music/packs/**, nothing
    written except non-destructive duration backfill. confirm=true executes
    the registration + dedupe deletes."""
    return discover_new_files(dry_run=not confirm)
