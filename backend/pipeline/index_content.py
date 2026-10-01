"""
Index downloaded IG content into the media table.

Reads the download manifests (posts/stories/highlights) and upserts one media row
per item. Idempotent: re-running only refreshes manifest-sourced fields and never
clobbers downstream pipeline state (status, r2_url, captions, etc.).

Writes through the db abstraction so prod (Supabase) and dev (SQLite) both populate:
the old version talked raw SQLite via get_connection() and never reached Supabase,
which left the prod media table empty (Create taxonomy + Downloads showed nothing).

local_path is stored RELATIVE to ORGANIZED_DIR (e.g. "nature/stories/123.jpg") so it
stays valid across machines and maps directly to the /static/media/<rel> mount.
"""

import json
import logging
import re
import subprocess
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

import httpx

from backend.config import (
    POSTS_MANIFEST,
    STORIES_MANIFEST,
    HIGHLIGHTS_MANIFEST,
    ORGANIZED_DIR,
)
from backend.db import _use_supabase, get_supabase, get_connection, init_db

log = logging.getLogger(__name__)

HASHTAG_RE = re.compile(r"#\w+", flags=re.UNICODE)

# Manifest fields we own — the only columns an upsert is allowed to overwrite.
# Everything else on an existing row (status, r2_url, hook_score, captions…) is preserved.
_MANIFEST_FIELDS = (
    "source", "media_type", "local_path", "caption", "taken_at",
    "category", "tags", "original_caption", "original_hashtags",
)

_SUPABASE_BATCH = 500

# Supabase media.media_type CHECK allows only these IG-style uppercase values.
_MEDIA_TYPE_MAP = {"video": "VIDEO", "image": "IMAGE", "carousel_album": "CAROUSEL_ALBUM"}


def _media_type(raw):
    return _MEDIA_TYPE_MAP.get((raw or "").lower(), "IMAGE")


def _iso(ts):
    if ts in (None, "", 0):
        return ""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    return str(ts)


def _hashtags(caption):
    if not caption:
        return "[]"
    return json.dumps(HASHTAG_RE.findall(caption), ensure_ascii=False)


def _rel_path(local_path):
    """Absolute manifest path → path relative to organized/. Falls back to basename."""
    if not local_path:
        return ""
    parts = Path(local_path).parts
    if "organized" in parts:
        idx = parts.index("organized")
        return str(Path(*parts[idx + 1:]))
    return Path(local_path).name


def _row_from_item(item, source):
    caption = item.get("caption") or ""
    return {
        "id": str(item["id"]),
        "source": source,
        "media_type": _media_type(item.get("media_type")),
        "local_path": _rel_path(item.get("local_path", "")),
        "caption": caption,
        "taken_at": _iso(item.get("timestamp")),
        "category": item.get("category") or "uncategorized",
        "tags": item.get("tags") or [],
        "original_caption": caption,
        "original_hashtags": _hashtags(caption),
    }


def _load(manifest_path):
    if not manifest_path.exists():
        return []
    return json.loads(manifest_path.read_text())


def _collect_rows():
    """Build deduped rows from all manifests. Later duplicate ids win (last seen)."""
    rows = {}
    for item in _load(POSTS_MANIFEST):
        rows[str(item["id"])] = _row_from_item(item, "post")
    for item in _load(STORIES_MANIFEST):
        rows[str(item["id"])] = _row_from_item(item, "story")
    # Highlights: legacy nested {name: {items:[...]}} OR flat list with highlight_name.
    hl = _load(HIGHLIGHTS_MANIFEST)
    if isinstance(hl, dict):
        for name, data in hl.items():
            for item in data.get("items", []):
                row = _row_from_item(item, "highlight")
                row["highlight_name"] = name
                rows[str(item["id"])] = row
    else:
        for item in hl:
            row = _row_from_item(item, "highlight")
            if item.get("highlight_name"):
                row["highlight_name"] = item["highlight_name"]
            rows[str(item["id"])] = row
    return list(rows.values())


