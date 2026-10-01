"""
DB single-row lookup regression tests (v0.9.5).

Root cause of the v0.9.5 reject 500: get_post_by_id / get_media_by_id used
PostgREST .single(), which raises APIError PGRST116 ("Cannot coerce the result
to a single JSON object") on 0 rows. A stale/already-deleted id therefore 500'd
the route instead of producing a clean 404. These tests pin the fix: the lookups
now use .maybe_single() and return None on 0 rows WITHOUT raising.
"""
from unittest.mock import MagicMock, patch

import backend.db as db


def _fake_supabase(maybe_single_result):
    """Build a supabase client mock whose chain ends at maybe_single().execute()."""
    client = MagicMock()
    builder = MagicMock()
    client.table.return_value = builder
    builder.select.return_value = builder
    builder.eq.return_value = builder
    builder.maybe_single.return_value = builder
    builder.single.side_effect = AssertionError("should use maybe_single(), not single()")
    builder.execute.return_value = maybe_single_result
    return client


def test_get_post_by_id_returns_none_on_zero_rows():
    # maybe_single() returns a response with data=None on 0 rows (no raise).
    resp = MagicMock(data=None)
    with patch.object(db, "_use_supabase", return_value=True), \
         patch.object(db, "get_supabase", return_value=_fake_supabase(resp)):
        assert db.get_post_by_id("missing-id") is None


def test_get_post_by_id_returns_row_when_found():
    resp = MagicMock(data={"id": "p1", "status": "preview"})
    with patch.object(db, "_use_supabase", return_value=True), \
         patch.object(db, "get_supabase", return_value=_fake_supabase(resp)):
        row = db.get_post_by_id("p1")
    assert row == {"id": "p1", "status": "preview"}


def test_get_post_by_id_handles_none_response():
    # Some postgrest versions return None (not a response) from maybe_single on 0 rows.
    with patch.object(db, "_use_supabase", return_value=True), \
         patch.object(db, "get_supabase", return_value=_fake_supabase(None)):
        assert db.get_post_by_id("missing-id") is None


def test_get_media_by_id_returns_none_on_zero_rows():
    resp = MagicMock(data=None)
    with patch.object(db, "_use_supabase", return_value=True), \
         patch.object(db, "get_supabase", return_value=_fake_supabase(resp)):
        assert db.get_media_by_id("missing-id") is None


def test_get_media_by_id_returns_row_when_found():
    resp = MagicMock(data={"id": "m1", "media_type": "VIDEO"})
    with patch.object(db, "_use_supabase", return_value=True), \
         patch.object(db, "get_supabase", return_value=_fake_supabase(resp)):
        row = db.get_media_by_id("m1")
    assert row == {"id": "m1", "media_type": "VIDEO"}


# ── db_retry transient handling (v0.9.6 daemon crash fix) ─────────────


class _LocalProtocolError(Exception):
    """Stand-in matching httpx.LocalProtocolError by class name."""


def test_db_retry_recovers_from_local_protocol_error():
    # "Received pseudo-header in trailer" corrupts a reused HTTP/2 client. db_retry
    # must treat LocalProtocolError as transient: reset the client and retry.
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _LocalProtocolError("Received pseudo-header in trailer {b':path'}")
        return "ok"

    with patch.object(db, "_reset_supabase") as reset:
        assert db.db_retry(fn) == "ok"
    assert calls["n"] == 2
    reset.assert_called()


def test_db_retry_reraises_non_transient():
    def fn():
        raise ValueError("boom")

    try:
        db.db_retry(fn)
        assert False, "should have raised"
    except ValueError:
        pass
