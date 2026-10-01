"""
Tests for POST /api/media/{id}/enhance endpoint:
- 404 when media not found
- 400 when media is IMAGE (not VIDEO)
- 500 when enhance_single returns error
- 200 with result on success
"""
import pytest
from unittest.mock import patch, MagicMock


FAKE_VIDEO_MEDIA = {
    "id": "media_abc",
    "media_type": "VIDEO",
    "reel_ready_path": "/tmp/fake_9x16.mp4",
    "status": "resized",
}

FAKE_IMAGE_MEDIA = {
    "id": "media_img",
    "media_type": "IMAGE",
    "reel_ready_path": None,
    "status": "resized",
}


def test_enhance_404_when_media_not_found(client, auth_headers):
    with patch("backend.api.routes.media.get_media_by_id", return_value=None):
        resp = client.post(
            "/api/media/nonexistent/enhance",
            json={"remove_watermarks": True, "watermark_position": "bottom", "stabilize": False},
            headers=auth_headers,
        )
    assert resp.status_code == 404


def test_enhance_400_for_image_media(client, auth_headers):
    with patch("backend.api.routes.media.get_media_by_id", return_value=FAKE_IMAGE_MEDIA):
        resp = client.post(
            "/api/media/media_img/enhance",
            json={"remove_watermarks": True, "watermark_position": "bottom", "stabilize": False},
            headers=auth_headers,
        )
    assert resp.status_code == 400
    assert "VIDEO" in resp.json().get("detail", "")


def test_enhance_500_when_enhance_fails(client, auth_headers):
    error_result = {"status": "error", "reason": "ffmpeg_failed", "id": "media_abc"}
    with patch("backend.api.routes.media.get_media_by_id", return_value=FAKE_VIDEO_MEDIA), \
         patch("backend.pipeline.enhance_video.enhance_single", return_value=error_result):
        resp = client.post(
            "/api/media/media_abc/enhance",
            json={"remove_watermarks": True, "watermark_position": "bottom", "stabilize": False},
            headers=auth_headers,
        )
    assert resp.status_code == 500
    assert "ffmpeg_failed" in resp.json().get("detail", "")


def test_enhance_200_on_success(client, auth_headers):
    ok_result = {"status": "enhanced", "output": "/tmp/media_abc_enhanced.mp4", "id": "media_abc"}
    updated_media = {**FAKE_VIDEO_MEDIA, "status": "enhanced", "reel_ready_path": ok_result["output"]}

    with patch("backend.api.routes.media.get_media_by_id", side_effect=[FAKE_VIDEO_MEDIA, updated_media]), \
         patch("backend.pipeline.enhance_video.enhance_single", return_value=ok_result):
        resp = client.post(
            "/api/media/media_abc/enhance",
            json={"remove_watermarks": True, "watermark_position": "bottom", "stabilize": False},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["reel_ready_path"] == ok_result["output"]
    assert data["media"]["status"] == "enhanced"


def test_enhance_default_body_no_stabilize(client, auth_headers):
    """Default body: stabilize=False (fast re-enhance path)."""
    ok_result = {"status": "enhanced", "output": "/tmp/out.mp4", "id": "media_abc"}
    updated_media = {**FAKE_VIDEO_MEDIA, "status": "enhanced"}
    captured = {}

    def capture_enhance(item, settings):
        captured["settings"] = settings
        return ok_result

    with patch("backend.api.routes.media.get_media_by_id", side_effect=[FAKE_VIDEO_MEDIA, updated_media]), \
         patch("backend.pipeline.enhance_video.enhance_single", side_effect=capture_enhance):
        resp = client.post(
            "/api/media/media_abc/enhance",
            json={},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert captured["settings"]["stabilize"] is False


def test_enhance_watermark_position_forwarded(client, auth_headers):
    """watermark_position in request body is forwarded to enhance_single."""
    ok_result = {"status": "enhanced", "output": "/tmp/out.mp4", "id": "media_abc"}
    updated_media = {**FAKE_VIDEO_MEDIA, "status": "enhanced"}
    captured = {}

    def capture_enhance(item, settings):
        captured["settings"] = settings
        return ok_result

    with patch("backend.api.routes.media.get_media_by_id", side_effect=[FAKE_VIDEO_MEDIA, updated_media]), \
         patch("backend.pipeline.enhance_video.enhance_single", side_effect=capture_enhance):
        resp = client.post(
            "/api/media/media_abc/enhance",
            json={"watermark_position": "both", "remove_watermarks": True},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert captured["settings"]["watermark_position"] == "both"
    assert captured["settings"]["remove_watermarks"] is True