def _upsert_supabase(rows):
    sb = get_supabase()
    for i in range(0, len(rows), _SUPABASE_BATCH):
        chunk = rows[i:i + _SUPABASE_BATCH]
        for attempt in range(3):
            try:
                sb.table("media").upsert(chunk).execute()
                break
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError, httpx.WriteError) as exc:
                if attempt == 2:
                    raise
                log.warning("Supabase upsert disconnected (attempt %d/3): %s — retrying", attempt + 1, exc)
                time.sleep(2 ** attempt)
    return len(rows)


def _sqlite_row(row: dict) -> dict:
    """SQLite stores `tags` as a JSON-text column — Supabase gets the list
    as-is (native array column)."""
    if isinstance(row.get("tags"), list):
        row = {**row, "tags": json.dumps(row["tags"], ensure_ascii=False)}
    return row


def _upsert_sqlite(rows):
    conn = get_connection()
    init_db(conn)
    set_clause = ", ".join(f"{f} = excluded.{f}" for f in _MANIFEST_FIELDS)
    cols = ("id", "highlight_name", *_MANIFEST_FIELDS)
    placeholders = ", ".join(f":{c}" for c in cols)
    sql = (
        f"INSERT INTO media ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {set_clause}"
    )
    for row in rows:
        row.setdefault("highlight_name", None)
        conn.execute(sql, _sqlite_row(row))
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    conn.close()
    return total


def _classify_loop():
    """Run the Groq category tagger repeatedly until no raw/untagged items remain.

    Heavy + rate-limited (~28 req/min). Stops on first pass that makes no progress.
    """
    from backend.pipeline import classify_groq

    total_classified = 0
    while True:
        r = classify_groq.run()
        total_classified += r["classified"]
        if r["total"] == 0 or r["classified"] == 0 or r.get("stopped_daily_cap"):
            break
    return total_classified


