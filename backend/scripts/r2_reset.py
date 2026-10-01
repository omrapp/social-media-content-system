"""
r2_reset — audit or wipe all objects in the Cloudflare R2 bucket.

Usage:
  python -m backend.scripts.r2_reset --audit    # inspect bucket vs DB (safe)
  python -m backend.scripts.r2_reset --wipe     # delete all objects + reset DB fields

--wipe resets:
  - Deletes every object in the R2 bucket
  - Clears r2_url / r2_key / thumbnail_url on all media rows
  - Reverts media status='uploaded' → 'resized'
  This leaves the DB ready for fresh uploads via the create flow.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import R2_ENDPOINT, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET, R2_PUBLIC_URL
from backend.db import _use_supabase, get_supabase
from backend.pipeline.upload_r2 import get_r2_client


# ── Helpers ──────────────────────────────────────────────────────────────────

def _list_all_objects(client) -> list[dict]:
    """Return all objects in bucket with Key + Size."""
    paginator = client.get_paginator("list_objects_v2")
    objects = []
    for page in paginator.paginate(Bucket=R2_BUCKET):
        objects.extend(page.get("Contents", []))
    return objects


def _fetch_all_media_with_r2(sb) -> list[dict]:
    """Fetch all media rows that have an r2_key set."""
    PAGE = 1000
    results = []
    offset = 0
    while True:
        batch = (
            sb.table("media")
            .select("id,status,r2_url,r2_key,thumbnail_url")
            .neq("r2_key", "")
            .not_.is_("r2_key", "null")
            .range(offset, offset + PAGE - 1)
            .execute()
            .data or []
        )
        results.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return results


def _fetch_all_uploaded_media(sb) -> list[dict]:
    """Fetch all media rows with status='uploaded'."""
    PAGE = 1000
    results = []
    offset = 0
    while True:
        batch = (
            sb.table("media")
            .select("id,status,r2_url,r2_key,thumbnail_url")
            .eq("status", "uploaded")
            .range(offset, offset + PAGE - 1)
            .execute()
            .data or []
        )
        results.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return results


# ── Audit ─────────────────────────────────────────────────────────────────────

def audit(client, sb) -> dict:
    print("=== r2_reset [AUDIT] ===\n")

    objects = _list_all_objects(client)
    total_size_mb = sum(o["Size"] for o in objects) / (1024 ** 2)
    print(f"Bucket objects : {len(objects)}")
    print(f"Total size     : {total_size_mb:.1f} MB\n")

    # Group by media_id prefix: media/<id>/
    by_media: dict[str, list[str]] = defaultdict(list)
    unrecognized = []
    for obj in objects:
        key = obj["Key"]
        parts = key.split("/")
        if len(parts) >= 3 and parts[0] == "media":
            by_media[parts[1]].append(key)
        else:
            unrecognized.append(key)

    print(f"Distinct media prefixes : {len(by_media)}")
    if unrecognized:
        print(f"Unrecognized keys       : {len(unrecognized)}")
        for k in unrecognized[:5]:
            print(f"  {k}")

    # Cross-reference with DB
    db_media = _fetch_all_media_with_r2(sb)
    db_ids = {m["id"] for m in db_media}

    orphaned_prefixes = [mid for mid in by_media if mid not in db_ids]
    no_thumbnail = [
        mid for mid, keys in by_media.items()
        if not any(k.endswith(".jpg") for k in keys)
    ]

    print(f"\nOrphaned prefixes (no DB row)  : {len(orphaned_prefixes)}")
    print(f"Missing thumbnail (.jpg)       : {len(no_thumbnail)}")

    if orphaned_prefixes:
        print("  (first 5 orphaned media IDs)")
        for mid in orphaned_prefixes[:5]:
            print(f"  {mid}")

    print(f"\nDB media rows with r2_key set  : {len(db_media)}")
    missing_in_bucket = [m["id"] for m in db_media if m["id"] not in by_media]
    print(f"DB rows missing from bucket    : {len(missing_in_bucket)}")

    return {
        "objects": len(objects),
        "total_mb": round(total_size_mb, 1),
        "orphaned_prefixes": len(orphaned_prefixes),
        "no_thumbnail": len(no_thumbnail),
        "db_rows_with_r2_key": len(db_media),
        "db_rows_missing_from_bucket": len(missing_in_bucket),
    }


# ── Wipe ─────────────────────────────────────────────────────────────────────

def wipe(client, sb) -> dict:
    print("=== r2_reset [WIPE] ===\n")

    objects = _list_all_objects(client)
    print(f"Objects to delete: {len(objects)}")

    deleted = 0
    if objects:
        # Batch-delete up to 1000 objects per request (S3 API limit)
        BATCH = 1000
        for i in range(0, len(objects), BATCH):
            batch = objects[i:i + BATCH]
            client.delete_objects(
                Bucket=R2_BUCKET,
                Delete={"Objects": [{"Key": o["Key"]} for o in batch]},
            )
            deleted += len(batch)
        print(f"  ✓ deleted {deleted} objects from bucket")

    # Clear r2_url / r2_key / thumbnail_url for all media that had them
    # Also revert uploaded → resized so the create flow can re-upload on demand
    uploaded_rows = _fetch_all_uploaded_media(sb)
    other_rows = _fetch_all_media_with_r2(sb)
    # Combine, de-dup by id
    all_rows = {r["id"]: r for r in other_rows}
    for r in uploaded_rows:
        all_rows[r["id"]] = r

    db_updated = 0
    reverted = 0
    for row in all_rows.values():
        update: dict = {"r2_url": None, "r2_key": None, "thumbnail_url": None}
        if row.get("status") == "uploaded":
            update["status"] = "resized"
            reverted += 1
        sb.table("media").update(update).eq("id", row["id"]).execute()
        db_updated += 1

    print(f"  ✓ cleared r2 fields on {db_updated} media rows")
    print(f"  ✓ reverted {reverted} rows: uploaded → resized")

    return {"deleted_objects": deleted, "db_rows_updated": db_updated, "reverted_to_resized": reverted}


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    if not _use_supabase():
        print("ERROR: Supabase not configured.")
        sys.exit(1)
    if not R2_ENDPOINT or not R2_ACCESS_KEY:
        print("ERROR: R2 not configured.")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--audit", action="store_true", help="Inspect bucket vs DB (read-only)")
    group.add_argument("--wipe", action="store_true", help="Delete ALL R2 objects + reset DB fields")
    args = parser.parse_args()

    client = get_r2_client()
    sb = get_supabase()

    if args.audit:
        audit(client, sb)
    elif args.wipe:
        result = wipe(client, sb)
        print(f"\n=== done === {result}")


if __name__ == "__main__":
    main()
