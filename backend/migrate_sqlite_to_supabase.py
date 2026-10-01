"""
One-time migration: SQLite content.db + queue.json → Supabase.
Run after Supabase project is created and tables are pushed.

Usage: python -m backend.migrate_sqlite_to_supabase
"""

import json
import sqlite3
from pathlib import Path
from backend.config import SQLITE_DB, QUEUE_FILE
from backend.db import get_supabase

STATUS_MAP = {0: "raw", 1: "resized"}


def migrate_media(sb):
    if not Path(SQLITE_DB).exists():
        print("No content.db found — skipping media migration")
        return 0

    conn = sqlite3.connect(str(SQLITE_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM media").fetchall()
    conn.close()

    if not rows:
        print("No media rows to migrate")
        return 0

    batch = []
    for row in rows:
        data = dict(row)
        if "processed" in data:
            data["status"] = STATUS_MAP.get(data.pop("processed"), "raw")
        batch.append(data)

    resp = sb.table("media").upsert(batch).execute()
    count = len(resp.data) if resp.data else 0
    print(f"Migrated {count} media rows")
    return count


def migrate_queue(sb):
    if not QUEUE_FILE.exists():
        print("No queue.json found — skipping posts migration")
        return 0

    queue = json.loads(QUEUE_FILE.read_text())
    if not queue:
        print("Empty queue.json — skipping")
        return 0

    posts = []
    for item in queue:
        post = {
            "media_id": item.get("id", item.get("media_id")),
            "status": item.get("status", "draft"),
            "caption": item.get("caption", ""),
            "alt_text": item.get("alt_text", ""),
        }
        if item.get("scheduled_at"):
            post["scheduled_at"] = item["scheduled_at"]
        if item.get("ig_media_id"):
            post["ig_media_id"] = item["ig_media_id"]

        hashtags = item.get("hashtags", "")
        if isinstance(hashtags, str):
            post["hashtags_en"] = [t.strip("#") for t in hashtags.split() if t]
        elif isinstance(hashtags, list):
            post["hashtags_en"] = hashtags

        posts.append(post)

    resp = sb.table("posts").insert(posts).execute()
    count = len(resp.data) if resp.data else 0
    print(f"Migrated {count} queue items to posts table")
    return count


def main():
    sb = get_supabase()
    print("Starting SQLite → Supabase migration...")
    media_count = migrate_media(sb)
    posts_count = migrate_queue(sb)
    print(f"\nDone. Migrated {media_count} media + {posts_count} posts.")


if __name__ == "__main__":
    main()
