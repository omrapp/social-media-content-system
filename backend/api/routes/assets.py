"""
Asset browser endpoints — music and LUT files for the edit drawer.
"""

import logging
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel

from backend.config import MUSIC_DIR, LUTS_DIR, LUTS_CINEMATIC_DIR, FONTS_DIR, ASSETS_DIR
from backend.api.auth import verify_token
from backend.db import list_assets, get_asset, create_asset, update_asset, delete_asset
from backend.pipeline.storage_supabase import storage_configured, delete_object, upload_file
from backend.pipeline.assets_index import reconcile, ASSET_TYPES, _scan_local

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assets", tags=["assets"], dependencies=[Depends(verify_token)])

# Jamendo packs directory — mirrors music_fetcher.PACKS_DIR
PACKS_DIR = MUSIC_DIR / "packs"
UPLOADS_DIR = PACKS_DIR / "_uploads"

AUDIO_EXTS = (".mp3", ".m4a", ".wav")


def _storage_mirror_upload(asset_type: str, dest: Path, storage_prefix: str, content_type: str) -> None:
    """Best-effort, non-blocking Storage upload + `assets` row for a freshly
    saved local upload — never raises, so the calling upload route's response
    is byte-for-byte unchanged whether or not this succeeds (additive-only,
    per the assets-supabase-index plan). No-op when Storage isn't configured."""
    try:
        if not storage_configured():
            return
        storage_path = f"{storage_prefix}/{dest.name}"
        public_url = upload_file(str(dest), storage_path, content_type)
        create_asset({
            "id": f"{asset_type}_{uuid.uuid4().hex[:12]}",
            "type": asset_type,
            "name": dest.stem.replace("_", " ").replace("-", " ").title(),
            "filename": dest.name,
            "storage_path": storage_path,
            "public_url": public_url,
            "local_path": str(dest.relative_to(ASSETS_DIR)),
            "size_bytes": dest.stat().st_size,
            "meta": {},
        })
    except Exception as exc:
        log.warning("assets: Storage mirror failed for upload %s (non-fatal): %s", dest, exc)


def _asset_item_from_row(row: dict) -> dict:
    """Project an `assets` table row into the frontend-facing AssetItem shape.
    `local_exists` is always freshness-checked against disk at request time
    (never trusted from a possibly-stale DB column) — path is validated to
    resolve UNDER ASSETS_DIR first, mirroring lut_select.py's containment
    check, guarding against a `..`-poisoned local_path ever being served."""
    local_path = row.get("local_path")
    local_exists = False
    url = row.get("public_url")
    if local_path:
        try:
            candidate = (ASSETS_DIR / local_path).resolve()
            root = ASSETS_DIR.resolve()
            if candidate.is_relative_to(root) and candidate.exists():
                local_exists = True
                if not url:
                    url = f"/static/assets/{Path(local_path).as_posix()}"
        except Exception:
            local_exists = False
    return {
        "id": row.get("id"),
        "type": row.get("type"),
        "name": row.get("name"),
        "filename": row.get("filename"),
        "local_path": local_path,
        "url": url,
        "local_exists": local_exists,
        "size_bytes": row.get("size_bytes"),
        "parent_asset_id": row.get("parent_asset_id"),
        "meta": row.get("meta") or {},
        "created_at": row.get("created_at"),
        # Metadata cutover (1.11.0, migration 015) — real columns on every
        # asset type now, not just music's meta JSONB. Rows read before the
        # migration is applied simply omit these keys from Supabase, so the
        # defaults below keep the response shape stable either way.
        "favourite": bool(row.get("favourite", False)),
        "usage_count": int(row.get("usage_count") or 0),
        "tags": row.get("tags") or [],
        "last_used_at": row.get("last_used_at"),
        "mood": row.get("mood"),
    }


