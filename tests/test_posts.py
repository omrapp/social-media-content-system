"""
Tests for posts API routes:
- GET /api/posts — returns list
- POST /api/posts — create with auto-platforms
- POST /{id}/approve — publishes immediately to all enabled platforms
- POST /{id}/cancel — soft-cancel (status=cancelled, media kept)
- POST /{id}/reject — hard-delete (post + media + files purged)
- POST /{id}/reschedule — sets new time + publish_after
- POST /{id}/publish — immediate publish (alias for approve)
- POST /create — 404 when no story episode found
- POST /create — 400 when strategy=best missing fields
- POST /auto-schedule — empty list → 0 scheduled
- POST /{id}/retry-youtube — 404 when post not found
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock


FAKE_POST = {
    "id": "post_abc",
    "media_id": "media_xyz",
    "status": "preview",
    "caption": "Test caption",
    "platforms": ["instagram"],
    "slot_at": None,
    "publish_after": "2027-01-01T00:00:00+00:00",
}

FAKE_MEDIA = {
    "id": "media_xyz",
    "media_type": "VIDEO",
    "status": "resized",
    "caption": "",
    "reel_ready_path": "/tmp/clip.mp4",
}


# ── GET /api/posts ─────────────────────────────────────────────────────────────

def test_list_posts_returns_list(client, auth_headers):
    with patch("backend.api.routes.posts.get_posts", return_value=[]):
        resp = client.get("/api/posts", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_list_posts_with_status_filter(client, auth_headers):
    with patch("backend.api.routes.posts.get_posts", return_value=[FAKE_POST]) as mock_gp:
        resp = client.get("/api/posts?status=preview", headers=auth_headers)
    assert resp.status_code == 200
    mock_gp.assert_called_once()
    call_kwargs = mock_gp.call_args
    filters = (call_kwargs.args[0] if call_kwargs.args else None) or (call_kwargs.kwargs.get("filters"))
    assert filters and filters.get("status") == "preview"


# ── POST /api/posts ────────────────────────────────────────────────────────────

def test_create_post_injects_default_platforms(client, auth_headers):
    new_post = {**FAKE_POST, "platforms": ["instagram"]}
    with patch("backend.api.routes.posts.get_media_by_id", return_value=FAKE_MEDIA), \
         patch("backend.api.routes.posts.create_post", return_value=new_post), \
         patch("backend.pipeline.scheduler._default_platforms", return_value=["instagram"]):
        resp = client.post(
            "/api/posts",
            json={"media_id": "media_xyz"},
            headers=auth_headers,
        )
    assert resp.status_code == 200


def test_create_post_404_when_media_missing(client, auth_headers):
    with patch("backend.api.routes.posts.get_media_by_id", return_value=None):
        resp = client.post(
            "/api/posts",
            json={"media_id": "nonexistent"},
            headers=auth_headers,
        )
    assert resp.status_code == 404


# ── POST /{id}/approve ─────────────────────────────────────────────────────────

def test_approve_publishes_immediately(client, auth_headers):
    with patch("backend.api.routes.posts.get_post_by_id", return_value=FAKE_POST), \
         patch("backend.pipeline.scheduler.publish_post", return_value={"instagram": "ig_1"}), \
         patch("backend.api.routes.posts.update_post") as mock_up, \
         patch("backend.api.routes.posts.broadcast_post_status"):
        resp = client.post("/api/posts/post_abc/approve", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "publishing"
    # Post is flipped out of 'preview' so the daemon won't double-publish.
    first_call = mock_up.call_args_list[0][0]
    assert first_call[0] == "post_abc"
    assert first_call[1]["status"] == "publishing"


def test_approve_404_when_post_missing(client, auth_headers):
    with patch("backend.api.routes.posts.get_post_by_id", return_value=None):
        resp = client.post("/api/posts/post_abc/approve", headers=auth_headers)
    assert resp.status_code == 404


# ── POST /{id}/cancel ──────────────────────────────────────────────────────────

def test_cancel_sets_cancelled(client, auth_headers):
    fake_post = {"id": "post_abc", "media_id": "media_xyz"}
    with patch("backend.api.routes.posts.get_post_by_id", return_value=fake_post), \
         patch("backend.api.routes.posts.update_post") as mock_up, \
         patch("backend.api.routes.posts.update_media"), \
         patch("backend.api.routes.posts.broadcast_post_status"):
        resp = client.post("/api/posts/post_abc/cancel", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"
    mock_up.assert_called_once_with("post_abc", {"status": "cancelled"})


# ── POST /{id}/reject ──────────────────────────────────────────────────────────

def test_reject_hard_deletes(client, auth_headers):
    """Reject permanently purges: post deleted, media marked deleted, files removed."""
    with patch("backend.api.routes.posts.get_post_by_id", return_value=FAKE_POST), \
         patch("backend.api.routes.posts.get_media_by_id", return_value=FAKE_MEDIA), \
         patch("backend.api.routes.posts.delete_post") as mock_del, \
         patch("backend.api.routes.posts.update_status") as mock_status, \
         patch("backend.api.routes.posts.broadcast_post_status"):
        resp = client.post("/api/posts/post_abc/reject", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "deleted"
    mock_del.assert_called_once_with("post_abc")
    mock_status.assert_called_once_with("media_xyz", "deleted")


def test_reject_404_when_post_missing(client, auth_headers):
    with patch("backend.api.routes.posts.get_post_by_id", return_value=None):
        resp = client.post("/api/posts/nonexistent/reject", headers=auth_headers)
    assert resp.status_code == 404


# ── POST /{id}/reschedule ──────────────────────────────────────────────────────

def test_reschedule_sets_new_time(client, auth_headers):
    new_time = "2026-06-07T08:00:00+00:00"
    with patch("backend.api.routes.posts.update_post") as mock_up, \
         patch("backend.api.routes.posts.broadcast_post_status"):
        resp = client.post(
            "/api/posts/post_abc/reschedule",
            json={"scheduled_at": new_time, "window_minutes": 60},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "scheduled_at" in data
    mock_up.assert_called_once()
    update_data = mock_up.call_args[0][1]
    assert "publish_after" in update_data
    assert update_data["status"] == "preview"


# ── POST /{id}/publish ─────────────────────────────────────────────────────────

def test_publish_now_publishes_immediately(client, auth_headers):
    with patch("backend.api.routes.posts.get_post_by_id", return_value=FAKE_POST), \
         patch("backend.pipeline.scheduler.publish_post", return_value={"instagram": "ig_1"}), \
         patch("backend.api.routes.posts.update_post") as mock_up, \
         patch("backend.api.routes.posts.broadcast_post_status"):
        resp = client.post("/api/posts/post_abc/publish", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "publishing"
    first_call = mock_up.call_args_list[0][0]
    assert first_call[1]["status"] == "publishing"


def test_publish_now_404_when_post_missing(client, auth_headers):
    with patch("backend.api.routes.posts.get_post_by_id", return_value=None):
        resp = client.post("/api/posts/post_abc/publish", headers=auth_headers)
    assert resp.status_code == 404


# ── POST /create ───────────────────────────────────────────────────────────────

def test_create_from_filter_400_story_removed(client, auth_headers):
    resp = client.post(
        "/api/posts/create",
        json={"strategy": "story"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "story" in resp.json().get("detail", "").lower()


def test_create_from_filter_400_best_missing_fields(client, auth_headers):
    # Pin merge OFF: with merge auto_run enabled the create endpoint intercepts
    # every request as a montage (200 merge_started) before the best/random
    # field validation, so the assertion must isolate the merge gate to be
    # deterministic regardless of the settings DB state.
    with patch("backend.api.routes.posts.get_setting", return_value={}):
        resp = client.post(
            "/api/posts/create",
            json={"strategy": "best"},  # missing category
            headers=auth_headers,
        )
    assert resp.status_code == 400
    assert "category" in resp.json().get("detail", "")


def test_create_from_filter_starts_pipeline(client, auth_headers):
    """diverse strategy: media found → pipeline task started → 200 returned immediately."""
    async def _noop(*args, **kwargs):
        pass

    with patch("backend.api.routes.posts.get_setting", return_value={}), \
         patch("backend.api.routes.posts._pick_media_for_create", return_value=FAKE_MEDIA), \
         patch("backend.api.routes.posts._pipeline_and_enqueue", side_effect=_noop):
        resp = client.post(
            "/api/posts/create",
            json={"strategy": "diverse"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pipeline_started"
    assert data["media_id"] == FAKE_MEDIA["id"]


# ── POST /auto-schedule ────────────────────────────────────────────────────────

def test_auto_schedule_empty_list(client, auth_headers):
    resp = client.post(
        "/api/posts/auto-schedule",
        json={"media_ids": []},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scheduled"] == 0
    assert data["posts"] == []


def test_auto_schedule_skips_missing_media(client, auth_headers):
    slot = datetime(2026, 6, 6, 8, 0, 0, tzinfo=timezone.utc)
    with patch("backend.api.routes.posts.get_media_by_id", return_value=None), \
         patch("backend.pipeline.slots.next_free_slot", return_value=slot):
        resp = client.post(
            "/api/posts/auto-schedule",
            json={"media_ids": ["nonexistent"]},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert resp.json()["scheduled"] == 0


# ── POST /{id}/retry-youtube ───────────────────────────────────────────────────

def test_retry_youtube_404_when_post_not_found(client, auth_headers):
    with patch("backend.api.routes.posts.get_post_by_id", return_value=None):
        resp = client.post("/api/posts/nonexistent/retry-youtube", headers=auth_headers)
    assert resp.status_code == 404


def test_retry_youtube_404_when_media_not_found(client, auth_headers):
    with patch("backend.api.routes.posts.get_post_by_id", return_value=FAKE_POST), \
         patch("backend.api.routes.posts.get_media_by_id", return_value=None):
        resp = client.post("/api/posts/post_abc/retry-youtube", headers=auth_headers)
    assert resp.status_code == 404


def test_retry_youtube_400_no_reel_path_or_r2(client, auth_headers):
    media_no_files = {**FAKE_MEDIA, "r2_url": None, "reel_ready_path": None}
    with patch("backend.api.routes.posts.get_post_by_id", return_value=FAKE_POST), \
         patch("backend.api.routes.posts.get_media_by_id", return_value=media_no_files):
        resp = client.post("/api/posts/post_abc/retry-youtube", headers=auth_headers)
    assert resp.status_code == 400
    assert "reel_ready_path" in resp.json().get("detail", "")
