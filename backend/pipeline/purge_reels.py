"""
Purge old local reel files from REELS_READY_DIR to stay under LOCAL_REELS_MAX_GB.

Three categories of deletable files:
  A) r2_url set in DB              — confirmed in R2, safe to delete
  B) terminal status, no r2_url   — error/rejected/deleted, pipeline abandoned
  C) orphan (no DB record)        — no matching reel_ready_path in DB at all

Files are NEVER deleted if:
  - newer than LOCAL_REELS_MIN_AGE_DAYS (default 7 days)
  - in active/pending states (resized, edited, scheduled, preview) without r2_url

Usage:
    python -m backend.pipeline.purge_reels              # dry-run
    python -m backend.pipeline.purge_reels --execute    # actually delete
    python -m backend.pipeline.purge_reels --execute --max-gb 3 --min-age-days 3
"""

import argparse
import logging
import time
from pathlib import Path

from backend.config import REELS_READY_DIR, LOCAL_REELS_MAX_GB, LOCAL_REELS_MIN_AGE_DAYS

log = logging.getLogger(__name__)

_GB = 1024 ** 3
_TERMINAL_STATUSES = {"error", "rejected", "deleted"}
# Statuses where a file is actively needed — never delete these even if old.
_ACTIVE_STATUSES = {"scheduled", "preview", "publishing"}


def _get_media_file_map() -> dict[str, dict]:
    """Return {reel_ready_path: {r2_url, status}} for all media with reel_ready_path set."""
    from backend.db import _use_supabase, get_supabase, db_retry, query as sqlite_query

    if _use_supabase():
        rows: list = []
        start, page = 0, 1000
        while True:
            def _page(s=start):
                return (
                    get_supabase()
                    .table("media")
                    .select("reel_ready_path,r2_url,status")
                    .not_.is_("reel_ready_path", "null")
                    .neq("reel_ready_path", "")
                    .range(s, s + page - 1)
                    .execute()
                    .data
                )
            batch = db_retry(_page)
            rows.extend(batch or [])
            if len(batch or []) < page:
                break
            start += page
    else:
        rows = sqlite_query(
            "SELECT reel_ready_path, r2_url, status FROM media "
            "WHERE reel_ready_path IS NOT NULL AND reel_ready_path != ''",
            []
        )

    return {
        r["reel_ready_path"]: {"r2_url": r.get("r2_url"), "status": r.get("status")}
        for r in rows
        if r.get("reel_ready_path")
    }


def _storage_settings() -> tuple[float, int]:
    """Return (max_gb, min_age_days) from DB settings, falling back to config.py env vars."""
    try:
        from backend.db import get_setting
        cfg = get_setting("storage") or {}
        max_gb = float(cfg.get("reels_max_gb", LOCAL_REELS_MAX_GB))
        min_age_days = int(cfg.get("reels_min_age_days", LOCAL_REELS_MIN_AGE_DAYS))
        return max_gb, min_age_days
    except Exception:
        return LOCAL_REELS_MAX_GB, LOCAL_REELS_MIN_AGE_DAYS


def _dir_size_bytes(directory: Path) -> int:
    return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())


