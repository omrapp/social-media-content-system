import json
import logging
import sqlite3
from datetime import datetime, timezone
from backend.config import SQLITE_DB, SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_KEY

log = logging.getLogger(__name__)

STATUS_FLOW = ["raw", "resized", "enhanced", "edited", "uploaded", "scheduled", "preview", "posted", "error", "deleted"]
APPROVAL_FLOW = ["pending", "approved", "rejected", "auto_approved"]
MUSIC_SOURCES = ["original", "licensed", "none", "unknown"]

_supabase_client = None


def _use_supabase():
    return bool(SUPABASE_URL and SUPABASE_KEY)


def get_supabase():
    global _supabase_client
    if _supabase_client is None:
        import httpx
        from supabase import create_client, ClientOptions
        key = SUPABASE_SERVICE_KEY or SUPABASE_KEY
        # Force HTTP/1.1: the shared HTTP/2 connection pool is not thread-safe
        # across FastAPI threadpool workers (hpack deque mutated during iteration).
        _supabase_client = create_client(
            SUPABASE_URL, key,
            options=ClientOptions(httpx_client=httpx.Client(http2=False)),
        )
    return _supabase_client


def _reset_supabase():
    """Drop the cached client so the next call rebuilds a fresh connection."""
    global _supabase_client
    _supabase_client = None


def db_retry(fn, attempts: int = 3):
    """
    Run a Supabase call, retrying on transient HTTP/2 connection drops.

    Supabase's long-lived HTTP/2 connection is periodically terminated by the
    server (GOAWAY → httpx RemoteProtocolError). The cached client then raises on
    the next call. We reset the client and retry so daemon ticks don't die on a
    stale connection.
    """
    import time
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            name = type(exc).__name__
            exc_str = str(exc)
            transient = (
                "RemoteProtocolError" in name
                # Corrupted HTTP/2 connection state on a reused cached client —
                # "Received pseudo-header in trailer". Rebuilding the client clears it.
                or "LocalProtocolError" in name
                or "pseudo-header in trailer" in exc_str
                or "ConnectionTerminated" in exc_str
                or "Server disconnected" in exc_str
                or "ConnectError" in name
                or "deque mutated during iteration" in exc_str
                or ("APIError" in name and "JSON could not be generated" in exc_str)
                or ("APIError" in name and "<html>" in exc_str)
            )
            if not transient or i == attempts - 1:
                raise
            last_exc = exc
            _reset_supabase()
            time.sleep(0.5 * (i + 1))
    raise last_exc  # pragma: no cover


# ── SQLite fallback ──────────────────────────────────────────

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY, source TEXT, highlight_name TEXT, media_type TEXT,
    local_path TEXT, caption TEXT, taken_at TEXT, duration_s REAL,
    width INT, height INT, hook_score REAL, status TEXT DEFAULT 'raw',
    reel_ready_path TEXT, r2_url TEXT, r2_key TEXT, thumbnail_url TEXT,
    category TEXT, tags TEXT, error_message TEXT,
    original_caption TEXT, original_hashtags TEXT, original_music TEXT,
    music_source TEXT DEFAULT 'unknown', licensed_music TEXT,
    approval_status TEXT DEFAULT 'pending', feedback TEXT,
    edit_requests TEXT, media_preview_url TEXT,
    publish_after TEXT, approved_at TEXT,
    series_id TEXT, episode_number INT, episode_total INT,
    global_day_number INT, series_arc_position TEXT,
    caption_ig TEXT, caption_ig_ar TEXT, caption_tt TEXT,
    caption_yt_title TEXT, caption_yt_description TEXT,
    hashtags_en TEXT, hashtags_ar TEXT, hashtags_en_b TEXT, alt_text TEXT,
    do_not_use INT DEFAULT 0,
    quality_score REAL, blur_score REAL, shake_score REAL,
    decaptioned INT DEFAULT 0, decaptioned_path TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# All non-PK media columns and their ADD COLUMN declarations.
# _migrate() compares this list against the live table and back-fills anything missing —
# safe to run on DBs that predate any past schema change.
_MEDIA_COLUMNS = [
    ("source", "TEXT"),
    ("highlight_name", "TEXT"),
    ("media_type", "TEXT"),
    ("local_path", "TEXT"),
    ("caption", "TEXT"),
    ("taken_at", "TEXT"),
    ("duration_s", "REAL"),
    ("width", "INT"),
    ("height", "INT"),
    ("hook_score", "REAL"),
    ("status", "TEXT DEFAULT 'raw'"),
    ("reel_ready_path", "TEXT"),
    ("r2_url", "TEXT"),
    ("r2_key", "TEXT"),
    ("thumbnail_url", "TEXT"),
    ("category", "TEXT"),
    ("tags", "TEXT"),
    ("error_message", "TEXT"),
    ("original_caption", "TEXT"),
    ("original_hashtags", "TEXT"),
    ("original_music", "TEXT"),
    ("music_source", "TEXT DEFAULT 'unknown'"),
    ("licensed_music", "TEXT"),
    ("approval_status", "TEXT DEFAULT 'pending'"),
    ("feedback", "TEXT"),
    ("edit_requests", "TEXT"),
    ("media_preview_url", "TEXT"),
    ("publish_after", "TEXT"),
    ("approved_at", "TEXT"),
    ("series_id", "TEXT"),
    ("episode_number", "INT"),
    ("episode_total", "INT"),
    ("global_day_number", "INT"),
    ("series_arc_position", "TEXT"),
    ("caption_ig", "TEXT"),
    ("caption_ig_ar", "TEXT"),
    ("caption_tt", "TEXT"),
    ("caption_yt_title", "TEXT"),
    ("caption_yt_description", "TEXT"),
    ("hashtags_en", "TEXT"),
    ("hashtags_ar", "TEXT"),
    ("alt_text", "TEXT"),
    ("do_not_use", "INT DEFAULT 0"),
    ("hashtags_en_b", "TEXT"),
    ("quality_score", "REAL"),  # combined blur/shake probe score 0-1 (0.6.0)
    ("blur_score", "REAL"),     # sharpness sub-metric, debugging (0.6.0)
    ("shake_score", "REAL"),    # stability sub-metric, debugging (0.6.0)
    # Decaption cache (v1.5.0): 1 once a clip has been scanned/cleaned (idempotent,
    # never re-scanned); decaptioned_path points at the cleaned file under
    # DECAPTIONED_DIR, or the original when the detector found no overlay text.
    # Supabase is migrated MANUALLY — run this once against the prod DB:
    #   ALTER TABLE media ADD COLUMN decaptioned INT DEFAULT 0;
    #   ALTER TABLE media ADD COLUMN decaptioned_path TEXT;
    ("decaptioned", "INT DEFAULT 0"),
    ("decaptioned_path", "TEXT"),
]


