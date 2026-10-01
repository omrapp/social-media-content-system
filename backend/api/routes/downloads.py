import asyncio
import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.config import (
    POSTS_DIR, HIGHLIGHTS_DIR, POSTS_MANIFEST, HIGHLIGHTS_MANIFEST,
    ORGANIZED_DIR, UPLOADS_DIR, IG_TOKEN, IG_USER_URL,
    PEXELS_API_KEY, PIXABAY_API_KEY,
)
from backend.db import get_setting
from backend.api.auth import verify_token
from backend.api.ws import broadcast, log_broadcast

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/downloads", tags=["downloads"], dependencies=[Depends(verify_token)])

# Upload defaults — used when the "uploads" settings group is missing keys.
_UPLOAD_DEFAULTS = {
    "max_mb": 500,
    "allowed_types": [".mp4", ".mov", ".m4v", ".webm"],
    "auto_probe": True,
    "url_fetch": True,
}


def _upload_cfg() -> dict:
    cfg = get_setting("uploads") or {}
    return {**_UPLOAD_DEFAULTS, **cfg}


def _sanitize_segment(value: str, fallback: str) -> str:
    """Strip path-traversal chars from a category/stem so it is safe as a path segment."""
    cleaned = re.sub(r"[/\\]", "", (value or "")).replace("..", "").strip()
    cleaned = cleaned.strip(". ")
    return cleaned[:60] or fallback