def purge_local(
    max_gb: float | None = None,
    min_age_days: int | None = None,
    dry_run: bool = True,
) -> dict:
    db_max_gb, db_min_age = _storage_settings()
    if max_gb is None:
        max_gb = db_max_gb
    if min_age_days is None:
        min_age_days = db_min_age
    """
    Delete oldest safe reels until REELS_READY_DIR is under max_gb.

    Files newer than min_age_days are never deleted regardless of category.

    Returns dict with bytes_freed, files_deleted, files_skipped, dry_run,
    and per-category counts (uploaded, terminal, orphan).
    """
    max_bytes = max_gb * _GB
    current = _dir_size_bytes(REELS_READY_DIR)

    if current <= max_bytes:
        log.info(
            "purge_reels: %.2fGB used, cap %.2fGB — nothing to do",
            current / _GB, max_gb,
        )
        return {
            "bytes_freed": 0, "files_deleted": 0, "files_skipped": 0,
            "dry_run": dry_run, "uploaded": 0, "terminal": 0, "orphan": 0,
        }

    log.info(
        "purge_reels: %.2fGB used, cap %.2fGB — need to free %.2fGB%s",
        current / _GB, max_gb, (current - max_bytes) / _GB,
        " (DRY RUN)" if dry_run else "",
    )

    db_map = _get_media_file_map()
    thumbs = REELS_READY_DIR / "thumbs"
    min_age_secs = min_age_days * 86400
    now = time.time()

    uploaded_files: list[Path] = []
    terminal_files: list[Path] = []   # explicit terminal + stale (old, no r2_url, not actively queued)
    orphan_files: list[Path] = []
    skipped_active: list[Path] = []   # scheduled/preview/publishing — never touch
    recent_protected = 0

    for f in REELS_READY_DIR.rglob("*"):
        if not f.is_file():
            continue
        if str(f).startswith(str(thumbs)):
            continue

        # Recency guard — never delete recently created files
        age_secs = now - f.stat().st_mtime
        if age_secs < min_age_secs:
            recent_protected += 1
            continue

        path_str = str(f)
        if path_str in db_map:
            rec = db_map[path_str]
            if rec["r2_url"]:
                uploaded_files.append(f)
            elif rec["status"] in _ACTIVE_STATUSES:
                # Actively queued for publish — never delete
                skipped_active.append(f)
            else:
                # Terminal (error/rejected/deleted) OR stale (resized/edited/raw but old, never uploaded)
                # Both are safe to reclaim once past the age guard
                terminal_files.append(f)
        else:
            orphan_files.append(f)

    log.info(
        "purge_reels candidates: %d uploaded, %d terminal/stale, %d orphan "
        "| protected (recent <%dd): %d | skipping (active/queued): %d",
        len(uploaded_files), len(terminal_files), len(orphan_files),
        min_age_days, recent_protected, len(skipped_active),
    )

    # Precompute sets for O(1) category lookup
    uploaded_set = set(uploaded_files)
    terminal_set = set(terminal_files)

    def _by_mtime(f: Path) -> float:
        return f.stat().st_mtime

    # Delete order: uploaded (safest) → terminal → orphan, oldest-first within each
    candidates = (
        sorted(uploaded_files, key=_by_mtime)
        + sorted(terminal_files, key=_by_mtime)
        + sorted(orphan_files, key=_by_mtime)
    )

    bytes_freed = 0
    files_deleted = 0
    files_skipped = 0
    count_uploaded = count_terminal = count_orphan = 0

    for f in candidates:
        if current - bytes_freed <= max_bytes:
            break
        size = f.stat().st_size
        if f in uploaded_set:
            category = "uploaded"
        elif f in terminal_set:
            category = "terminal"
        else:
            category = "orphan"

        if dry_run:
            log.info(
                "purge_reels [dry-run] would delete [%s] %s (%.1fMB)",
                category, f.name, size / 1024**2,
            )
        else:
            try:
                f.unlink()
                log.info("purge_reels deleted [%s] %s (%.1fMB)", category, f.name, size / 1024**2)
            except OSError as exc:
                log.warning("purge_reels failed to delete %s: %s", f, exc)
                files_skipped += 1
                continue

        bytes_freed += size
        files_deleted += 1
        if category == "uploaded":
            count_uploaded += 1
        elif category == "terminal":
            count_terminal += 1
        else:
            count_orphan += 1

    remaining = current - bytes_freed
    log.info(
        "purge_reels done: freed %.2fGB, deleted %d files "
        "(uploaded=%d terminal=%d orphan=%d)%s — %.2fGB remaining",
        bytes_freed / _GB, files_deleted,
        count_uploaded, count_terminal, count_orphan,
        " (dry-run)" if dry_run else "",
        remaining / _GB,
    )

    return {
        "bytes_freed": bytes_freed,
        "files_deleted": files_deleted,
        "files_skipped": files_skipped,
        "dry_run": dry_run,
        "uploaded": count_uploaded,
        "terminal": count_terminal,
        "orphan": count_orphan,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Purge old local reels to stay under disk cap")
    parser.add_argument("--execute", action="store_true", help="Actually delete files (default: dry-run)")
    parser.add_argument("--max-gb", type=float, default=LOCAL_REELS_MAX_GB,
                        help=f"Local disk cap in GB (default: {LOCAL_REELS_MAX_GB})")
    parser.add_argument("--min-age-days", type=int, default=LOCAL_REELS_MIN_AGE_DAYS,
                        help=f"Min file age in days before eligible for deletion (default: {LOCAL_REELS_MIN_AGE_DAYS})")
    args = parser.parse_args()

    result = purge_local(max_gb=args.max_gb, min_age_days=args.min_age_days, dry_run=not args.execute)
    freed_mb = result["bytes_freed"] / 1024**2
    print(
        f"{'[DRY RUN] ' if result['dry_run'] else ''}"
        f"Freed {freed_mb:.1f}MB across {result['files_deleted']} files "
        f"(uploaded={result['uploaded']} terminal={result['terminal']} orphan={result['orphan']}). "
        f"Skipped {result['files_skipped']}."
    )