def _migrate(conn):
    existing = {r[1] for r in conn.execute("PRAGMA table_info(media)").fetchall()}
    for name, decl in _MEDIA_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE media ADD COLUMN {name} {decl}")
    # Generic-taxonomy cutover: backfill category/tags from the old
    # pillar/country/city columns (if still present) then drop them.
    if "pillar" in existing:
        conn.execute("UPDATE media SET category = pillar WHERE pillar IS NOT NULL AND category IS NULL")
    if "country" in existing or "city" in existing:
        country_expr = "country" if "country" in existing else "NULL"
        city_expr = "city" if "city" in existing else "NULL"
        rows = conn.execute(
            f"SELECT id, {country_expr} AS country, {city_expr} AS city FROM media "
            "WHERE tags IS NULL OR tags = '' OR tags = '[]'"
        ).fetchall()
        for row in rows:
            merged = [v for v in (row["country"], row["city"]) if v]
            if merged:
                conn.execute(
                    "UPDATE media SET tags=? WHERE id=?",
                    (json.dumps(merged, ensure_ascii=False), row["id"]),
                )
    for col in ("pillar", "country", "city"):
        if col in existing:
            conn.execute(f"ALTER TABLE media DROP COLUMN {col}")
    if "series" in {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}:
        conn.execute("DROP TABLE series")
    # Indexes that depend on migrated columns — safe to create after ALTERs run.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_series_episode "
        "ON media(series_id, episode_number)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_media_category ON media(category)")
    conn.commit()


def get_connection():
    conn = sqlite3.connect(str(SQLITE_DB))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn=None):
    # Pipeline scripts use SQLite directly regardless of Supabase env, so always
    # ensure the local schema is initialized + migrated when a connection is in play.
    if _use_supabase() and conn is None:
        return
    close = conn is None
    if close:
        conn = get_connection()
    conn.executescript(SQLITE_SCHEMA)
    conn.commit()
    _migrate(conn)
    if close:
        conn.close()


# ── Generic query/execute (SQLite only, used by pipeline scripts) ──

def query(sql, params=(), conn=None):
    close = conn is None
    if close:
        conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    if close:
        conn.close()
    return [dict(r) for r in rows]


def execute(sql, params=(), conn=None):
    close = conn is None
    if close:
        conn = get_connection()
    conn.execute(sql, params)
    conn.commit()
    if close:
        conn.close()


# ── High-level functions (Supabase-first, SQLite fallback) ──

def get_media(filters=None, limit=100, offset=0, include_deleted=False):
    if _use_supabase():
        def _fetch():
            q = get_supabase().table("media").select("*")
            if not include_deleted:
                q = q.neq("status", "deleted")
            if filters:
                for k, v in filters.items():
                    q = q.eq(k, v)
            return q.range(offset, offset + limit - 1).execute().data
        return db_retry(_fetch)
    sql = "SELECT * FROM media"
    conditions = []
    params = []
    if not include_deleted:
        conditions.append("status != 'deleted'")
    if filters:
        for k, v in filters.items():
            conditions.append(f"{k}=?")
            params.append(v)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += f" LIMIT {limit} OFFSET {offset}"
    return query(sql, params)


def get_all_media(include_deleted=False):
    """Fetch every media row, paginating past PostgREST's 1000-row response cap.

    get_media(limit=99999) silently truncates to 1000 in Supabase mode because
    .range() is bounded by PostgREST. Analytics/statistics aggregations need the
    full table, so loop in 1000-row pages until a short page returns. Mirrors the
    pagination in get_distinct().
    """
    if _use_supabase():
        rows: list = []
        start, page = 0, 1000
        while True:
            # Re-fetch the client inside db_retry so a reset (after a GOAWAY /
            # RemoteProtocolError) rebuilds the connection before retrying.
            def _fetch_page(s=start):
                q = get_supabase().table("media").select("*")
                if not include_deleted:
                    q = q.neq("status", "deleted")
                return q.range(s, s + page - 1).execute().data
            batch = db_retry(_fetch_page)
            rows.extend(batch)
            if len(batch) < page:
                break
            start += page
        return rows
    sql = "SELECT * FROM media"
    if not include_deleted:
        sql += " WHERE status != 'deleted'"
    return query(sql, [])


