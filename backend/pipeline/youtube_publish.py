"""YouTube Shorts publisher — uploads vertical video via Data API v3."""

import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

_MAX_TITLE = 97  # leave room for " #Shorts"
_YT_DESC_LIMIT = 4900  # YouTube description hard limit ~5000; leave buffer


def _truncate_yt_description(text: str, limit: int = _YT_DESC_LIMIT) -> str:
    """
    Ensure description fits within YouTube's limit.
    Always appends '\\n#Shorts' suffix; truncates narrative body if needed.
    """
    suffix = "\n#Shorts"
    if "#Shorts" in text or "#shorts" in text:
        # Already contains #Shorts — just hard-truncate.
        return text[:limit]
    available = limit - len(suffix)
    if len(text) <= available:
        return text + suffix
    # Truncate at a paragraph boundary if possible, then add ellipsis.
    cut = available - 3
    truncated = text[:cut]
    last_para = truncated.rfind("\n\n")
    if last_para > cut // 2:
        truncated = text[:last_para]
    return truncated.rstrip() + "..." + suffix


def _find_or_create_playlist(yt, category: str) -> str | None:
    """
    Return the YouTube playlist id for *category*, creating it if it doesn't exist.
    Caches the mapping in the 'youtube_playlists' settings group.
    Non-fatal: returns None on any error.
    """
    category = (category or "").strip().title()
    if not category:
        log.warning("YouTube playlist skipped: media.category is empty")
        return None
    try:
        from backend.db import get_setting, set_setting
        cache: dict = get_setting("youtube_playlists") or {}
        playlist_id = cache.get(category)
        if playlist_id:
            return playlist_id

        # List existing playlists (up to 50) and match by title (case-insensitive).
        playlist_title = category
        resp = yt.playlists().list(
            part="snippet", mine=True, maxResults=50
        ).execute()
        for item in resp.get("items", []):
            existing_title = item.get("snippet", {}).get("title", "")
            if existing_title.lower() == playlist_title.lower():
                playlist_id = item["id"]
                log.info("YouTube playlist matched existing %r → %s", playlist_title, playlist_id)
                break

        if not playlist_id:
            create_resp = yt.playlists().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": playlist_title,
                        "description": f"Shorts — {category}",
                    },
                    "status": {"privacyStatus": "public"},
                },
            ).execute()
            playlist_id = create_resp["id"]
            log.info("YouTube playlist created for %r: %s", category, playlist_id)

        cache[category] = playlist_id
        set_setting("youtube_playlists", cache)
        return playlist_id
    except Exception as exc:
        log.error("YouTube _find_or_create_playlist failed for %r: %s — check OAuth scope (need auth/youtube, not just youtube.upload)", category, exc)
        try:
            from backend.db import create_notification
            create_notification("error", "YouTube playlist failed", f"Category: {category} — {exc}")
        except Exception:
            pass
        return None


def _add_to_playlist(yt, playlist_id: str, video_id: str, category: str = "") -> bool:
    """Add a video to a YouTube playlist. Returns False on failure."""
    import time
    try:
        # 409 SERVICE_UNAVAILABLE / "operation was aborted" is transient — retry a few times.
        last_exc = None
        for i in range(3):
            try:
                yt.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        }
                    },
                ).execute()
                log.info("Added %s to playlist %s", video_id, playlist_id)
                return True
            except Exception as exc:
                msg = str(exc)
                retryable = "SERVICE_UNAVAILABLE" in msg or "operation was aborted" in msg or "backendError" in msg
                if not retryable or i == 2:
                    raise
                last_exc = exc
                time.sleep(1.5 * (i + 1))
        raise last_exc  # pragma: no cover
    except Exception as exc:
        log.warning("_add_to_playlist failed for video %s playlist %s: %s", video_id, playlist_id, exc)
        # If playlist was deleted/invalid, clear the cache entry so next publish recreates it.
        if "404" in str(exc) or "playlistNotFound" in str(exc):
            try:
                from backend.db import get_setting, set_setting
                cache: dict = get_setting("youtube_playlists") or {}
                stale_key = next((k for k, v in cache.items() if v == playlist_id), None)
                if stale_key:
                    del cache[stale_key]
                    set_setting("youtube_playlists", cache)
                    log.info("Cleared stale playlist cache for %r", stale_key)
            except Exception:
                pass
        return False


