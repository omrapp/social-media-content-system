"""
Reconcile the `assets` table (Supabase) against the two real sources of truth:
local disk (per-type dir under assets/) and the Supabase Storage bucket.

Mirrors music_fetcher.discover_new_files()'s dry-run/orphan-prune shape, but
widened to merge THREE sources — Storage bucket listing, local dir listing,
and existing `assets` DB rows — instead of two (local dir vs cache.json).

Critical invariant: reconcile NEVER deletes a local file, and NEVER prunes a
DB row that's missing from only ONE of {local disk, Storage bucket} — only
when missing from BOTH. Local disk stays what the FFmpeg pipeline
(merge_clips.py, video_edit.py, screens.py, lut_select.py) reads directly.

Bucket-listing safety: when the bucket is unconfigured, or a listing call for
a type comes back empty while the DB already has storage-backed rows for that
type (a strong signal the listing silently failed rather than the bucket
truly being empty), bucket state for that type is treated as UNKNOWN rather
than "confirmed absent" — existing storage_path/public_url data is left
untouched and no row is pruned on the strength of that read alone. This is
what makes the "never prune on partial/uncertain absence" invariant hold up
even when Storage is flaky, not just when it's cleanly unreachable.

Usage:
    python -m backend.pipeline.assets_index --type music           # dry-run preview
    python -m backend.pipeline.assets_index --type music --confirm  # write changes
"""

import argparse
import hashlib
import json
import logging
import uuid
from pathlib import Path

from backend.config import ASSETS_DIR, MUSIC_DIR, FONTS_DIR, LUTS_DIR, INTRO_DIR, OUTRO_DIR
from backend.db import list_assets, create_asset, update_asset, delete_asset
from backend.pipeline.storage_supabase import list_bucket_objects, storage_configured

log = logging.getLogger(__name__)

ASSET_TYPES = ("music", "font", "lut", "intro", "outro")

# type → (local dir(s) to rglob, allowed extensions, expected Storage-bucket
# prefix). Bucket layout mirrors the local folder basenames one-to-one so a
# manual bulk-upload can just recreate the same tree under the bucket root
# (e.g. bucket:/luts/cinematic/foo.cube for the curated LUT set — rglob on
# LUTS_DIR already walks into cinematic/ locally, same shape).
_TYPE_CONFIG = {
    "music": {"dirs": [MUSIC_DIR / "packs"], "exts": (".mp3", ".m4a", ".wav", ".aac", ".ogg"), "prefix": "music"},
    "font":  {"dirs": [FONTS_DIR], "exts": (".ttf", ".otf"), "prefix": "fonts"},
    "lut":   {"dirs": [LUTS_DIR], "exts": (".cube",), "prefix": "luts"},
    "intro": {"dirs": [INTRO_DIR], "exts": (".mp4", ".mov", ".m4v", ".jpg", ".jpeg", ".png"), "prefix": "intros"},
    "outro": {"dirs": [OUTRO_DIR], "exts": (".mp4", ".mov", ".m4v", ".jpg", ".jpeg", ".png"), "prefix": "outros"},
}


def _display_name(stem: str) -> str:
    return stem.replace("_", " ").replace("-", " ").title()


def _checksum(path: Path) -> str | None:
    try:
        h = hashlib.md5()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _scan_local(asset_type: str) -> dict[str, Path]:
    """{filename: local_path} for every matching file under the type's dir(s)."""
    cfg = _TYPE_CONFIG[asset_type]
    out: dict[str, Path] = {}
    for d in cfg["dirs"]:
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.suffix.lower() in cfg["exts"]:
                out.setdefault(f.name, f)
    return out


def reconcile(type: str | None = None, dry_run: bool = True) -> dict:
    """
    Diff local disk + Storage bucket + DB `assets` rows for one type (or every
    type in ASSET_TYPES when `type` is None), returning a preview of what
    would change.

    dry_run=True (default): compute the diff only, write nothing.
    dry_run=False: create/update/prune rows for real.

    Returns {"added": [...], "removed": [...], "updated": [...],
             "added_count", "removed_count", "updated_count"} — same
    preview/confirm shape as music_fetcher.discover_new_files() /
    /api/audio/refresh.
    """
    types = [type] if type else list(ASSET_TYPES)
    added: list[dict] = []
    removed: list[dict] = []
    updated: list[dict] = []

    for t in types:
        if t not in _TYPE_CONFIG:
            continue
        _reconcile_type(t, dry_run, added, removed, updated)

    return {
        "added": added, "removed": removed, "updated": updated,
        "added_count": len(added), "removed_count": len(removed), "updated_count": len(updated),
    }