def get_media_by_id(media_id):
    if _use_supabase():
        # maybe_single() returns data=None on 0 rows instead of raising PGRST116
        # ("Cannot coerce the result to a single JSON object"), so a missing id
        # surfaces as None → 404 in routes, never a 500.
        resp = db_retry(lambda: get_supabase().table("media").select("*").eq("id", media_id).maybe_single().execute())
        return resp.data if resp else None
    rows = query("SELECT * FROM media WHERE id=?", (media_id,))
    return rows[0] if rows else None


def upsert_media(data):
    if _use_supabase():
        return db_retry(lambda: get_supabase().table("media").upsert(data).execute().data)
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    execute(
        f"INSERT OR REPLACE INTO media ({cols}) VALUES ({placeholders})",
        tuple(data.values())
    )


def delete_media_row(media_id) -> bool:
    """Hard-delete a media row (not the soft 'deleted' status). Used by stock
    cleanup to reclaim storage — stock clips are always re-downloadable from the
    provider, so no soft-delete audit trail is needed."""
    if _use_supabase():
        db_retry(lambda: get_supabase().table("media").delete().eq("id", media_id).execute())
        return True
    execute("DELETE FROM media WHERE id=?", (media_id,))
    return True


def update_status(media_id, new_status, error_message=None, conn=None):
    if _use_supabase():
        update = {"status": new_status}
        if error_message:
            update["error_message"] = error_message
        return db_retry(lambda: get_supabase().table("media").update(update).eq("id", media_id).execute())
    if error_message:
        execute("UPDATE media SET status=?, error_message=? WHERE id=?",
                (new_status, error_message, media_id), conn)
    else:
        execute("UPDATE media SET status=? WHERE id=?", (new_status, media_id), conn)


def update_media(media_id, data):
    if _use_supabase():
        return db_retry(lambda: get_supabase().table("media").update(data).eq("id", media_id).execute())
    sets = ", ".join(f"{k}=?" for k in data)
    execute(f"UPDATE media SET {sets} WHERE id=?", (*data.values(), media_id))


# ── Posts (Supabase only — queue.json fallback handled in scheduler) ──

def create_post(data):
    if not _use_supabase():
        return None
    return db_retry(lambda: get_supabase().table("posts").insert(data).execute().data)


def get_posts(filters=None, limit=50, desc=False):
    if not _use_supabase():
        return []
    def _fetch():
        q = get_supabase().table("posts").select("*")
        if filters:
            for k, v in filters.items():
                q = q.eq(k, v)
        return q.order("scheduled_at", desc=desc).limit(limit).execute().data
    return db_retry(_fetch)


def get_post_by_id(post_id):
    if not _use_supabase():
        return None
    # maybe_single() returns data=None on 0 rows instead of raising PGRST116, so a
    # stale/already-deleted post_id surfaces as None → 404 in routes, not a 500.
    resp = db_retry(lambda: get_supabase().table("posts").select("*").eq("id", post_id).maybe_single().execute())
    return resp.data if resp else None


def update_post(post_id, data):
    if not _use_supabase():
        return None
    return db_retry(lambda: get_supabase().table("posts").update(data).eq("id", post_id).execute())


def delete_post(post_id):
    if not _use_supabase():
        return None
    return db_retry(lambda: get_supabase().table("posts").delete().eq("id", post_id).execute())


def get_due_posts() -> list[dict]:
    """Return posts where publish_after <= now and status is 'preview'."""
    if not _use_supabase():
        return []
    now = datetime.now(timezone.utc).isoformat()
    return db_retry(lambda: (
        get_supabase()
        .table("posts")
        .select("*")
        .lte("publish_after", now)
        .eq("status", "preview")
        .execute()
        .data
    ))


def get_distinct(column: str, filters: dict | None = None) -> list[str]:
    """Return sorted distinct non-null values of a media column."""
    if _use_supabase():
        # PostgREST caps responses at 1000 rows; paginate so distinct values
        # aren't computed over a truncated slice (media can exceed 10k rows).
        values: set = set()
        start, page = 0, 1000
        while True:
            def _fetch_page(s=start):
                q = get_supabase().table("media").select(column)
                if filters:
                    for k, v in filters.items():
                        q = q.eq(k, v)
                return q.not_.is_(column, "null").range(s, s + page - 1).execute().data
            rows = db_retry(_fetch_page)
            for r in rows:
                if r.get(column):
                    values.add(r[column])
            if len(rows) < page:
                break
            start += page
        return sorted(values)
    sql = f"SELECT DISTINCT {column} FROM media WHERE {column} IS NOT NULL"
    params: list = []
    if filters:
        for k, v in filters.items():
            sql += f" AND {k}=?"
            params.append(v)
    sql += f" ORDER BY {column}"
    return [r[column] for r in query(sql, params)]


def _selection_rank(row: dict, category_perf: dict[str, float], weight: float) -> float:
    """Blended pick score: predicted visual hook_score lifted by the clip's
    category realized engagement (Enhancement I). When category_perf is empty
    (cold start) this is just hook_score, so behaviour is unchanged until real
    performance data exists. The lift only reorders across categories — within a
    single fixed category it adds a constant and never changes the ranking."""
    base = row.get("hook_score") or 0
    perf = category_perf.get(row.get("category")) or 0.0
    return base + weight * perf