def _local_fallback_assets(type: str | None) -> list[dict]:
    """Lightweight per-type local-disk scan used only when Supabase isn't
    configured, so dev environments without Supabase creds still see
    something on the Assets page instead of an empty list."""
    types = [type] if type else list(ASSET_TYPES)
    out: list[dict] = []
    for t in types:
        if t not in ASSET_TYPES:
            continue
        for filename, path in sorted(_scan_local(t).items()):
            try:
                rel = path.relative_to(ASSETS_DIR)
                url = f"/static/assets/{rel.as_posix()}"
                rel_str = rel.as_posix()
            except ValueError:
                url = None
                rel_str = None
            out.append({
                "id": f"local_{t}_{path.stem}",
                "type": t,
                "name": path.stem.replace("_", " ").replace("-", " ").title(),
                "filename": filename,
                "local_path": rel_str,
                "url": url,
                "local_exists": True,
                "size_bytes": path.stat().st_size if path.exists() else None,
                "parent_asset_id": None,
                "meta": {},
                "created_at": None,
                "favourite": False,
                "usage_count": 0,
                "tags": [],
                "last_used_at": None,
                "mood": None,
            })
    return out


def _track_from_file(f: Path, category: str, shared: bool = False) -> dict:
    """Build a track dict from a file path."""
    # URL path relative to /static/assets root (which maps to ASSETS_DIR = assets/)
    rel = f.relative_to(MUSIC_DIR.parent)  # relative to assets/
    return {
        "id": f.stem,
        "title": f.stem.replace("_", " ").replace("-", " ").title(),
        "source": "local",
        "category": category,
        "shared": shared,
        "url": f"/static/assets/{rel.as_posix()}",
    }


@router.get("/fonts")
def list_fonts():
    """Scan assets/fonts/ for font files available for branding overlay."""
    fonts: list[dict] = []
    if FONTS_DIR.exists():
        for f in sorted(FONTS_DIR.iterdir()):
            if f.suffix.lower() in (".ttf", ".otf"):
                fonts.append({"name": f.stem, "file": f.name})
    return {"fonts": fonts}


@router.get("/luts")
def list_luts():
    """List available colour-grade LUTs: the legacy flat files in assets/luts/
    plus the curated cinematic set in assets/luts/cinematic/ joined with
    catalog.json (mood/category tags). `file` is the LUTS_DIR-relative path the
    pipeline expects (e.g. "warm.cube" or "cinematic/teal_orange.cube")."""
    from backend.pipeline.lut_select import load_catalog

    luts = [
        {"name": f.stem, "file": f.name, "tags": [], "categories": [],
         "intensity": 1.0, "source": "", "dir": "legacy"}
        for f in sorted(LUTS_DIR.glob("*.cube"))
    ]

    catalog = {e["file"]: e for e in load_catalog() if e.get("file")}
    for f in sorted(LUTS_CINEMATIC_DIR.glob("*.cube")):
        rel = f"cinematic/{f.name}"
        meta = catalog.get(rel, {})
        luts.append({
            "name": meta.get("name") or f.stem.replace("_", " ").title(),
            "file": rel,
            "tags": meta.get("tags", []),
            "categories": meta.get("categories", []),
            "intensity": meta.get("intensity", 1.0),
            "source": meta.get("source", ""),
            "dir": "cinematic",
        })
    return {"luts": luts}


@router.get("/music")
def list_music():
    """
    Return all cached tracks from the flat music_fetcher manifest, projected
    into the original per-file shape (id/title/source/category/shared/url) so
    MusicPicker.tsx keeps working unchanged (1.9.0: delegates to
    music_fetcher.list_all_tracks() instead of re-scanning the filesystem —
    the category buckets it used to scan no longer reflect physical layout).

    Tracks tagged to multiple categories resolve to one physical file (dedupe by
    resolved real path so each track appears once, tagged with its actual
    on-disk folder).
    """
    from backend.pipeline.music_fetcher import list_all_tracks

    tracks: list[dict] = []
    seen_real: set[str] = set()
    for t in list_all_tracks():
        if not t.get("exists") or not t.get("local_path"):
            continue
        p = Path(t["local_path"])
        real = str(p.resolve())
        if real in seen_real:
            continue
        seen_real.add(real)
        category = p.parent.name  # actual on-disk folder, e.g. "_shared", "culture"
        shared = category == "_shared" or p.is_symlink()
        tracks.append({
            "id": t["id"],
            "title": t.get("title") or p.stem.replace("_", " ").replace("-", " ").title(),
            "source": "local",
            "category": category,
            "shared": shared,
            "url": t.get("url"),
        })

    return {"music": tracks}