async def _stream_to_disk(file: UploadFile, dest: Path, max_bytes: int) -> int:
    """Stream an upload to disk in 1 MB chunks, rejecting at max_bytes.

    Writes chunks straight to the file instead of buffering the whole upload in
    RAM — matters at the raised 500 MB cap (buffering would peak ~1 GB/upload).
    Deletes the partial file and raises on overflow. Returns bytes written.
    """
    total = 0
    with open(dest, "wb") as fh:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds {max_bytes // (1024 * 1024)} MB limit")
            fh.write(chunk)
    return total


class DownloadRequest(BaseModel):
    highlight_name: str | None = None
    resume: bool = False


def _file_stats(directory: Path) -> dict:
    stats = {"video": 0, "image": 0, "other": 0, "total_size_mb": 0.0}
    if not directory.exists():
        return stats
    for f in directory.rglob("*"):
        if f.is_file():
            size_mb = f.stat().st_size / (1024 * 1024)
            stats["total_size_mb"] += size_mb
            ext = f.suffix.lower()
            if ext in (".mp4", ".mov", ".avi"):
                stats["video"] += 1
            elif ext in (".jpg", ".jpeg", ".png", ".webp"):
                stats["image"] += 1
            else:
                stats["other"] += 1
    stats["total_size_mb"] = round(stats["total_size_mb"], 1)
    return stats


def _load_manifest(path: Path) -> list:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _organized_breakdown() -> list:
    if not ORGANIZED_DIR.exists():
        return []
    categories = []
    for category_dir in sorted(ORGANIZED_DIR.iterdir()):
        if not category_dir.is_dir():
            continue
        # User uploads live at organized/uploads/ — keep them out of the IG funnel.
        if category_dir.name == "uploads":
            continue
        stats = _file_stats(category_dir)
        categories.append({
            "category": category_dir.name,
            "video": stats["video"],
            "image": stats["image"],
            "total_size_mb": stats["total_size_mb"],
        })
    return categories


def _highlight_breakdown() -> list:
    manifest = _load_manifest(HIGHLIGHTS_MANIFEST)
    highlights = {}
    for item in manifest:
        name = item.get("highlight_name", "unknown")
        if name not in highlights:
            highlights[name] = {"name": name, "count": 0, "last_downloaded": None}
        highlights[name]["count"] += 1
        ts = item.get("downloaded_at")
        if ts and (not highlights[name]["last_downloaded"] or ts > highlights[name]["last_downloaded"]):
            highlights[name]["last_downloaded"] = ts
    return list(highlights.values())


@router.get("/categories")
def download_categories():
    """Per-category pipeline funnel: count of media at each status stage."""
    from backend.db import get_supabase, _use_supabase, db_retry, query as sqlite_query
    FUNNEL = ["raw", "resized", "enhanced", "edited", "uploaded", "posted", "error"]

    if _use_supabase():
        try:
            rows = db_retry(lambda: get_supabase().table("media").select("category,status").execute().data or [])
        except Exception:
            rows = []
    else:
        rows = sqlite_query("SELECT category, status FROM media")

    # Aggregate: {category: {status: count, total: count}}
    agg: dict[str, dict] = {}
    for row in rows:
        category = (row.get("category") or "uncategorized").strip()
        status = row.get("status") or "raw"
        if category not in agg:
            agg[category] = {s: 0 for s in FUNNEL}
            agg[category]["total"] = 0
        agg[category][status if status in FUNNEL else "raw"] += 1
        agg[category]["total"] += 1

    result = [{"category": c, **counts} for c, counts in agg.items()]
    result.sort(key=lambda x: x["total"], reverse=True)
    return result


@router.get("/status")
def download_status():
    posts_manifest = _load_manifest(POSTS_MANIFEST)
    highlights_manifest = _load_manifest(HIGHLIGHTS_MANIFEST)
    return {
        "posts": {
            "downloaded": len(posts_manifest),
            "files": _file_stats(POSTS_DIR),
        },
        "highlights": {
            "downloaded": len(highlights_manifest),
            "files": _file_stats(HIGHLIGHTS_DIR),
            "breakdown": _highlight_breakdown(),
        },
        "organized": _organized_breakdown(),
        "uploads": _file_stats(UPLOADS_DIR),
    }


@router.get("/check-new")
async def check_new():
    if not IG_TOKEN:
        return {"error": "IG_TOKEN not configured", "new_posts": 0, "new_highlights": 0}

    import requests
    posts_manifest = _load_manifest(POSTS_MANIFEST)
    known_ids = {item["id"] for item in posts_manifest}

    resp = requests.get(
        f"{IG_USER_URL}/media",
        params={"access_token": IG_TOKEN, "fields": "id", "limit": 100},
    )
    if resp.status_code != 200:
        return {"error": "IG API error", "new_posts": 0}

    api_ids = {item["id"] for item in resp.json().get("data", [])}
    new_count = len(api_ids - known_ids)
    return {"new_posts": new_count, "total_on_ig": len(api_ids)}


@router.post("/posts")
async def trigger_post_download():
    from backend.pipeline.download_posts import run
    await broadcast("download_start", {"type": "posts"})
    await log_broadcast("log", "downloads", "Downloading posts…")
    try:
        result = run()
        await broadcast("download_complete", {"type": "posts", "result": result})
        await log_broadcast("success", "downloads", "Posts download complete", result)
        return result
    except Exception as e:
        await log_broadcast("error", "downloads", f"Posts download failed — {e}")
        raise


@router.post("/highlights")
async def trigger_highlight_download(body: DownloadRequest):
    from backend.pipeline.download_highlights import run
    label = body.highlight_name or "all"
    await broadcast("download_start", {"type": "highlights"})
    await log_broadcast("log", "downloads", f"Downloading highlights: {label}")
    try:
        result = run(highlight_filter=body.highlight_name)
        await broadcast("download_complete", {"type": "highlights", "result": result})
        await log_broadcast("success", "downloads", f"Highlights download complete: {label}", result)
        return result
    except Exception as e:
        await log_broadcast("error", "downloads", f"Highlights download failed — {e}")
        raise


def _dest_path(category: str, stem: str, ext: str) -> Path:
    """Build a safe, deduped destination under UPLOADS_DIR/<category>/ — id-based
    leaf (uuid6-suffixed filename), not nested by geography. Mirrors
    backend/pipeline/stock_footage.py::_dest_path."""
    safe_category = _sanitize_segment(category, "uncategorized")
    safe_stem = _sanitize_segment(stem, "clip")
    dest_dir = UPLOADS_DIR / safe_category
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / f"{safe_stem}_{uuid.uuid4().hex[:6]}{ext}"


def _finalize_upload(dest: Path, category: str, tags: list[str] | None = None) -> dict:
    """ffprobe-verify a saved file is a video, then insert a raw media row.

    On bad/non-video file: delete it and raise ValueError. Returns the inserted row.
    """
    from backend.pipeline.index_content import _ffprobe_video, insert_upload_row

    if _ffprobe_video(dest) is None:
        dest.unlink(missing_ok=True)
        raise ValueError("File is not a valid video (no readable video stream)")
    rel = str(dest.relative_to(ORGANIZED_DIR))
    return insert_upload_row(rel, category, tags)


@router.post("/upload")
async def upload_videos(
    files: list[UploadFile] = File(...),
    meta: str = Form(...),
):
    """Upload one or more local video files with per-file category/tags.

    `meta` is a JSON array aligned by index: [{category,tags}, ...].
    Each file is stream-saved under uploads/<category>/, ffprobe-verified,
    and indexed as a raw media row.
    """
    cfg = _upload_cfg()
    max_bytes = int(cfg["max_mb"]) * 1024 * 1024
    allowed = {e.lower() for e in cfg["allowed_types"]}

    try:
        meta_list = json.loads(meta)
        if not isinstance(meta_list, list):
            raise ValueError("meta must be a JSON array")
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, f"Invalid meta: {exc}")

    results = []
    saved = 0
    for i, file in enumerate(files):
        fname = file.filename or f"upload_{i}"
        m = meta_list[i] if i < len(meta_list) else {}
        category = (m or {}).get("category") or ""
        tags = (m or {}).get("tags") or None
        ext = Path(fname).suffix.lower()
        try:
            if ext not in allowed:
                raise ValueError(f"Unsupported type '{ext}'. Allowed: {', '.join(sorted(allowed))}")
            if not category:
                raise ValueError("category is required")
            dest = _dest_path(category, Path(fname).stem, ext)
            await _stream_to_disk(file, dest, max_bytes)
            row = _finalize_upload(dest, category, tags)
            results.append({"filename": fname, "ok": True, "id": row["id"], "local_path": row["local_path"]})
            saved += 1
        except HTTPException as exc:
            results.append({"filename": fname, "ok": False, "error": exc.detail})
        except Exception as exc:
            log.warning("upload failed for %s: %s", fname, exc)
            results.append({"filename": fname, "ok": False, "error": str(exc)})

    if saved:
        await broadcast("download_complete", {"type": "upload", "saved": saved})
        await log_broadcast("success", "downloads", f"Uploaded {saved} video(s)")
    return {"results": results, "saved": saved}