def _quality_gate_cfg() -> dict:
    """Selection quality-gate thresholds with safe defaults (0.6.0)."""
    cfg = get_setting("selection") or {}

    def _num(key, default):
        try:
            return float(cfg.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    return {
        "min_duration_s": _num("min_duration_s", 10.0),
        "min_short_side": _num("min_short_side", 720.0),
        "min_hook_score": _num("min_hook_score", 0.0),
        "min_quality_score": _num("min_quality_score", 0.0),
        "require_video_only": bool(cfg.get("require_video_only", True)),
    }


def _passes_quality_gate(row: dict, cfg: dict) -> tuple[bool, str | None]:
    """Null-safe selection gate. A rule only rejects when the field is PRESENT
    and below threshold — missing data is never treated as a failure (avoids
    starving the queue on un-probed archive). Returns (passes, skip_reason).
    Thresholds of 0 disable that individual rule."""
    if cfg["require_video_only"] and row.get("media_type") not in (None, "VIDEO"):
        return False, "not_video"

    dur = row.get("duration_s")
    if dur is not None and cfg["min_duration_s"] > 0 and dur < cfg["min_duration_s"]:
        return False, f"too_short({dur:.1f}s<{cfg['min_duration_s']:.0f}s)"

    w, h = row.get("width"), row.get("height")
    if w and h and cfg["min_short_side"] > 0 and min(w, h) < cfg["min_short_side"]:
        return False, f"low_res({min(w, h)}px<{cfg['min_short_side']:.0f}px)"

    hs = row.get("hook_score")
    if hs is not None and cfg["min_hook_score"] > 0 and hs < cfg["min_hook_score"]:
        return False, f"low_hook_score({hs:.2f}<{cfg['min_hook_score']:.2f})"

    qs = row.get("quality_score")
    if qs is not None and cfg["min_quality_score"] > 0 and qs < cfg["min_quality_score"]:
        return False, f"low_quality({qs:.2f}<{cfg['min_quality_score']:.2f})"

    return True, None


def _filter_by_quality(rows: list[dict], where: str = "selection") -> list[dict]:
    """Apply the quality gate to a candidate list, logging each skip with reason."""
    cfg = _quality_gate_cfg()
    kept = []
    for r in rows:
        ok, reason = _passes_quality_gate(r, cfg)
        if ok:
            kept.append(r)
        else:
            log.info("%s: skip media_id=%s — %s", where, r.get("id"), reason)
    return kept


def _best_media(rows: list[dict]) -> dict:
    """Pick the highest-ranked raw clip, blending hook_score with realized
    per-category performance when selection.use_performance is on (default)."""
    cfg = get_setting("selection") or {}
    category_perf: dict[str, float] = {}
    if cfg.get("use_performance", True):
        try:
            from backend.pipeline.feedback_aggregator import category_performance
            category_perf = category_performance()
        except Exception:
            category_perf = {}
    if not category_perf:
        return max(rows, key=lambda r: r.get("hook_score") or 0)
    try:
        weight = float(cfg.get("performance_weight", 0.5))
    except (TypeError, ValueError):
        weight = 0.5
    return max(rows, key=lambda r: _selection_rank(r, category_perf, weight))


def _is_classified(row: dict) -> bool:
    """True when category + hook_score are both present (fully classified)."""
    return (
        row.get("category") is not None
        and row.get("hook_score") is not None
    )


def _tags_where_sqlite(tags: list[str] | None) -> tuple[str, list]:
    """SQLite WHERE-clause fragment matching ALL of `tags` against the JSON-text
    `tags` column (each element LIKE-matched — no JSON1 dependency)."""
    if not tags:
        return "", []
    clause = " AND ".join(["tags LIKE ?"] * len(tags))
    return f" AND {clause}", [f'%"{t}"%' for t in tags]


def _categories_until_distinct(categories: list, min_distinct: int) -> set[str]:
    """Walk an ordered (most-recent-first) category list and collect the most
    recent `min_distinct` DISTINCT values, stopping as soon as that many unique
    categories are seen. Returns fewer if the list runs out first. Counting
    distinct categories (not just the last N posts) matters because a small pool
    can post the same category several times in a row, which would under-count
    real diversity if we only looked at post count."""
    seen: set[str] = set()
    for c in categories:
        if not c:
            continue
        seen.add(c)
        if len(seen) >= min_distinct:
            break
    return seen


def recent_posted_distinct_categories(min_distinct: int) -> set[str]:
    """The last `min_distinct` DISTINCT categories used across recent posts
    (preview/scheduled/posted), most-recent-first — i.e. the cooldown set a
    category must clear before it's eligible again.
    Supabase only; returns empty set on SQLite or any error — cooldown is a no-op."""
    if not _use_supabase() or min_distinct <= 0:
        return set()
    try:
        # Scan a bounded window of recent posts, comfortably larger than any
        # realistic cooldown, so we can actually reach min_distinct distinct
        # categories even if the same category repeats a lot in between.
        scan_limit = max(min_distinct * 10, 200)
        posts = db_retry(lambda: (
            get_supabase()
            .table("posts")
            .select("media_id")
            .in_("status", ["preview", "scheduled", "posted"])
            .order("created_at", desc=True)
            .limit(scan_limit)
            .execute()
        )).data or []
        media_ids = [p["media_id"] for p in posts if p.get("media_id")]
        if not media_ids:
            return set()
        media = db_retry(lambda: (
            get_supabase()
            .table("media")
            .select("id, category")
            .in_("id", media_ids)
            .execute()
        )).data or []
        category_by_id = {m["id"]: m.get("category") for m in media}
        ordered_categories = [category_by_id.get(mid) for mid in media_ids]
        return _categories_until_distinct(ordered_categories, min_distinct)
    except Exception as exc:
        log.warning("recent_posted_distinct_categories: failed (%s)", exc)
        return set()


def get_raw_media_for_create(category: str, tags: list[str] | None = None,
                             exclude_ids: list[str] | None = None,
                             strategy: str = "best") -> dict | None:
    """
    Pick one unposted raw media item matching category and optionally tags.
    strategy='best'   → highest hook_score, lifted by realized category performance
                        (Enhancement I) so proven categories win when tags are omitted
    strategy='random' → random from matching set (excluding exclude_ids)
    Tags are an optional secondary filter — omit to match any tags.
    """
    exclude_ids = exclude_ids or []
    if _use_supabase():
        def _fetch_raw():
            q = (
                get_supabase()
                .table("media")
                .select("*")
                .eq("status", "raw")
                .eq("media_type", "VIDEO")
                .eq("category", category)
                .eq("do_not_use", False)
            )
            if tags:
                q = q.contains("tags", tags)
            return q.execute().data or []
        rows = db_retry(_fetch_raw)
        rows = [r for r in rows if r["id"] not in exclude_ids]
        rows = _filter_by_quality(rows, where="create")
        if (get_setting("selection") or {}).get("require_classified", True):
            classified = [r for r in rows if _is_classified(r)]
            if classified:
                rows = classified
            else:
                log.info("create: require_classified skipped — no fully-classified candidates in %s", category)
        if not rows:
            return None
        if strategy == "random":
            import random
            return random.choice(rows)
        return _best_media(rows)
    # SQLite fallback — build WHERE dynamically based on whether tags are set
    where = "status='raw' AND media_type='VIDEO' AND category=? AND COALESCE(do_not_use, 0) = 0"
    params: list = [category]
    tags_clause, tags_params = _tags_where_sqlite(tags)
    where += tags_clause
    params.extend(tags_params)
    rows = query(f"SELECT * FROM media WHERE {where}", params)
    rows = [r for r in rows if r["id"] not in exclude_ids]
    rows = _filter_by_quality(rows, where="create")
    if (get_setting("selection") or {}).get("require_classified", True):
        classified = [r for r in rows if _is_classified(r)]
        if classified:
            rows = classified
        else:
            log.info("create: require_classified skipped — no fully-classified candidates in %s", category)
    if not rows:
        return None
    if strategy == "random":
        import random
        return random.choice(rows)
    return _best_media(rows)


def get_diverse_raw_media(exclude_ids: list[str], strategy: str = "random") -> dict | None:
    """
    Pick one unposted raw VIDEO clip across ALL categories, with category cooldown.

    Category cooldown (selection.category_cooldown_categories, default 20): skip a
    category until that many OTHER distinct categories have been posted since.
    Falls back to the full pool when the cooldown would leave nothing — never
    starves the queue. Respects require_classified and all quality-gate thresholds.
    """
    if _use_supabase():
        def _fetch_all():
            return (
                get_supabase()
                .table("media")
                .select("*")
                .eq("status", "raw")
                .eq("media_type", "VIDEO")
                .eq("do_not_use", False)
                .limit(5000)
                .execute()
            ).data or []
        rows = db_retry(_fetch_all)
    else:
        rows = query(
            "SELECT * FROM media WHERE status='raw' AND media_type='VIDEO' AND COALESCE(do_not_use, 0) = 0",
            [],
        )

    rows = [r for r in rows if r["id"] not in exclude_ids]
    rows = _filter_by_quality(rows, where="diverse")

    cfg = get_setting("selection") or {}
    if cfg.get("require_classified", True):
        classified = [r for r in rows if _is_classified(r)]
        if classified:
            rows = classified
        else:
            log.info("diverse: require_classified skipped — no fully-classified candidates")

    try:
        cooldown = int(float(cfg.get("category_cooldown_categories", 20)))
    except (TypeError, ValueError):
        cooldown = 20
    if cooldown > 0:
        used = recent_posted_distinct_categories(cooldown)
        if used:
            diverse = [r for r in rows if r.get("category") not in used]
            if diverse:
                rows = diverse
            else:
                log.info("diverse: category cooldown relaxed — all categories in cooldown window")

    if not rows:
        return None
    if strategy == "best":
        return _best_media(rows)
    import random
    return random.choice(rows)


def get_random_category_for_merge() -> str | None:
    """Randomly pick a category from the available raw VIDEO pool (quality-gated,
    require_classified-aware, weighted by clip count like get_diverse_raw_media),
    applying the same distinct-category cooldown so auto-create merge doesn't
    repeat a category too soon. Used by the daemon when
    pipeline.auto_create_reel_type='merge' and auto_create_category is unset."""
    if _use_supabase():
        def _fetch_all():
            return (
                get_supabase()
                .table("media")
                .select("*")
                .eq("status", "raw")
                .eq("media_type", "VIDEO")
                .eq("do_not_use", False)
                .limit(5000)
                .execute()
            ).data or []
        rows = db_retry(_fetch_all)
    else:
        rows = query(
            "SELECT * FROM media WHERE status='raw' AND media_type='VIDEO' AND COALESCE(do_not_use, 0) = 0",
            [],
        )

    rows = _filter_by_quality(rows, where="merge_category_pick")
    cfg = get_setting("selection") or {}
    if cfg.get("require_classified", True):
        classified = [r for r in rows if _is_classified(r)]
        if classified:
            rows = classified

    rows = [r for r in rows if r.get("category")]
    if not rows:
        return None

    try:
        cooldown = int(float(cfg.get("category_cooldown_categories", 20)))
    except (TypeError, ValueError):
        cooldown = 20
    if cooldown > 0:
        used = recent_posted_distinct_categories(cooldown)
        if used:
            diverse = [r for r in rows if r.get("category") not in used]
            if diverse:
                rows = diverse

    import random
    return random.choice(rows)["category"]


def get_category_raw_media(category: str, exclude_ids: list[str],
                           tags: list[str] | None = None,
                           strategy: str = "random",
                           source: str | None = None) -> dict | None:
    """Pick one unposted raw VIDEO clip within a SINGLE category for the merge
    montage. tags is an optional secondary filter — when omitted the pool mixes
    all tags across that category (the montage rule). Respects quality gates +
    require_classified, matching the other pickers.

    source narrows by provenance for the merge stock/local quota:
      "stock" → only source='stock' (Pexels/Pixabay B-roll)
      "local" → everything EXCEPT stock (archive/upload/highlight)
      None    → no provenance filter (default; backward-compatible).

    strategy='best' → hook_score-ranked; anything else → random (the default,
    which is what gives a varied montage)."""
    if _use_supabase():
        def _fetch():
            q = (
                get_supabase()
                .table("media")
                .select("*")
                .eq("status", "raw")
                .eq("media_type", "VIDEO")
                .eq("category", category)
                .eq("do_not_use", False)
            )
            if tags:
                q = q.contains("tags", tags)
            if source == "stock":
                q = q.eq("source", "stock")
            elif source == "local":
                q = q.neq("source", "stock")
            return q.limit(5000).execute().data or []
        rows = db_retry(_fetch)
    else:
        where = "status='raw' AND media_type='VIDEO' AND category=? AND COALESCE(do_not_use, 0) = 0"
        params: list = [category]
        tags_clause, tags_params = _tags_where_sqlite(tags)
        where += tags_clause
        params.extend(tags_params)
        if source == "stock":
            where += " AND source='stock'"
        elif source == "local":
            where += " AND COALESCE(source, '') != 'stock'"
        rows = query(f"SELECT * FROM media WHERE {where}", params)

    rows = [r for r in rows if r["id"] not in exclude_ids]
    rows = _filter_by_quality(rows, where="create")
    if (get_setting("selection") or {}).get("require_classified", True):
        classified = [r for r in rows if _is_classified(r)]
        if classified:
            rows = classified
        else:
            log.info("merge: require_classified skipped — no fully-classified candidates in %s", category)
    if not rows:
        return None
    if strategy == "best":
        return _best_media(rows)
    import random
    return random.choice(rows)


def count_raw_videos(category: str | None = None, tags: list[str] | None = None) -> int:
    """Count unposted raw VIDEO clips (do_not_use excluded) for the merge
    availability indicator. Mirrors get_category_raw_media's HARD filters
    (status=raw, media_type=VIDEO, not do_not_use) — an availability signal,
    not the exact post-quality-gate pool. Images/carousels never counted."""
    if _use_supabase():
        def _fetch():
            q = (
                get_supabase()
                .table("media")
                .select("id", count="exact")
                .eq("status", "raw")
                .eq("media_type", "VIDEO")
                .eq("do_not_use", False)
            )
            if category:
                q = q.eq("category", category)
            if tags:
                q = q.contains("tags", tags)
            return q.execute().count or 0
        return db_retry(_fetch)
    where = "status='raw' AND media_type='VIDEO' AND COALESCE(do_not_use, 0) = 0"
    params: list = []
    if category:
        where += " AND category=?"
        params.append(category)
    tags_clause, tags_params = _tags_where_sqlite(tags)
    where += tags_clause
    params.extend(tags_params)
    rows = query(f"SELECT COUNT(*) AS n FROM media WHERE {where}", params)
    if not rows:
        return 0
    row = rows[0]
    return int(row["n"] if isinstance(row, dict) else row[0])


def get_recent_merge_usage(category: str | None, limit_reels: int = 3) -> tuple[dict, list]:
    """Sub-shot memory for same-category merged reels (metadata-only, no cache).

    Returns (usage, proven):
      usage  = {source_id: [ {"start","dur","score","reel_rank"} ]} where reel_rank
               0 = the most recent reel, 1 = the next older, … — drives hard-exclude
               (within cooldown) vs soft-weight (past it) so a new reel avoids
               repeating the sub-shots recent reels already used.
      proven = flat [ {"src","start","dur","score"} ] across all parsed reels, sorted
               by score desc — the pool used to top up a thin fresh selection.

    Reads recent source='merge' rows' metadata.merge.cuts. Cuts written as dicts
    (src/start/dur/score) carry sub-shot detail; legacy reels with a bare [float,…]
    cuts list are skipped. metadata may be a dict (Supabase JSONB) or a JSON string
    (SQLite) — both handled. Never raises: returns ({}, []) on error / empty category."""
    if not category:
        return {}, []
    try:
        n = max(1, int(limit_reels)) * 2
        if _use_supabase():
            def _fetch():
                return (
                    get_supabase().table("media").select("metadata,created_at")
                    .eq("source", "merge").eq("category", category)
                    .order("created_at", desc=True).limit(n).execute().data
                ) or []
            rows = db_retry(_fetch)
        else:
            rows = query(
                "SELECT metadata FROM media WHERE source='merge' AND category=? "
                "ORDER BY created_at DESC LIMIT ?", (category, n)
            )
        usage: dict = {}
        proven: list = []
        for rank, r in enumerate(rows or []):
            meta = r.get("metadata") if isinstance(r, dict) else None
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    continue
            if not isinstance(meta, dict):
                continue
            cuts = ((meta.get("merge") or {}).get("cuts")) or []
            for c in cuts:
                if not isinstance(c, dict):
                    continue  # legacy bare-float cut — no sub-shot detail
                src = c.get("src")
                if not src:
                    continue
                try:
                    start = float(c.get("start") or 0.0)
                    dur = float(c.get("dur") or 0.0)
                    score = float(c.get("score") or 0.0)
                except Exception:
                    continue
                usage.setdefault(src, []).append(
                    {"start": start, "dur": dur, "score": score, "reel_rank": rank})
                proven.append({"src": src, "start": start, "dur": dur, "score": score})
        proven.sort(key=lambda x: x["score"], reverse=True)
        return usage, proven
    except Exception as exc:
        log.warning("get_recent_merge_usage failed for %s: %s", category, exc)
        return {}, []


# ── Captions ──

def save_caption(data):
    if not _use_supabase():
        return None
    return db_retry(lambda: get_supabase().table("captions").insert(data).execute().data)


def get_captions(media_id):
    if not _use_supabase():
        return []
    return db_retry(lambda: get_supabase().table("captions").select("*").eq("media_id", media_id).execute().data)


# ── Pipeline runs ──

def log_pipeline_run(stage, status="running", metadata=None):
    if not _use_supabase():
        return None
    data = {"stage": stage, "status": status}
    if metadata:
        data["metadata"] = metadata
    resp = db_retry(lambda: get_supabase().table("pipeline_runs").insert(data).execute())
    return resp.data[0] if resp.data else None


def update_pipeline_run(run_id, data):
    if not _use_supabase():
        return None
    return db_retry(lambda: get_supabase().table("pipeline_runs").update(data).eq("id", run_id).execute())


# ── Notifications ──

def create_notification(type, title, message=None):
    if not _use_supabase():
        return None
    return db_retry(lambda: get_supabase().table("notifications").insert({
        "type": type, "title": title, "message": message
    }).execute())


def get_notifications(unread_only=False, limit=20):
    if not _use_supabase():
        return []
    def _fetch():
        q = get_supabase().table("notifications").select("*")
        if unread_only:
            q = q.eq("read", False)
        return q.order("created_at", desc=True).limit(limit).execute().data
    return db_retry(_fetch)


# ── Settings (key/value JSON store, dual-mode) ──

def get_setting(key, default=None):
    if _use_supabase():
        resp = db_retry(lambda: get_supabase().table("settings").select("value").eq("key", key).maybe_single().execute())
        return resp.data["value"] if resp and resp.data else default
    rows = query("SELECT value FROM settings WHERE key=?", (key,))
    if not rows:
        return default
    try:
        return json.loads(rows[0]["value"])
    except (ValueError, TypeError):
        return rows[0]["value"]


def set_setting(key, value):
    now = datetime.now(timezone.utc).isoformat()
    if _use_supabase():
        return db_retry(lambda: get_supabase().table("settings").upsert(
            {"key": key, "value": value, "updated_at": now}
        ).execute().data)
    execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, json.dumps(value), now),
    )