def _reconcile_type(asset_type: str, dry_run: bool, added: list, removed: list, updated: list) -> None:
    cfg = _TYPE_CONFIG[asset_type]

    local_files = _scan_local(asset_type)  # {filename: Path}

    bucket_objects_raw = list_bucket_objects(cfg["prefix"])  # [] on unconfigured/failed — never raises
    # Storage lists every object under the prefix verbatim — including non-media
    # files a bulk upload can drag along (assets/luts/catalog.json,
    # assets/music/cache.json, Storage's own ".emptyFolderPlaceholder" marker
    # files). Filter to the same allowed extensions _scan_local() uses so these
    # never get indexed as a fake asset row.
    bucket_objects = [
        o for o in bucket_objects_raw
        if Path(o["storage_path"]).suffix.lower() in cfg["exts"]
    ]
    bucket_by_filename = {Path(o["storage_path"]).name: o for o in bucket_objects}

    db_rows = list_assets(asset_type)
    db_by_filename = {r["filename"]: r for r in db_rows if r.get("filename")}

    # Bucket data is "trustworthy" (safe to treat a miss as confirmed absence)
    # only when Storage is actually configured in THIS process AND either we
    # got real objects back or there were no storage-backed rows to lose in
    # the first place. An unconfigured/unreachable Storage client must never
    # be trusted to confirm absence — otherwise a dev/staging process with no
    # SUPABASE_SERVICE_KEY (but still _use_supabase()=True via the anon key,
    # e.g. pointed at a shared prod DB) would prune every storage-only row on
    # its very first sync, since it can never list the bucket to prove
    # otherwise. Rows with no storage_path to begin with have nothing to lose,
    # so they still resolve to "absent" further below regardless.
    has_storage_rows = any(r.get("storage_path") for r in db_rows)
    bucket_trustworthy = storage_configured() and (bool(bucket_objects) or not has_storage_rows)

    all_filenames = set(local_files) | set(bucket_by_filename) | set(db_by_filename)

    for filename in sorted(all_filenames):
        local_path = local_files.get(filename)
        bucket_obj = bucket_by_filename.get(filename)
        db_row = db_by_filename.get(filename)

        on_local = local_path is not None
        if bucket_obj is not None:
            bucket_status = "present"
        elif bucket_trustworthy:
            bucket_status = "absent"
        elif db_row and db_row.get("storage_path"):
            bucket_status = "unknown"  # unreliable listing this run — don't assume removal
        else:
            bucket_status = "absent"  # never had a storage_path anyway, nothing to lose

        if db_row is None:
            if not on_local and bucket_status != "present":
                continue  # nothing to index
            checksum = bucket_obj["checksum"] if bucket_obj else (_checksum(local_path) if local_path else None)
            # Content-hash dedupe: skip creating a duplicate row for a file
            # that's byte-identical to one already indexed under another name.
            if checksum and any(r.get("checksum") == checksum for r in db_rows):
                continue
            size_bytes = (bucket_obj.get("size_bytes") if bucket_obj else None) or (
                local_path.stat().st_size if local_path else None
            )
            row = {
                "id": f"{asset_type}_{uuid.uuid4().hex[:12]}",
                "type": asset_type,
                "name": _display_name(Path(filename).stem),
                "filename": filename,
                "storage_path": bucket_obj["storage_path"] if bucket_obj else None,
                "public_url": bucket_obj["public_url"] if bucket_obj else None,
                "local_path": str(local_path.relative_to(ASSETS_DIR)) if local_path else None,
                "size_bytes": size_bytes,
                "checksum": checksum,
                "meta": {},
            }
            added.append(row)
            if not dry_run:
                create_asset(row)
            continue

        # Existing row — prune only when confirmed missing from BOTH sides.
        if not on_local and bucket_status == "absent":
            removed.append({"id": db_row["id"], "filename": filename})
            if not dry_run:
                delete_asset(db_row["id"])
            continue
        if not on_local and bucket_status == "unknown":
            continue  # can't confirm bucket-side removal this run — leave untouched

        # Present on at least one (confirmed) side — refresh drifted fields.
        # Storage-derived fields are only touched when this run's bucket read
        # is trustworthy for this filename (bucket_status != "unknown").
        new_local_path = str(local_path.relative_to(ASSETS_DIR)) if local_path else None
        patch: dict = {}
        if db_row.get("local_path") != new_local_path:
            patch["local_path"] = new_local_path

        if bucket_status != "unknown":
            new_storage_path = bucket_obj["storage_path"] if bucket_obj else None
            new_public_url = bucket_obj["public_url"] if bucket_obj else None
            if db_row.get("storage_path") != new_storage_path:
                patch["storage_path"] = new_storage_path
            if db_row.get("public_url") != new_public_url:
                patch["public_url"] = new_public_url

        if bucket_obj:
            if bucket_obj.get("size_bytes") and db_row.get("size_bytes") != bucket_obj["size_bytes"]:
                patch["size_bytes"] = bucket_obj["size_bytes"]
            if bucket_obj.get("checksum") and db_row.get("checksum") != bucket_obj["checksum"]:
                patch["checksum"] = bucket_obj["checksum"]
        elif on_local and not db_row.get("checksum"):
            cs = _checksum(local_path)
            if cs:
                patch["checksum"] = cs
            if not db_row.get("size_bytes"):
                patch["size_bytes"] = local_path.stat().st_size

        if patch:
            updated.append({"id": db_row["id"], "filename": filename, "patch": patch})
            if not dry_run:
                update_asset(db_row["id"], patch)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default=None, choices=list(ASSET_TYPES))
    parser.add_argument("--confirm", action="store_true", help="Write changes (default is dry-run preview)")
    args = parser.parse_args()
    result = reconcile(args.type, dry_run=not args.confirm)
    print(json.dumps(result, indent=2, default=str))