class UrlUploadRequest(BaseModel):
    url: str
    category: str
    tags: list[str] | None = None


@router.post("/upload-url")
async def upload_video_url(body: UrlUploadRequest):
    """Fetch a public Drive/Dropbox/direct video URL server-side, then index it."""
    cfg = _upload_cfg()
    if not cfg.get("url_fetch", True):
        raise HTTPException(403, "URL fetch is disabled (uploads.url_fetch=false)")
    if not body.category:
        raise HTTPException(400, "category is required")

    from urllib.parse import urlparse
    from backend.pipeline.upload_fetch import normalize_url, fetch_to_file, FetchError

    max_bytes = int(cfg["max_mb"]) * 1024 * 1024
    direct = normalize_url(body.url)
    # Drive/Dropbox links rarely carry a usable extension — default to .mp4.
    ext = Path(urlparse(direct).path).suffix.lower()
    if ext not in {e.lower() for e in cfg["allowed_types"]}:
        ext = ".mp4"
    dest = _dest_path(body.category, "url_clip", ext)
    try:
        fetch_to_file(direct, dest, max_bytes)
        row = _finalize_upload(dest, body.category, body.tags)
    except FetchError as exc:
        dest.unlink(missing_ok=True)
        result = {"filename": body.url, "ok": False, "error": str(exc)}
        return {"results": [result], "saved": 0}
    except Exception as exc:
        dest.unlink(missing_ok=True)
        log.warning("url upload failed for %s: %s", body.url, exc)
        result = {"filename": body.url, "ok": False, "error": str(exc)}
        return {"results": [result], "saved": 0}

    await broadcast("download_complete", {"type": "upload", "saved": 1})
    await log_broadcast("success", "downloads", "Fetched 1 video from URL")
    result = {"filename": body.url, "ok": True, "id": row["id"], "local_path": row["local_path"]}
    return {"results": [result], "saved": 1}