def get_all_settings():
    if _use_supabase():
        resp = db_retry(lambda: get_supabase().table("settings").select("*").execute())
        return {r["key"]: r["value"] for r in resp.data}
    rows = query("SELECT key, value FROM settings")
    out = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except (ValueError, TypeError):
            out[r["key"]] = r["value"]
    return out


# ── Assets (Supabase only — indexes music/font/lut/intro/outro; mirrors the
# posts CRUD template above. Local disk stays the fast-serve path read
# directly by assets.py's per-type routes; this table is the admin/public-URL
# index kept in sync by assets_index.reconcile()) ──

def list_assets(type: str | None = None, favourite: bool | None = None,
                tag: str | None = None) -> list[dict]:
    """List `assets` rows, optionally filtered by type/favourite/tag
    (all optional, additive — existing call sites like `list_assets("music")`
    are unaffected). `tag` matches against the `tags` array column added in
    migration 015 (contains-one-element semantics); the former `pillars` column
    was merged into `tags` by migration 017."""
    if not _use_supabase():
        return []
    def _fetch():
        q = get_supabase().table("assets").select("*")
        if type:
            q = q.eq("type", type)
        if favourite is not None:
            q = q.eq("favourite", favourite)
        if tag:
            q = q.contains("tags", [tag])
        return q.order("name").execute().data
    return db_retry(_fetch)


