"""TikTok Content Posting API v2 — Direct Post (PULL_FROM_URL or FILE_UPLOAD)."""

import logging
import time

import httpx

log = logging.getLogger(__name__)

_API_BASE = "https://open.tiktokapis.com/v2"


def _headers() -> dict:
    from backend.config import TIKTOK_ACCESS_TOKEN
    if not TIKTOK_ACCESS_TOKEN:
        raise RuntimeError("TIKTOK_ACCESS_TOKEN not configured — run backend/scripts/auth_tiktok.py")
    return {
        "Authorization": f"Bearer {TIKTOK_ACCESS_TOKEN}",
        "Content-Type": "application/json; charset=UTF-8",
    }


def _build_caption(caption: str, hashtags: list[str]) -> str:
    tags = " ".join(f"#{t.lstrip('#')}" for t in hashtags[:5])
    body = caption.split("\n")[0][:2100].strip()
    return f"{body} {tags}".strip() if tags else body


def _poll_status(publish_id: str) -> None:
    terminal_failures = {
        "FAILED", "SPAM_RISK_TOO_MANY_POSTS", "SPAM_RISK_USER_BANNED_FROM_POSTING",
        "AUDITION_FAILED", "INTERNAL_ERROR",
    }
    for _ in range(24):  # up to 2 min
        resp = httpx.post(
            f"{_API_BASE}/post/publish/status/fetch/",
            headers=_headers(),
            json={"publish_id": publish_id},
            timeout=15,
        ).json()
        status = resp.get("data", {}).get("status", "")
        log.debug("TikTok publish_id=%s status=%s", publish_id, status)
        if status == "PUBLISH_COMPLETE":
            return
        if status in terminal_failures:
            raise RuntimeError(f"TikTok publish failed: status={status} response={resp}")
        time.sleep(5)
    raise TimeoutError(f"TikTok publish timed out for publish_id={publish_id}")


def _post_info(caption_text: str) -> dict:
    return {
        "title": caption_text[:150],
        "privacy_level": "PUBLIC_TO_EVERYONE",
        "disable_duet": False,
        "disable_comment": False,
        "disable_stitch": False,
        "video_cover_timestamp_ms": 1000,
    }


def _init_pull_from_url(url: str, caption_text: str) -> str:
    resp = httpx.post(
        f"{_API_BASE}/post/publish/video/init/",
        headers=_headers(),
        json={
            "post_info": _post_info(caption_text),
            "source_info": {"source": "PULL_FROM_URL", "video_url": url},
        },
        timeout=30,
    ).json()
    if resp.get("error", {}).get("code", "ok") != "ok":
        raise RuntimeError(f"TikTok init (PULL_FROM_URL) failed: {resp}")
    return resp["data"]["publish_id"]


def _init_file_upload(video_path: str, caption_text: str) -> tuple[str, str]:
    from pathlib import Path
    file_size = Path(video_path).stat().st_size
    resp = httpx.post(
        f"{_API_BASE}/post/publish/video/init/",
        headers=_headers(),
        json={
            "post_info": _post_info(caption_text),
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,
                "total_chunk_count": 1,
            },
        },
        timeout=30,
    ).json()
    if resp.get("error", {}).get("code", "ok") != "ok":
        raise RuntimeError(f"TikTok init (FILE_UPLOAD) failed: {resp}")
    data = resp["data"]
    return data["publish_id"], data["upload_url"]


def upload_short(media: dict, caption: str, hashtags_en: list[str]) -> str:
    """
    Post a video to TikTok via Direct Post API.
    Prefers PULL_FROM_URL (R2 url) over FILE_UPLOAD.
    Returns publish_id.
    """
    caption_text = _build_caption(caption, hashtags_en)

    r2_url = media.get("r2_url") or ""
    if r2_url:
        publish_id = _init_pull_from_url(r2_url, caption_text)
        _poll_status(publish_id)
        log.info("TikTok published via PULL_FROM_URL: publish_id=%s", publish_id)
        return publish_id

    from pathlib import Path
    video_path = media.get("reel_ready_path") or ""
    if not video_path or not Path(video_path).exists():
        raise ValueError(f"No R2 URL or local video path for media {media.get('id')}")

    publish_id, upload_url = _init_file_upload(video_path, caption_text)
    file_size = Path(video_path).stat().st_size
    with open(video_path, "rb") as f:
        video_bytes = f.read()

    put_resp = httpx.put(
        upload_url,
        content=video_bytes,
        headers={
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
            "Content-Length": str(file_size),
        },
        timeout=300,
    )
    if put_resp.status_code not in (200, 201, 206):
        raise RuntimeError(f"TikTok upload PUT failed: HTTP {put_resp.status_code}: {put_resp.text[:200]}")

    _poll_status(publish_id)
    log.info("TikTok published via FILE_UPLOAD: publish_id=%s", publish_id)
    return publish_id