# ── Google Drive + Photos import (Phase 2) ───────────────────

def _ext_from_name(name: str, allowed: set[str]) -> str:
    """Pick a safe video extension from a remote filename; default .mp4."""
    ext = Path(name or "").suffix.lower()
    return ext if ext in allowed else ".mp4"


def _import_google_file(category: str, tags: list[str] | None, name: str,
                        downloader, allowed: set[str]) -> dict:
    """Shared: build dest, run `downloader(dest)`, ffprobe-verify, index a raw row.

    `downloader` is a callable taking the dest Path and writing the file to it.
    Returns a per-item result dict matching the upload route shape.
    """
    ext = _ext_from_name(name, allowed)
    dest = _dest_path(category, Path(name).stem or "google_clip", ext)
    try:
        downloader(dest)
        row = _finalize_upload(dest, category, tags)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        log.warning("google import failed for %s: %s", name, exc)
        return {"filename": name, "ok": False, "error": str(exc)}
    return {"filename": name, "ok": True, "id": row["id"], "local_path": row["local_path"]}


@router.get("/google/status")
def google_status():
    """Whether Google Drive/Photos import is configured (creds present in .env)."""
    from backend.pipeline.google_import import is_configured
    return {"configured": is_configured()}


@router.get("/google-drive/list")
def google_drive_list(q: str = "", page_token: str = ""):
    """List the owner's Google Drive video files."""
    from backend.pipeline.google_import import list_drive_videos, GoogleImportError
    try:
        return list_drive_videos(q, page_token)
    except GoogleImportError as exc:
        raise HTTPException(400, str(exc))


class DriveImportRequest(BaseModel):
    file_id: str
    name: str = "drive_clip"
    category: str
    tags: list[str] | None = None


@router.post("/google-drive/import")
async def google_drive_import(body: DriveImportRequest):
    """Download a chosen Drive file server-side and index it as raw media."""
    from backend.pipeline.google_import import download_drive_file, GoogleImportError
    if not body.category:
        raise HTTPException(400, "category is required")
    cfg = _upload_cfg()
    max_bytes = int(cfg["max_mb"]) * 1024 * 1024
    allowed = {e.lower() for e in cfg["allowed_types"]}

    try:
        # Offload the blocking network download + ffprobe off the event loop.
        result = await asyncio.to_thread(
            _import_google_file,
            body.category, body.tags, body.name,
            lambda dest: download_drive_file(body.file_id, dest, max_bytes), allowed,
        )
    except GoogleImportError as exc:
        raise HTTPException(400, str(exc))

    if result["ok"]:
        await broadcast("download_complete", {"type": "upload", "saved": 1})
        await log_broadcast("success", "downloads", "Imported 1 video from Google Drive")
    return {"results": [result], "saved": 1 if result["ok"] else 0}


@router.post("/google-photos/session")
def google_photos_session():
    """Create a Google Photos picking session — returns the picker URL to open."""
    from backend.pipeline.google_import import create_photos_session, GoogleImportError
    try:
        return create_photos_session()
    except GoogleImportError as exc:
        raise HTTPException(400, str(exc))


@router.get("/google-photos/session/{session_id}")
def google_photos_poll(session_id: str):
    """Poll a picking session — media_items_set flips true once the user finishes."""
    from backend.pipeline.google_import import get_photos_session, GoogleImportError
    try:
        return get_photos_session(session_id)
    except GoogleImportError as exc:
        raise HTTPException(400, str(exc))


class PhotosImportRequest(BaseModel):
    session_id: str
    category: str
    tags: list[str] | None = None