def get_asset(asset_id: str) -> dict | None:
    if not _use_supabase():
        return None
    resp = db_retry(lambda: get_supabase().table("assets").select("*").eq("id", asset_id).maybe_single().execute())
    return resp.data if resp else None


def create_asset(row: dict) -> dict:
    if not _use_supabase():
        return {}
    data = db_retry(lambda: get_supabase().table("assets").insert(row).execute().data)
    return (data or [None])[0] or {}


def update_asset(asset_id: str, patch: dict) -> dict | None:
    if not _use_supabase():
        return None
    data = db_retry(lambda: get_supabase().table("assets").update(patch).eq("id", asset_id).execute().data)
    return (data or [None])[0]


def delete_asset(asset_id: str) -> bool:
    if not _use_supabase():
        return False
    db_retry(lambda: get_supabase().table("assets").delete().eq("id", asset_id).execute())
    return True


def bulk_upsert_assets(rows: list[dict]) -> None:
    """Upsert many `assets` rows in one round-trip (conflict on primary key
    `id`). Used by music_fetcher's list_all_tracks() mirror hook so the whole
    flat-cache track list can be synced in a single call instead of N. No-op
    when Supabase isn't configured or *rows* is empty."""
    if not rows or not _use_supabase():
        return
    db_retry(lambda: get_supabase().table("assets").upsert(rows).execute())


