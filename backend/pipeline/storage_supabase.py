"""
Supabase Storage client wrapper for the `assets` bucket (music/font/lut/intro/
outro public URLs). Shaped after upload_r2.py's get_r2_client()/upload_file()/
public_url() pattern, but rides db.py's already-constructed Supabase client
(get_supabase()) instead of building a second client — Storage calls share the
same service-role session used for Postgres writes elsewhere in this codebase.

Bucket is public-read by design (see migration 014_assets_table.sql header) —
non-sensitive branding/music/LUT assets, not user data. Service-role key only
(SUPABASE_SERVICE_KEY); never exposed to frontend.

Every function here degrades gracefully (empty list / no-op) when Storage is
unconfigured or a call fails — reconcile and the upload routes must never 500
just because the bucket isn't set up yet.
"""

import logging

from backend.config import SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_STORAGE_BUCKET
from backend.db import get_supabase, db_retry

log = logging.getLogger(__name__)


def storage_configured() -> bool:
    """True when Supabase Storage can be used server-side (service-role key set).
    Storage writes require the service-role key (bypasses bucket RLS), unlike
    _use_supabase() in db.py which only requires the anon key for table reads."""
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def _bucket():
    return get_supabase().storage.from_(SUPABASE_STORAGE_BUCKET)


def public_url(storage_path: str) -> str:
    return _bucket().get_public_url(storage_path)


def list_bucket_objects(prefix: str = "") -> list[dict]:
    """
    List every file object in the bucket under *prefix*, recursing into
    subfolders — Supabase Storage's `.list()` is single-level per call; folder
    placeholders come back with `metadata=None` and no real file id.

    Returns [{"storage_path", "public_url", "size_bytes", "checksum",
    "updated_at"}, ...]. Returns [] (never raises) when Storage is unconfigured
    or the call fails, so reconcile can always fall back to local-only.
    """
    if not storage_configured():
        return []
    out: list[dict] = []
    try:
        _list_recursive(prefix, out)
    except Exception as exc:
        log.warning("storage_supabase: list_bucket_objects failed (prefix=%r): %s", prefix, exc)
        return []
    return out


def _list_recursive(prefix: str, out: list[dict]) -> None:
    entries = db_retry(lambda: _bucket().list(prefix or None)) or []
    for entry in entries:
        name = entry.get("name")
        if not name:
            continue
        path = f"{prefix.rstrip('/')}/{name}" if prefix else name
        metadata = entry.get("metadata")
        if metadata is None:
            # Folder placeholder (no metadata) — recurse one level deeper.
            _list_recursive(path, out)
            continue
        checksum = (metadata.get("eTag") or "").strip('"') or None
        out.append({
            "storage_path": path,
            "public_url": public_url(path),
            "size_bytes": metadata.get("size"),
            "checksum": checksum,
            "updated_at": entry.get("updated_at"),
        })


def upload_file(local_path: str, storage_path: str, content_type: str = "application/octet-stream") -> str:
    """
    Upload *local_path* to *storage_path* inside the bucket (upsert), returning
    its public URL. Raises on failure — callers decide whether to surface the
    error or swallow it as best-effort (upload routes/trim_track do the latter).
    """
    with open(local_path, "rb") as fh:
        data = fh.read()
    db_retry(lambda: _bucket().upload(
        storage_path, data,
        file_options={"content-type": content_type, "upsert": "true"},
    ))
    return public_url(storage_path)


def delete_object(storage_path: str) -> None:
    """Best-effort delete of one Storage object. Never raises — the DB-row
    delete is the primary operation, Storage cleanup is secondary."""
    if not storage_configured() or not storage_path:
        return
    try:
        db_retry(lambda: _bucket().remove([storage_path]))
    except Exception as exc:
        log.warning("storage_supabase: delete_object failed for %r: %s", storage_path, exc)
