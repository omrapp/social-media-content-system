"""
backfill_yt_playlists — ensure all posted YouTube videos are in per-category playlists.

Idempotent: uses the same _find_or_create_playlist / _add_to_playlist logic as the
publish pipeline. Safe to run multiple times.

Usage:
  python -m backend.scripts.backfill_yt_playlists            # dry-run
  python -m backend.scripts.backfill_yt_playlists --apply    # execute
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.db import _use_supabase, get_supabase
from backend.pipeline.youtube_publish import _build_client, _find_or_create_playlist, _add_to_playlist


def _fetch_posted_yt_videos() -> list[dict]:
    """Return posts with yt_video_id set, joined with media.category."""
    sb = get_supabase()
    try:
        posts = (
            sb.table("posts")
            .select("id,yt_video_id,media_id")
            .not_.is_("yt_video_id", "null")
            .execute()
            .data or []
        )
    except Exception as exc:
        print(f"ERROR: could not fetch posts: {exc}")
        return []

    media_ids = list({p["media_id"] for p in posts if p.get("media_id")})
    if not media_ids:
        return []

    category_map: dict[str, str] = {}
    for mid in media_ids:
        try:
            row = sb.table("media").select("id,category").eq("id", mid).single().execute().data
            if row and row.get("category"):
                category_map[mid] = row["category"]
        except Exception:
            pass

    result = []
    for p in posts:
        category = category_map.get(p.get("media_id") or "")
        if p.get("yt_video_id") and category:
            result.append({"yt_video_id": p["yt_video_id"], "category": category, "post_id": p["id"]})
    return result


def run(apply: bool = False) -> None:
    if not _use_supabase():
        print("ERROR: Supabase not configured.")
        sys.exit(1)

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"=== backfill_yt_playlists [{mode}] ===")
    if not apply:
        print("Pass --apply to execute changes.\n")

    videos = _fetch_posted_yt_videos()
    print(f"Found {len(videos)} posted YouTube videos with category data\n")
    if not videos:
        return

    if not apply:
        for v in videos:
            print(f"  would add {v['yt_video_id']} → playlist '{v['category']}'")
        return

    try:
        yt = _build_client()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    by_category: dict[str, list[str]] = {}
    for v in videos:
        by_category.setdefault(v["category"], []).append(v["yt_video_id"])

    for category, video_ids in by_category.items():
        print(f"  {category}: {len(video_ids)} video(s)…")
        playlist_id = _find_or_create_playlist(yt, category)
        if not playlist_id:
            print(f"    ✗ could not get/create playlist for '{category}' — check logs")
            continue
        for vid in video_ids:
            ok = _add_to_playlist(yt, playlist_id, vid, category=category)
            status = "✓" if ok else "✗ (may already be in playlist or 404)"
            print(f"    {status} {vid}")

    print("\n=== done ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill YouTube per-category playlists.")
    parser.add_argument("--apply", action="store_true", help="Execute changes (default is dry-run).")
    args = parser.parse_args()
    run(apply=args.apply)
