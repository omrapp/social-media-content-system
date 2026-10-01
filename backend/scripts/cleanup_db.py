"""
cleanup_db — reset error/stuck DB records to their correct states.

What it does:
  1. media status='error' → recompute real state:
       r2_url set                       → uploaded
       reel_ready_path exists on disk   → resized
       otherwise                        → raw
  2. posts status='publishing', published_at IS NULL → preview
     (daemon will re-attempt on next tick)
  3. posts whose media has status='deleted' → hard-deleted from posts table
     (media deleted = post can never publish)

Usage:
  python -m backend.scripts.cleanup_db            # dry-run (default, safe)
  python -m backend.scripts.cleanup_db --apply    # execute changes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a module from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.db import _use_supabase, get_supabase, get_media, update_status, update_post


# ── Helpers ──────────────────────────────────────────────────────────────────

def _infer_media_status(row: dict) -> str:
    """Best-guess real status for an error row based on available fields."""
    if row.get("r2_url"):
        return "uploaded"
    reel_path = row.get("reel_ready_path") or ""
    if reel_path and Path(reel_path).exists():
        return "resized"
    return "raw"


def _fetch_all(table: str, filters: dict | None = None, select: str = "*") -> list[dict]:
    """Page through Supabase results (PostgREST caps at 1000/request)."""
    sb = get_supabase()
    PAGE = 1000
    results: list[dict] = []
    offset = 0
    while True:
        q = sb.table(table).select(select)
        if filters:
            for k, v in filters.items():
                q = q.eq(k, v)
        batch = q.range(offset, offset + PAGE - 1).execute().data or []
        results.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return results


def _fetch_posts_stuck_publishing() -> list[dict]:
    return (
        get_supabase()
        .table("posts")
        .select("id,media_id,status,published_at")
        .eq("status", "publishing")
        .is_("published_at", "null")
        .execute()
        .data or []
    )


def _fetch_deleted_media_ids() -> list[str]:
    rows = _fetch_all("media", filters={"status": "deleted"}, select="id")
    return [r["id"] for r in rows]


def _fetch_posts_for_media_ids(media_ids: list[str]) -> list[dict]:
    if not media_ids:
        return []
    return (
        get_supabase()
        .table("posts")
        .select("id,media_id,status")
        .in_("media_id", media_ids)
        .execute()
        .data or []
    )


# ── Cleanup tasks ─────────────────────────────────────────────────────────────

def fix_error_media(apply: bool) -> dict:
    """Reset media rows stuck in status='error' to their real state."""
    rows = _fetch_all("media", filters={"status": "error"})
    if not rows:
        return {"total": 0}

    buckets: dict[str, list[str]] = {"uploaded": [], "resized": [], "raw": []}
    for row in rows:
        target = _infer_media_status(row)
        buckets[target].append(row["id"])

    total = len(rows)
    print(f"\n[media errors] {total} rows with status='error'")
    for target, ids in buckets.items():
        if ids:
            print(f"  → reset to '{target}': {len(ids)}")

    if apply and total:
        sb = get_supabase()
        for target, ids in buckets.items():
            if ids:
                for mid in ids:
                    sb.table("media").update({"status": target, "error_message": None}).eq("id", mid).execute()
        print("  ✓ applied")

    return {"total": total, **{f"reset_to_{k}": len(v) for k, v in buckets.items()}}


def fix_stuck_publishing(apply: bool) -> dict:
    """Reset posts stuck in 'publishing' with no published_at back to 'preview'."""
    rows = _fetch_posts_stuck_publishing()
    count = len(rows)
    print(f"\n[stuck posts] {count} posts stuck in 'publishing' with no published_at")

    if apply and count:
        for row in rows:
            update_post(row["id"], {"status": "preview"})
        print("  ✓ reset to 'preview'")

    return {"stuck_publishing_reset": count}


def delete_orphaned_posts(apply: bool) -> dict:
    """Delete posts whose media has been soft-deleted."""
    deleted_media_ids = _fetch_deleted_media_ids()
    if not deleted_media_ids:
        print("\n[orphaned posts] no deleted media found")
        return {"orphaned_posts_deleted": 0}

    posts = _fetch_posts_for_media_ids(deleted_media_ids)
    count = len(posts)
    print(f"\n[orphaned posts] {count} posts reference deleted media")

    if apply and count:
        sb = get_supabase()
        for post in posts:
            sb.table("posts").delete().eq("id", post["id"]).execute()
        print("  ✓ deleted")

    return {"orphaned_posts_deleted": count}


def purge_deleted_media(apply: bool) -> dict:
    """Hard-delete media rows where status='deleted' (R2 objects already removed at soft-delete time)."""
    rows = _fetch_all("media", filters={"status": "deleted"}, select="id")
    count = len(rows)
    print(f"\n[purge deleted media] {count} rows with status='deleted'")

    if not apply:
        print("  (dry-run) would hard-delete these rows from media table")
        return {"purge_deleted_media": count}

    if count > 0:
        sb = get_supabase()
        for row in rows:
            sb.table("media").delete().eq("id", row["id"]).execute()
        print(f"  ✓ deleted {count} rows")

    return {"purge_deleted_media": count}


# ── Entry point ───────────────────────────────────────────────────────────────

def run(apply: bool = False, purge_deleted: bool = False) -> dict:
    if not _use_supabase():
        print("ERROR: Supabase not configured. Set SUPABASE_URL + SUPABASE_SERVICE_KEY.")
        sys.exit(1)

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"=== cleanup_db [{mode}] ===")
    if not apply:
        print("Pass --apply to execute changes.\n")

    results = {}
    if purge_deleted:
        results.update(purge_deleted_media(apply))
    else:
        results.update(fix_error_media(apply))
        results.update(fix_stuck_publishing(apply))
        results.update(delete_orphaned_posts(apply))

    print(f"\n=== done ===")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset error/stuck DB records.")
    parser.add_argument("--apply", action="store_true",
                        help="Execute changes (default is dry-run).")
    parser.add_argument("--purge-deleted", action="store_true",
                        help="Hard-delete media rows with status='deleted'. R2 objects already removed. Run dry-run first.")
    args = parser.parse_args()
    run(apply=args.apply, purge_deleted=args.purge_deleted)