def _ffprobe_video(path: Path) -> dict | None:
    """Return {duration_s, width, height} for a video file via ffprobe, or None on failure."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration:format=duration",
                "-of", "csv=p=0", str(path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None
        lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
        width = height = duration = None
        for line in lines:
            parts = line.split(",")
            if len(parts) == 3:
                try:
                    width, height = int(parts[0]), int(parts[1])
                    if parts[2] and parts[2] != "N/A":
                        duration = float(parts[2])
                except (ValueError, IndexError):
                    pass
            elif len(parts) == 1:
                try:
                    duration = float(parts[0])
                except ValueError:
                    pass
        if duration is None or duration <= 0:
            return None
        result: dict = {"duration_s": round(duration, 2)}
        if width and height:
            result["width"] = width
            result["height"] = height
        return result
    except Exception:
        return None


def insert_upload_row(
    local_path_rel: str,
    category: str,
    tags: list[str] | None = None,
    *,
    media_type: str = "VIDEO",
    source: str = "upload",
) -> dict:
    """Create ONE fresh raw media row for a user-uploaded clip (local file or URL fetch).

    Writes through the db abstraction (Supabase-first, SQLite fallback), mirroring
    the column shape of _row_from_item. `local_path_rel` is relative to ORGANIZED_DIR.
    After insert, ffprobe populates duration_s/width/height so selection quality gates
    work (reuses _ffprobe_video). Returns the inserted row dict (incl id).

    `source` defaults to "upload" (existing manual-upload callers unaffected); pass
    source="stock" for stock-footage imports — gets a "stk_" id prefix so stock rows
    are distinguishable from manual uploads at a glance.
    """
    id_prefix = "stk_" if source == "stock" else "up_"
    row_id = id_prefix + uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": row_id,
        "source": source,
        "media_type": media_type,
        "local_path": local_path_rel,
        "status": "raw",
        "category": category or "uncategorized",
        "tags": tags or [],
        # Neutral baseline hook_score so uploaded / stock clips count as "classified"
        # (_is_classified needs category+hook_score). Without it, selection's
        # require_classified (default True) excludes these rows from merge/single
        # picks whenever any archive clip in the same category IS classified — the
        # reason imported stock never appeared in merged reels. A later real
        # classify pass overwrites this value.
        "hook_score": 0.5,
        "caption": "",
        "original_caption": "",
        "original_hashtags": "[]",
        "taken_at": now,
    }

    if _use_supabase():
        get_supabase().table("media").insert(row).execute()
    else:
        conn = get_connection()
        init_db(conn)
        sqlite_row = _sqlite_row(row)
        cols = ", ".join(sqlite_row.keys())
        placeholders = ", ".join(f":{c}" for c in sqlite_row.keys())
        conn.execute(f"INSERT INTO media ({cols}) VALUES ({placeholders})", sqlite_row)
        conn.commit()
        conn.close()

    # Probe duration/dimensions on the saved file (reuse, don't reimplement).
    probe = _ffprobe_video(ORGANIZED_DIR / local_path_rel)
    if probe:
        try:
            if _use_supabase():
                get_supabase().table("media").update(probe).eq("id", row_id).execute()
            else:
                sets = ", ".join(f"{k}=?" for k in probe)
                conn = get_connection()
                conn.execute(f"UPDATE media SET {sets} WHERE id=?", (*probe.values(), row_id))
                conn.commit()
                conn.close()
            row.update(probe)
        except Exception as exc:
            log.warning("insert_upload_row: probe update failed for %s: %s", row_id, exc)

    return row


def _probe_unscored_videos(limit: int = 200) -> int:
    """Probe VIDEO rows with NULL duration_s and write back dimension/duration data.

    Called after the manifest upsert so the rows exist in the DB. Bounded to
    `limit` clips per run to avoid blocking the index stage for large archives.
    Returns number of rows updated.
    """
    if not _use_supabase():
        return 0
    sb = get_supabase()
    rows = (
        sb.table("media")
        .select("id,local_path,media_type")
        .eq("media_type", "VIDEO")
        .is_("duration_s", "null")
        .limit(limit)
        .execute()
        .data or []
    )
    updated = 0
    for row in rows:
        rel = row.get("local_path") or ""
        if not rel:
            continue
        path = ORGANIZED_DIR / rel
        if not path.exists():
            continue
        probe = _ffprobe_video(path)
        if not probe:
            continue
        try:
            sb.table("media").update(probe).eq("id", row["id"]).execute()
            updated += 1
        except Exception as exc:
            log.warning("index: probe update failed for %s: %s", row["id"], exc)
    if updated:
        log.info("index: probed %d video(s) for duration/dimensions", updated)
    return updated


def run(classify: bool = False):
    rows = _collect_rows()
    posts = sum(1 for r in rows if r["source"] == "post")
    stories = sum(1 for r in rows if r["source"] == "story")
    highlights = sum(1 for r in rows if r["source"] == "highlight")

    if _use_supabase():
        written = _upsert_supabase(rows)
        backend = "supabase"
    else:
        written = _upsert_sqlite(rows)
        backend = "sqlite"

    with_category = sum(1 for r in rows if r["category"] and r["category"] != "uncategorized")

    probed = _probe_unscored_videos()

    result = {
        "backend": backend,
        "posts": posts,
        "stories": stories,
        "highlights": highlights,
        "indexed": len(rows),
        "with_category": with_category,
        "total_in_db": written,
        "probed_videos": probed,
    }
    if classify:
        result["classified"] = _classify_loop()
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--classify",
        action="store_true",
        help="After indexing, run Groq category tagging until done (slow, rate-limited)",
    )
    args = parser.parse_args()

    result = run(classify=args.classify)
    print(
        f"[{result['backend']}] indexed {result['indexed']} "
        f"({result['posts']} posts, {result['stories']} stories, "
        f"{result['highlights']} highlights), {result['with_category']} categorized. "
        f"media rows: {result['total_in_db']}."
    )
    if "classified" in result:
        print(f"Classified {result['classified']} items via Groq.")