@router.post("/music/upload")
async def upload_music(file: UploadFile = File(...)):
    """
    Upload a custom music track (mp3/m4a/wav).
    Saved to PACKS_DIR/_uploads/ and immediately available in the track list.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXTS:
        raise HTTPException(400, f"Unsupported audio format '{ext}'. Allowed: {AUDIO_EXTS}")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(file.filename or "upload").stem[:60]
    # Deduplicate filename with a short uuid suffix
    dest = UPLOADS_DIR / f"{stem}_{uuid.uuid4().hex[:6]}{ext}"

    try:
        content = await file.read()
        dest.write_bytes(content)
    except Exception as exc:
        log.exception("music upload failed")
        raise HTTPException(500, f"Upload failed: {exc}")

    # Register in the flat music_fetcher cache so it's immediately selectable
    # and shows up in list_all_tracks() without waiting for a /api/audio/refresh.
    from backend.pipeline.music_fetcher import register_local_file
    register_local_file(dest)

    # Additive (1.10.0): also mirror into Supabase Storage + the assets table
    # when configured — non-breaking, response shape below is unchanged.
    _storage_mirror_upload("music", dest, "music/packs/_uploads",
                            mimetypes.guess_type(dest.name)[0] or "audio/mpeg")

    track = _track_from_file(dest, "_uploads")
    log.info("music upload: saved %s (%d bytes)", dest, len(content))
    return {"track": track}


# ── Intro / Outro screen assets ──────────────────────────────────────────────

VIDEO_EXTS = (".mp4", ".mov", ".m4v")
IMAGE_EXTS = (".jpg", ".jpeg", ".png")
SCREEN_EXTS = VIDEO_EXTS + IMAGE_EXTS

MAX_SCREEN_BYTES = 50 * 1024 * 1024  # 50 MB hard cap


def _screen_from_file(f: Path, category: str) -> dict:
    rel = f.relative_to(ASSETS_DIR)
    return {
        "id": f.stem,
        "name": f.stem.replace("_", " ").replace("-", " ").title(),
        "file": f.name,
        "category": category,
        "url": f"/static/assets/{rel.as_posix()}",
    }


@router.get("/intros")
def list_intros():
    """List uploaded intro/splash screen assets."""
    from backend.config import INTRO_DIR
    INTRO_DIR.mkdir(parents=True, exist_ok=True)
    items = [
        _screen_from_file(f, "intro")
        for f in sorted(INTRO_DIR.iterdir())
        if f.suffix.lower() in SCREEN_EXTS
    ]
    return {"intros": items}


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


@router.post("/intros/upload")
async def upload_intro(file: UploadFile = File(...)):
    """Upload an intro/splash screen asset (video or image, max 50 MB)."""
    from backend.config import INTRO_DIR
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SCREEN_EXTS:
        raise HTTPException(400, f"Unsupported format '{ext}'. Allowed: mp4, mov, m4v, jpg, jpeg, png")
    INTRO_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(file.filename or "intro").stem[:60]
    dest = INTRO_DIR / f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
    try:
        content = await _read_bounded(file, MAX_SCREEN_BYTES)
        dest.write_bytes(content)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("intro upload failed")
        raise HTTPException(500, f"Upload failed: {exc}")
    log.info("intro upload: saved %s (%d bytes)", dest, len(content))

    # Additive (1.10.0): also mirror into Supabase Storage + the assets table
    # when configured — non-breaking, response shape below is unchanged.
    _storage_mirror_upload("intro", dest, "intros", mimetypes.guess_type(dest.name)[0] or "application/octet-stream")

    return {"item": _screen_from_file(dest, "intro")}


@router.get("/outros")
def list_outros():
    """List uploaded cast/outro screen assets."""
    from backend.config import OUTRO_DIR
    OUTRO_DIR.mkdir(parents=True, exist_ok=True)
    items = [
        _screen_from_file(f, "outro")
        for f in sorted(OUTRO_DIR.iterdir())
        if f.suffix.lower() in SCREEN_EXTS
    ]
    return {"outros": items}


@router.post("/outros/upload")
async def upload_outro(file: UploadFile = File(...)):
    """Upload a cast/outro screen asset (video or image, max 50 MB)."""
    from backend.config import OUTRO_DIR
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SCREEN_EXTS:
        raise HTTPException(400, f"Unsupported format '{ext}'. Allowed: mp4, mov, m4v, jpg, jpeg, png")
    OUTRO_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(file.filename or "outro").stem[:60]
    dest = OUTRO_DIR / f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
    try:
        content = await _read_bounded(file, MAX_SCREEN_BYTES)
        dest.write_bytes(content)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("outro upload failed")
        raise HTTPException(500, f"Upload failed: {exc}")
    log.info("outro upload: saved %s (%d bytes)", dest, len(content))

    # Additive (1.10.0): also mirror into Supabase Storage + the assets table
    # when configured — non-breaking, response shape below is unchanged.
    _storage_mirror_upload("outro", dest, "outros", mimetypes.guess_type(dest.name)[0] or "application/octet-stream")

    return {"item": _screen_from_file(dest, "outro")}


# ── Editor sticker / image-overlay assets (2.0.0 Phase 5) ────────────────────

# PNG/WebP only: both carry an alpha channel, which is the whole point of a
# sticker, and both are what editor_edl._safe_sticker accepts for an EDL
# ImageLayer.asset. Smaller cap than the screen assets — these are overlays,
# not full-frame footage.
STICKER_EXTS = {".png", ".webp"}
MAX_STICKER_BYTES = 10 * 1024 * 1024  # 10 MB hard cap


def _sticker_from_file(f: Path) -> dict:
    rel = f.relative_to(ASSETS_DIR)
    return {
        "id": f.stem,
        "name": f.stem.replace("_", " ").replace("-", " ").title(),
        "file": f.name,
        # What an EDL ImageLayer.asset stores: ASSETS_DIR-relative, so
        # editor_edl._safe_sticker() resolves it back to this exact file.
        "asset": f"stickers/{f.name}",
        "url": f"/static/assets/{rel.as_posix()}",
    }


@router.get("/stickers")
def list_stickers():
    """List uploaded editor sticker/image-overlay assets. Ships empty — the
    library is whatever this install uploaded."""
    from backend.config import STICKERS_DIR
    STICKERS_DIR.mkdir(parents=True, exist_ok=True)
    items = [
        _sticker_from_file(f)
        for f in sorted(STICKERS_DIR.iterdir())
        if f.suffix.lower() in STICKER_EXTS
    ]
    return {"stickers": items}


@router.post("/stickers/upload")
async def upload_sticker(file: UploadFile = File(...)):
    """Upload a sticker/image overlay (PNG or WebP, max 10 MB)."""
    from backend.config import STICKERS_DIR
    ext = Path(file.filename or "").suffix.lower()
    if ext not in STICKER_EXTS:
        raise HTTPException(400, f"Unsupported format '{ext}'. Allowed: png, webp")
    STICKERS_DIR.mkdir(parents=True, exist_ok=True)
    # The uploaded name is never trusted as a path: only its stem survives, and
    # a uuid suffix keeps two uploads of "logo.png" from clobbering each other.
    stem = Path(file.filename or "sticker").stem[:60]
    dest = STICKERS_DIR / f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
    try:
        content = await _read_bounded(file, MAX_STICKER_BYTES)
        dest.write_bytes(content)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("sticker upload failed")
        raise HTTPException(500, f"Upload failed: {exc}")
    log.info("sticker upload: saved %s (%d bytes)", dest, len(content))

    # Same additive Storage mirror the intro/outro uploads do. It stays a no-op
    # until the `assets` table's type CHECK (migration 014) learns 'sticker' —
    # the helper never raises, so the response above is identical either way and
    # the sticker library itself is a disk scan, not a DB read.
    _storage_mirror_upload("sticker", dest, "stickers",
                           mimetypes.guess_type(dest.name)[0] or "image/png")

    return {"item": _sticker_from_file(dest)}


@router.post("/music/refetch")
def refetch_music(
    category: str = Query(default="hidden_gem", max_length=50),
    tags: list[str] | None = Query(default=None),
    avoid_id: str | None = Query(default=None, max_length=200),
):
    """
    Fetch a fresh track from Jamendo for the given category (skipping avoid_id).
    Returns the downloaded track so the frontend can select it before dispatching.
    """
    try:
        from backend.pipeline.music_fetcher import get_track_for_category
        avoid = [avoid_id] if avoid_id else None
        track_path = get_track_for_category(category, tags=tags, avoid_ids=avoid)
        if not track_path:
            raise HTTPException(404, f"No track available for category '{category}'")
        f = Path(track_path)
        rel = f.relative_to(MUSIC_DIR.parent)
        return {
            "track": {
                "id": f.stem,
                "title": f.stem.replace("_", " ").replace("-", " ").title(),
                "source": "local",
                "category": category,
                "url": f"/static/assets/{rel.as_posix()}",
            }
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("music refetch failed for category=%s", category)
        raise HTTPException(500, f"Refetch failed: {exc}")


# ── Unified assets index (v1.10.0) ───────────────────────────────────────────
# DB-backed CRUD + reconcile across all 5 types. Sits alongside (not
# replacing) the per-type routes above — MusicPicker.tsx/LutPicker.tsx keep
# calling GET /music and /luts unchanged; this surface backs the new Assets
# admin page.

class AssetPatch(BaseModel):
    name: str | None = None
    meta: dict | None = None
    favourite: bool | None = None
    tags: list[str] | None = None


@router.get("/all")
def list_all_assets(
    type: str | None = Query(default=None),
    favourite: bool | None = Query(default=None),
    tag: str | None = Query(default=None),
):
    """Unified listing from the `assets` table (DB = source of truth).
    Falls back to a lightweight per-type local-disk scan when Supabase isn't
    configured at all — dev environments without Supabase creds keep working.
    `favourite`/`tag` are additive filters (migration 015 columns);
    the local-disk fallback path ignores them (no per-type metadata there)."""
    if type and type not in ASSET_TYPES:
        raise HTTPException(400, f"Unknown asset type '{type}'. Allowed: {ASSET_TYPES}")
    from backend.db import _use_supabase
    if _use_supabase():
        rows = list_assets(type, favourite=favourite, tag=tag)
        return {"assets": [_asset_item_from_row(r) for r in rows]}
    return {"assets": _local_fallback_assets(type)}


@router.get("/all/{asset_id}")
def get_asset_route(asset_id: str):
    row = get_asset(asset_id)
    if not row:
        raise HTTPException(404, "Asset not found")
    return {"asset": _asset_item_from_row(row)}


@router.put("/all/{asset_id}")
def update_asset_route(asset_id: str, body: AssetPatch):
    if not get_asset(asset_id):
        raise HTTPException(404, "Asset not found")
    patch: dict = {}
    if body.name is not None:
        patch["name"] = body.name
    if body.meta is not None:
        patch["meta"] = body.meta
    if body.favourite is not None:
        patch["favourite"] = body.favourite
    if body.tags is not None:
        patch["tags"] = body.tags
    if not patch:
        raise HTTPException(400, "No fields to update — pass name/meta/favourite/tags")
    update_asset(asset_id, patch)
    return {"asset": _asset_item_from_row(get_asset(asset_id))}


@router.delete("/all/{asset_id}")
def delete_asset_route(asset_id: str):
    """Hard-delete the DB row + its Storage object (best-effort). Never
    touches the local file — matches the local-stays-authoritative invariant;
    removing a locally-served asset is a manual disk operation."""
    row = get_asset(asset_id)
    if not row:
        raise HTTPException(404, "Asset not found")
    if row.get("storage_path"):
        delete_object(row["storage_path"])
    delete_asset(asset_id)
    return {"ok": True, "id": asset_id}


@router.post("/sync")
def sync_assets(
    type: str | None = Query(default=None),
    confirm: bool = Query(default=False),
):
    """
    Two-step reconcile preview/confirm against local disk + the Storage
    bucket, mirroring /api/audio/refresh?confirm=.

    confirm=false (default): dry-run preview only — nothing written.
    confirm=true: executes the create/update/prune diff for real.
    """
    if type and type not in ASSET_TYPES:
        raise HTTPException(400, f"Unknown asset type '{type}'. Allowed: {ASSET_TYPES}")
    try:
        return reconcile(type, dry_run=not confirm)
    except Exception as exc:
        log.exception("assets sync failed (type=%s confirm=%s)", type, confirm)
        raise HTTPException(500, f"Sync failed: {exc}")