def increment_asset_usage(asset_id: str) -> None:
    """Best-effort usage_count bump + last_used_at touch on an `assets` row
    (migration 015 columns). Called from FFmpeg render paths (music pick, LUT
    apply, font/intro/outro overlay) that must never fail because of an
    analytics increment — never raises, no-op when Supabase isn't configured
    or *asset_id* is falsy."""
    if not asset_id or not _use_supabase():
        return
    try:
        current = db_retry(
            lambda: get_supabase().table("assets").select("usage_count")
            .eq("id", asset_id).maybe_single().execute()
        )
        count = ((current.data or {}).get("usage_count") or 0) if current else 0
        db_retry(lambda: get_supabase().table("assets").update({
            "usage_count": count + 1,
            "last_used_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", asset_id).execute())
    except Exception as exc:
        log.warning("increment_asset_usage: failed for %s (non-fatal): %s", asset_id, exc)


# ── Edit projects (Supabase only — versioned Reel Editor EDL documents,
# migration 016; mirrors the assets CRUD block above). Posts are already
# Supabase-only in this codebase, and the editor always operates on a post's
# reel, so there is no SQLite fallback: every function below degrades to
# None/[]/False when Supabase isn't configured, and the editor routes surface
# that as "no saved version" → hydrate from metadata.merge instead. ──

def list_edit_projects(media_id: str, limit: int | None = None) -> list[dict]:
    """All saved EDL versions for one reel, newest version first. Returns [] when
    Supabase isn't configured."""
    if not _use_supabase():
        return []
    def _fetch():
        q = (get_supabase().table("edit_projects").select("*")
             .eq("media_id", media_id).order("version", desc=True))
        if limit:
            q = q.limit(limit)
        return q.execute().data
    return db_retry(_fetch)


def get_edit_project(project_id: str) -> dict | None:
    """One EDL version row by primary key. None when Supabase isn't configured."""
    if not _use_supabase():
        return None
    resp = db_retry(lambda: get_supabase().table("edit_projects").select("*").eq("id", project_id).maybe_single().execute())
    return resp.data if resp else None


def get_latest_edit_project(media_id: str) -> dict | None:
    """Highest-version EDL row for a reel — what the editor reopens. None when
    the reel has never been saved, or when Supabase isn't configured."""
    if not _use_supabase():
        return None
    data = db_retry(lambda: (
        get_supabase().table("edit_projects").select("*")
        .eq("media_id", media_id).order("version", desc=True).limit(1).execute().data
    ))
    return (data or [None])[0]


def get_edit_project_version(media_id: str, version: int) -> dict | None:
    """One EDL row addressed the way the UI thinks about it — (reel, version
    number) rather than a row id — for the version picker's "load this one".
    None when Supabase isn't configured or that version was pruned."""
    if not _use_supabase():
        return None
    data = db_retry(lambda: (
        get_supabase().table("edit_projects").select("*")
        .eq("media_id", media_id).eq("version", int(version)).limit(1).execute().data
    ))
    return (data or [None])[0]


def create_edit_project(row: dict) -> dict:
    """Insert one EDL version row (caller computes `version`). Returns the stored
    row, or {} when Supabase isn't configured."""
    if not _use_supabase():
        return {}
    data = db_retry(lambda: get_supabase().table("edit_projects").insert(row).execute().data)
    return (data or [None])[0] or {}


def delete_edit_project(project_id: str) -> bool:
    """Delete one EDL version row. False when Supabase isn't configured."""
    if not _use_supabase():
        return False
    db_retry(lambda: get_supabase().table("edit_projects").delete().eq("id", project_id).execute())
    return True


def prune_edit_projects(media_id: str, keep: int) -> int:
    """Trim a reel's saved EDL history to the *keep* newest versions (settings
    key editor.keep_versions). Returns the number of rows deleted; 0 when
    Supabase isn't configured or nothing is over the cap."""
    if not _use_supabase() or keep <= 0:
        return 0
    rows = list_edit_projects(media_id) or []
    stale = rows[keep:]
    for r in stale:
        try:
            delete_edit_project(r["id"])
        except Exception as exc:
            log.warning("prune_edit_projects: failed to delete %s (non-fatal): %s", r.get("id"), exc)
    return len(stale)
