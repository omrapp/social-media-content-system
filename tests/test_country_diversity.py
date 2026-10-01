"""
Category-diversity regression tests (fix: merge/diverse auto-pick repeating
the same category).

- db._categories_until_distinct: pure walk-back helper
- db.recent_posted_distinct_categories: Supabase-backed wrapper
- db.get_diverse_raw_media / db.get_random_category_for_merge: use the
  distinct-category cooldown so auto-pick doesn't repeat a category too soon
"""
from unittest.mock import MagicMock, patch

import backend.db as db


# ── _categories_until_distinct (pure) ───────────────────────────────────────

def test_until_distinct_stops_as_soon_as_n_unique_seen():
    # "food" repeats 3x before "culture" shows up — should NOT count as 2
    # distinct after only 2 posts; must walk past the repeats to reach 2 distinct.
    ordered = ["food", "food", "food", "culture", "nature"]
    assert db._categories_until_distinct(ordered, 2) == {"food", "culture"}


def test_until_distinct_returns_fewer_when_list_runs_out():
    ordered = ["food", "culture"]
    assert db._categories_until_distinct(ordered, 20) == {"food", "culture"}


def test_until_distinct_skips_falsy_entries():
    ordered = [None, "food", "", "culture"]
    assert db._categories_until_distinct(ordered, 2) == {"food", "culture"}


def test_until_distinct_empty_list():
    assert db._categories_until_distinct([], 20) == set()


# ── recent_posted_distinct_categories (Supabase-backed) ─────────────────────

def _fake_supabase(posts_data, media_data):
    """Chain-mock: .table('posts')...execute() then .table('media')...execute()."""
    client = MagicMock()
    posts_builder = MagicMock()
    media_builder = MagicMock()

    def table(name):
        return posts_builder if name == "posts" else media_builder

    client.table.side_effect = table
    for b in (posts_builder, media_builder):
        b.select.return_value = b
        b.in_.return_value = b
        b.order.return_value = b
        b.limit.return_value = b
    posts_builder.execute.return_value = MagicMock(data=posts_data)
    media_builder.execute.return_value = MagicMock(data=media_data)
    return client


def test_recent_posted_distinct_categories_walks_past_repeats():
    # Most-recent-first order: food, food, culture, nature — asking for 2
    # distinct should stop at {food, culture}, not need all 4 rows.
    posts = [{"media_id": "m1"}, {"media_id": "m2"}, {"media_id": "m3"}, {"media_id": "m4"}]
    media = [
        {"id": "m1", "category": "food"},
        {"id": "m2", "category": "food"},
        {"id": "m3", "category": "culture"},
        {"id": "m4", "category": "nature"},
    ]
    with patch.object(db, "_use_supabase", return_value=True), \
         patch.object(db, "get_supabase", return_value=_fake_supabase(posts, media)):
        assert db.recent_posted_distinct_categories(2) == {"food", "culture"}


def test_recent_posted_distinct_categories_zero_is_noop():
    assert db.recent_posted_distinct_categories(0) == set()


def test_recent_posted_distinct_categories_sqlite_is_noop():
    with patch.object(db, "_use_supabase", return_value=False):
        assert db.recent_posted_distinct_categories(20) == set()


def test_recent_posted_distinct_categories_swallows_errors():
    with patch.object(db, "_use_supabase", return_value=True), \
         patch.object(db, "get_supabase", side_effect=RuntimeError("boom")):
        assert db.recent_posted_distinct_categories(20) == set()


# ── auto-pickers use the distinct-category cooldown ─────────────────────────

def _row(category, id_="m1"):
    return {"id": id_, "category": category, "hook_score": 0.5,
            "media_type": "VIDEO"}


def test_get_diverse_raw_media_returns_a_row():
    rows = [_row("food", "m1")]
    with patch.object(db, "_use_supabase", return_value=True), \
         patch.object(db, "db_retry", return_value=rows), \
         patch.object(db, "_filter_by_quality", side_effect=lambda r, where=None: r), \
         patch.object(db, "get_setting", return_value={"require_classified": False, "category_cooldown_categories": 0}):
        picked = db.get_diverse_raw_media(exclude_ids=[])
    assert picked is not None
    assert picked["category"] == "food"


def test_get_random_category_for_merge_none_when_no_category():
    rows = [_row(None, "m1")]
    with patch.object(db, "_use_supabase", return_value=True), \
         patch.object(db, "db_retry", return_value=rows), \
         patch.object(db, "_filter_by_quality", side_effect=lambda r, where=None: r), \
         patch.object(db, "get_setting", return_value={"require_classified": False, "category_cooldown_categories": 0}):
        assert db.get_random_category_for_merge() is None


def test_get_random_category_for_merge_uses_distinct_cooldown_setting():
    rows = [_row("food", "m1"), _row("culture", "m2")]
    with patch.object(db, "_use_supabase", return_value=True), \
         patch.object(db, "db_retry", return_value=rows), \
         patch.object(db, "_filter_by_quality", side_effect=lambda r, where=None: r), \
         patch.object(db, "get_setting", return_value={"require_classified": False, "category_cooldown_categories": 20}), \
         patch.object(db, "recent_posted_distinct_categories", return_value={"food"}) as recent:
        category = db.get_random_category_for_merge()
    recent.assert_called_once_with(20)
    assert category == "culture"
