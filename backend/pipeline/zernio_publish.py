import logging
import requests
from backend.config import ZERNIO_API_KEY, ZERNIO_IG_ACCOUNT_ID, ZERNIO_TT_ACCOUNT_ID

log = logging.getLogger(__name__)

_ZERNIO_API_URL = "https://zernio.com/api/v1/posts"

_ACCOUNT_IDS: dict[str, str] = {
    "instagram": ZERNIO_IG_ACCOUNT_ID,
    "tiktok": ZERNIO_TT_ACCOUNT_ID,
}


def upload_short(media: dict, caption: str, platform: str) -> str:
    """
    Publish a video to Instagram (as Reel) or TikTok via Zernio.
    Returns the Zernio post _id.

    Instagram: posts as contentType="reels" with shareToFeed=True.
    TikTok: requires tiktokSettings at root level with 6 mandatory fields
            (privacy_level, allow_comment, allow_duet, allow_stitch,
             content_preview_confirmed, express_consent_given).
    Thumbnail: uses media.thumbnail_url if available.
    """
    if not ZERNIO_API_KEY:
        raise RuntimeError("ZERNIO_API_KEY not configured")

    r2_url = media.get("r2_url") or media.get("media_preview_url")
    if not r2_url:
        raise ValueError(f"No public URL for Zernio {platform} publish")

    account_id = _ACCOUNT_IDS.get(platform, "")
    if not account_id:
        raise ValueError(f"ZERNIO_{platform.upper()}_ACCOUNT_ID not configured")

    thumbnail_url = media.get("thumbnail_url") or ""

    if platform == "instagram":
        platform_specific: dict = {
            "contentType": "reels",  # must be set or Zernio posts as feed video
            "shareToFeed": True,
        }
        if thumbnail_url:
            platform_specific["instagramThumbnail"] = thumbnail_url  # JPEG/PNG 1080x1920

        payload: dict = {
            "content": caption,
            "mediaItems": [{"type": "video", "url": r2_url}],
            "platforms": [
                {
                    "platform": "instagram",
                    "accountId": account_id,
                    "platformSpecificData": platform_specific,
                }
            ],
            "publishNow": True,
        }

    elif platform == "tiktok":
        # tiktokSettings goes at ROOT level, not inside platformSpecificData (TikTok-only exception).
        tiktok_settings: dict = {
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "allow_comment": True,
            "allow_duet": True,
            "allow_stitch": True,
            "content_preview_confirmed": True,   # TikTok legal requirement — must be True
            "express_consent_given": True,        # TikTok legal requirement — must be True
        }
        if thumbnail_url:
            tiktok_settings["video_cover_image_url"] = thumbnail_url  # JPG/PNG/WebP max 20 MB

        payload = {
            "content": caption,   # caption for video posts (tiktokSettings.description is carousels only)
            "mediaItems": [{"type": "video", "url": r2_url}],
            "platforms": [{"platform": "tiktok", "accountId": account_id}],
            "tiktokSettings": tiktok_settings,
            "publishNow": True,
        }

    else:
        raise ValueError(f"Unsupported platform for Zernio: {platform!r}")

    resp = requests.post(
        _ZERNIO_API_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {ZERNIO_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=(10, 300),
    )
    resp.raise_for_status()
    data = resp.json()
    post_id = (data.get("post") or {}).get("_id") or data.get("_id") or ""
    log.info("Zernio %s published → post_id=%s", platform, post_id)
    return post_id