@router.post("/google-photos/import")
async def google_photos_import(body: PhotosImportRequest):
    """Download all video items the user picked in the session; index each as raw."""
    from backend.pipeline.google_import import (
        list_photos_picked, download_photos_item, GoogleImportError,
    )
    if not body.category:
        raise HTTPException(400, "category is required")
    cfg = _upload_cfg()
    max_bytes = int(cfg["max_mb"]) * 1024 * 1024
    allowed = {e.lower() for e in cfg["allowed_types"]}

    try:
        items = await asyncio.to_thread(list_photos_picked, body.session_id)
    except GoogleImportError as exc:
        raise HTTPException(400, str(exc))
    if not items:
        return {"results": [], "saved": 0, "error": "No videos picked in that session"}

    results = []
    saved = 0
    for it in items:
        # Offload the blocking download + ffprobe off the event loop, per item.
        result = await asyncio.to_thread(
            _import_google_file,
            body.category, body.tags, it["name"],
            lambda dest, _u=it["base_url"]: download_photos_item(_u, dest, max_bytes), allowed,
        )
        results.append(result)
        if result["ok"]:
            saved += 1

    if saved:
        await broadcast("download_complete", {"type": "upload", "saved": saved})
        await log_broadcast("success", "downloads", f"Imported {saved} video(s) from Google Photos")
    return {"results": results, "saved": saved}


# ── Stock B-roll sourcing (Phase A, 1.8.0) ───────────────────

def _stock_cfg() -> dict:
    from backend.pipeline.stock_footage import _settings
    return _settings()


def _require_stock_enabled():
    if not _stock_cfg().get("enabled"):
        raise HTTPException(400, "Enable stock.enabled in Settings first")


# Stock filenames are stored as "<provider>_<providerVideoId>_<uuid6>.<ext>"
# (see stock_footage._download_and_index). Parse the provider + id back out so we
# can dedupe re-imports and label the library without a new DB column.
_STOCK_NAME_RE = re.compile(r"^(pexels|pixabay)_([A-Za-z0-9]+)_[0-9a-f]{6}\.", re.IGNORECASE)


def _parse_stock_key(local_path: str) -> tuple[str, str] | None:
    m = _STOCK_NAME_RE.match(Path(local_path or "").name)
    if not m:
        return None
    return m.group(1).lower(), m.group(2)


def _stock_media_rows(cols: str) -> list[dict]:
    """Fetch source='stock' media rows (Supabase-first, SQLite fallback)."""
    from backend.db import get_supabase, _use_supabase, db_retry, query as sqlite_query
    if _use_supabase():
        try:
            return db_retry(lambda: get_supabase().table("media").select(cols)
                            .eq("source", "stock").execute().data or [])
        except Exception:
            return []
    return sqlite_query(f"SELECT {cols} FROM media WHERE source='stock'")


def _imported_stock_keys() -> set[str]:
    """Set of '<provider>:<id>' already imported — powers dedup on re-import."""
    keys: set[str] = set()
    for r in _stock_media_rows("local_path"):
        parsed = _parse_stock_key(r.get("local_path") or "")
        if parsed:
            keys.add(f"{parsed[0]}:{parsed[1]}")
    return keys


def _stock_library() -> dict:
    """Per-category breakdown of imported stock clips, with per-clip detail
    (provider, dimensions, duration, on-disk size, tags, import date) plus the
    flat imported-key list the search grid uses to mark already-imported clips."""
    rows = _stock_media_rows(
        "id,category,tags,status,local_path,width,height,duration_s,taken_at"
    )
    groups: dict[str, dict] = {}
    imported_keys: list[str] = []
    total_size = 0.0
    for r in rows:
        lp = r.get("local_path") or ""
        parsed = _parse_stock_key(lp)
        provider = parsed[0] if parsed else "unknown"
        provider_id = parsed[1] if parsed else ""
        if parsed:
            imported_keys.append(f"{provider}:{provider_id}")
        size_mb = 0.0
        try:
            p = ORGANIZED_DIR / lp
            if lp and p.exists():
                size_mb = round(p.stat().st_size / (1024 * 1024), 1)
        except Exception:
            pass
        total_size += size_mb
        category = ((r.get("category") or "").strip()) or "uncategorized"
        g = groups.setdefault(category, {"category": category, "count": 0, "total_size_mb": 0.0, "clips": []})
        g["count"] += 1
        g["total_size_mb"] = round(g["total_size_mb"] + size_mb, 1)
        g["clips"].append({
            "id": r.get("id"),
            "provider": provider,
            "provider_id": provider_id,
            "category": category,
            "tags": r.get("tags") or [],
            "status": r.get("status") or "raw",
            "width": r.get("width"),
            "height": r.get("height"),
            "duration_s": r.get("duration_s"),
            "size_mb": size_mb,
            "created_at": r.get("taken_at"),
        })
    categories = sorted(groups.values(), key=lambda x: x["count"], reverse=True)
    for g in categories:
        g["clips"].sort(key=lambda c: c.get("created_at") or "", reverse=True)
    return {
        "categories": categories,
        "total_clips": len(rows),
        "total_size_mb": round(total_size, 1),
        "imported_keys": imported_keys,
    }