def _build_client():
    from backend.config import YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
    if not all([YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN]):
        raise RuntimeError(
            "Missing YouTube credentials — set YOUTUBE_CLIENT_ID / "
            "YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN in .env"
        )
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YOUTUBE_CLIENT_ID,
        client_secret=YOUTUBE_CLIENT_SECRET,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _get_local_path(media: dict) -> tuple[str, bool]:
    """Return (video_path, should_delete). Downloads from r2_url if local file missing."""
    reel_path = media.get("reel_ready_path") or ""
    if reel_path and Path(reel_path).exists():
        return reel_path, False

    url = media.get("r2_url") or media.get("media_preview_url") or ""
    if not url:
        raise ValueError(f"No local video or public URL for media {media.get('id')}")

    import httpx
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    with httpx.stream("GET", url, timeout=300, follow_redirects=True) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
            tmp.write(chunk)
    tmp.close()
    return tmp.name, True


def upload_short(
    media: dict,
    caption: str,
    hashtags_en: list[str],
    title_override: str | None = None,
    hashtags_ar: list[str] | None = None,
) -> str:
    """
    Upload a vertical video as a YouTube Short.
    Returns the YouTube video id.

    caption: full description text — may already include bilingual body + hashtags
             (assembled by _build_platform_caption); will be truncate-safe capped.
    title_override: when provided (e.g. caption_yt_title), used directly
             instead of derived first-line-of-caption.
    hashtags_ar: Arabic hashtags added to the API tags field for search signal.
    """
    from googleapiclient.http import MediaFileUpload

    video_path, cleanup = _get_local_path(media)
    try:
        yt = _build_client()

        if title_override:
            title = title_override.strip()[:_MAX_TITLE + 8]  # allow space for explicit #Shorts
            if "#Shorts" not in title and "#shorts" not in title:
                title = f"{title[:_MAX_TITLE]} #Shorts"
        else:
            first_line = caption.split("\n")[0][:_MAX_TITLE].strip()
            title = f"{first_line} #Shorts" if first_line else "#Shorts"

        # API tags: EN hashtags + Arabic tags (for search) + platform tags.
        tags = [t.lstrip("#") for t in hashtags_en[:25]]
        if hashtags_ar:
            tags += [t.lstrip("#") for t in hashtags_ar[:5]]
        tags += ["Shorts", "TravelShorts", "Travel"]

        # Description: already bilingual (EN + AR + hashtags) from _build_platform_caption.
        description = _truncate_yt_description(caption) if caption else "#Shorts"

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "19",  # Travel & Events
                "defaultLanguage": "en",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media_upload = MediaFileUpload(
            video_path, chunksize=10 * 1024 * 1024, resumable=True, mimetype="video/mp4"
        )
        request = yt.videos().insert(part="snippet,status", body=body, media_body=media_upload)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.debug("YouTube upload progress: %d%%", int(status.progress() * 100))

        video_id = response["id"]
        log.info("YouTube Short uploaded: https://youtube.com/shorts/%s", video_id)

        # Add to per-category playlist if enabled.
        category = media.get("category") or ""
        if category:
            from backend.db import get_setting
            platforms_cfg = get_setting("platforms") or {}
            yt_cfg = platforms_cfg.get("youtube") or {}
            if yt_cfg.get("playlists_enabled", True):
                playlist_id = _find_or_create_playlist(yt, category)
                if playlist_id:
                    _add_to_playlist(yt, playlist_id, video_id, category=category)

        return video_id
    finally:
        if cleanup:
            Path(video_path).unlink(missing_ok=True)