@router.get("/stock/status")
def stock_status():
    """Whether at least one stock provider key is configured."""
    return {"configured": bool(PEXELS_API_KEY or PIXABAY_API_KEY)}


@router.get("/stock/library")
def stock_library():
    """Per-category imported-stock breakdown + dedup keys for the Stock UI."""
    return _stock_library()


@router.get("/stock/search")
async def stock_search(query: str = "", category: str = "", tags: list[str] = Query(default=[]), provider: str = ""):
    """Search-only preview — no download/index yet (mirrors /api/posts/select-preview)."""
    _require_stock_enabled()
    from backend.pipeline.stock_footage import search_stock
    try:
        candidates = await asyncio.to_thread(
            search_stock,
            category=category, tags=tags or None,
            query=query or None, source=provider or None,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return {"results": candidates}


class StockImportRequest(BaseModel):
    id: str
    provider: str
    category: str
    tags: list[str] | None = None


@router.post("/stock/import")
async def stock_import(body: StockImportRequest):
    """Download + index exactly one previously-searched candidate."""
    _require_stock_enabled()
    if not body.category:
        raise HTTPException(400, "category is required")

    # Server-side dedup: never download the same provider clip twice.
    key = f"{(body.provider or '').lower()}:{body.id}"
    if key in _imported_stock_keys():
        return {
            "results": [{"filename": f"{body.provider}:{body.id}", "ok": False,
                         "error": "Already imported", "duplicate": True}],
            "saved": 0, "duplicate": True,
        }

    from backend.pipeline.stock_footage import import_stock_clip

    try:
        row = await asyncio.to_thread(
            import_stock_clip, body.id, body.provider, body.category, body.tags,
        )
    except Exception as exc:
        return {"results": [{"filename": f"{body.provider}:{body.id}", "ok": False, "error": str(exc)}], "saved": 0}

    await broadcast("download_complete", {"type": "upload", "saved": 1})
    await log_broadcast("success", "downloads", f"Imported 1 stock video ({body.provider})")
    result = {"filename": f"{body.provider}:{body.id}", "ok": True, "id": row["id"], "local_path": row["local_path"]}
    return {"results": [result], "saved": 1}


@router.delete("/stock/{media_id}")
async def stock_delete(media_id: str):
    """Hard-delete one imported stock clip — remove the file from disk AND the
    media row so the storage is reclaimed. Only source='stock' rows are eligible
    (a guard against deleting archive footage through this route)."""
    from backend.db import get_media_by_id, delete_media_row

    row = get_media_by_id(media_id)
    if not row or row.get("source") != "stock":
        raise HTTPException(404, "Stock clip not found")

    lp = row.get("local_path") or ""
    if lp:
        try:
            (ORGANIZED_DIR / lp).unlink(missing_ok=True)
        except Exception as exc:
            log.warning("stock delete: file unlink failed for %s: %s", media_id, exc)

    delete_media_row(media_id)
    await broadcast("download_complete", {"type": "stock_delete", "id": media_id})
    await log_broadcast("success", "downloads", "Deleted 1 stock video")
    return {"ok": True, "id": media_id}


@router.post("/resume")
async def resume_download():
    from backend.pipeline.download_posts import run as run_posts
    from backend.pipeline.download_highlights import run as run_highlights
    await broadcast("download_start", {"type": "resume"})
    await log_broadcast("log", "downloads", "Resuming all downloads…")
    try:
        posts_result = run_posts()
        highlights_result = run_highlights()
        await broadcast("download_complete", {"type": "resume"})
        await log_broadcast("success", "downloads", "Resume complete", {
            "posts": posts_result,
            "highlights": highlights_result,
        })
        return {"posts": posts_result, "highlights": highlights_result}
    except Exception as e:
        await log_broadcast("error", "downloads", f"Resume failed — {e}")
        raise
