"""
Google Drive + Google Photos import for the Download page (Phase 2).

Single-account model: one OAuth refresh token for the account owner (mirrors the
YouTube uploader). Mint it with backend/scripts/auth_google.py.

Drive  — server-side files.list / files.get_media. Lists the owner's video files
         and downloads a chosen file to disk under a hard size cap.
Photos — Google Photos Picker API session flow. The classic Library list API was
         restricted for third-party apps in 2025, so we create a picking session,
         the user selects items in Google's hosted picker, then we read the picked
         mediaItems and download each via its baseUrl (+ "=dv" for full video).

Downloads stream to disk in 1 MB chunks with a byte cap — no full-file buffering.
"""

import logging
from pathlib import Path

import requests

from backend.config import (
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN,
)

log = logging.getLogger(__name__)

_CHUNK = 1024 * 1024
_TIMEOUT = 30
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_PICKER_BASE = "https://photospicker.googleapis.com/v1"

# Drive video MIME prefix filter + page size for the file browser.
_DRIVE_PAGE_SIZE = 50


class GoogleImportError(Exception):
    """Raised on any Google import configuration or transfer failure."""


def is_configured() -> bool:
    """True when all three Google OAuth env vars are present."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN)


def _credentials():
    """Build refreshed OAuth2 credentials from the stored refresh token."""
    if not is_configured():
        raise GoogleImportError(
            "Google import not configured — set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET "
            "/ GOOGLE_REFRESH_TOKEN in .env (run backend/scripts/auth_google.py)."
        )
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise GoogleImportError(f"Missing Google client libs: {exc}")

    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri=_TOKEN_URI,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )
    try:
        creds.refresh(Request())
    except Exception as exc:
        raise GoogleImportError(f"Token refresh failed: {exc}")
    return creds


def _access_token() -> str:
    return _credentials().token


def _bounded_write(resp, dest: Path, max_bytes: int) -> int:
    """Stream a requests response body to disk, enforcing max_bytes. Returns bytes."""
    clen = resp.headers.get("Content-Length")
    if clen and clen.isdigit() and int(clen) > max_bytes:
        raise GoogleImportError(f"File is {int(clen) // (1024 * 1024)} MB, exceeds cap")
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=_CHUNK):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                fh.close()
                dest.unlink(missing_ok=True)
                raise GoogleImportError(f"Download exceeds {max_bytes // (1024 * 1024)} MB limit")
            fh.write(chunk)
    return total


# ── Google Drive ─────────────────────────────────────────────

def _drive_service():
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GoogleImportError(f"Missing google-api-python-client: {exc}")
    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


def list_drive_videos(query: str = "", page_token: str = "") -> dict:
    """List the owner's Drive video files (most-recent first).

    `query` does a name substring match. Returns
    {files: [{id,name,size,mimeType,thumbnailLink,duration_ms}], next_page_token}.
    """
    svc = _drive_service()
    q = "mimeType contains 'video/' and trashed = false"
    if query:
        safe = query.replace("'", "\\'")
        q += f" and name contains '{safe}'"
    try:
        resp = (
            svc.files()
            .list(
                q=q,
                pageSize=_DRIVE_PAGE_SIZE,
                pageToken=page_token or None,
                orderBy="modifiedTime desc",
                fields="nextPageToken, files(id, name, size, mimeType, thumbnailLink, "
                       "videoMediaMetadata(durationMillis))",
                spaces="drive",
            )
            .execute()
        )
    except Exception as exc:
        raise GoogleImportError(f"Drive list failed: {exc}")

    files = []
    for f in resp.get("files", []):
        meta = f.get("videoMediaMetadata") or {}
        files.append({
            "id": f["id"],
            "name": f.get("name", "video"),
            "size": int(f["size"]) if f.get("size") else None,
            "mimeType": f.get("mimeType", ""),
            "thumbnailLink": f.get("thumbnailLink"),
            "duration_ms": int(meta["durationMillis"]) if meta.get("durationMillis") else None,
        })
    return {"files": files, "next_page_token": resp.get("nextPageToken", "")}


def download_drive_file(file_id: str, dest: Path, max_bytes: int) -> int:
    """Download a Drive file to dest, enforcing max_bytes. Returns bytes written."""
    svc = _drive_service()
    # Size pre-check from metadata so we reject oversize before streaming.
    try:
        meta = svc.files().get(fileId=file_id, fields="size, mimeType, name").execute()
    except Exception as exc:
        raise GoogleImportError(f"Drive metadata fetch failed: {exc}")
    size = int(meta["size"]) if meta.get("size") else None
    if size is not None and size > max_bytes:
        raise GoogleImportError(f"File is {size // (1024 * 1024)} MB, exceeds cap")

    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise GoogleImportError(f"Missing google-api-python-client: {exc}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    request = svc.files().get_media(fileId=file_id)
    total = 0
    with open(dest, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=_CHUNK)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
            total = fh.tell()
            if total > max_bytes:
                fh.close()
                dest.unlink(missing_ok=True)
                raise GoogleImportError(f"Download exceeds {max_bytes // (1024 * 1024)} MB limit")
    return total


# ── Google Photos (Picker API) ───────────────────────────────

def _picker_headers() -> dict:
    return {"Authorization": f"Bearer {_access_token()}"}


def create_photos_session() -> dict:
    """Create a Photos picking session. Returns {id, picker_uri, poll_interval_ms}."""
    try:
        resp = requests.post(f"{_PICKER_BASE}/sessions", headers=_picker_headers(), json={}, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise GoogleImportError(f"Photos session create failed: {exc}")
    data = resp.json()
    poll = data.get("pollingConfig", {}) or {}
    # pollInterval comes back like "5s" or {"seconds": 5}; default to 3s.
    interval_ms = 3000
    raw = poll.get("pollInterval")
    if isinstance(raw, str) and raw.endswith("s"):
        try:
            interval_ms = int(float(raw[:-1]) * 1000)
        except ValueError:
            pass
    return {
        "id": data.get("id", ""),
        "picker_uri": data.get("pickerUri", ""),
        "poll_interval_ms": interval_ms,
    }


def get_photos_session(session_id: str) -> dict:
    """Poll a picking session. Returns {id, media_items_set: bool}."""
    try:
        resp = requests.get(f"{_PICKER_BASE}/sessions/{session_id}", headers=_picker_headers(), timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise GoogleImportError(f"Photos session poll failed: {exc}")
    data = resp.json()
    return {"id": data.get("id", session_id), "media_items_set": bool(data.get("mediaItemsSet"))}


def list_photos_picked(session_id: str) -> list[dict]:
    """List the video mediaItems the user picked in the session.

    Returns [{id, name, base_url, mimeType, size, duration_ms}]. Non-video items
    are skipped (Phase 1/2 = video only).
    """
    items: list[dict] = []
    page_token = ""
    while True:
        params = {"sessionId": session_id, "pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        try:
            resp = requests.get(f"{_PICKER_BASE}/mediaItems", headers=_picker_headers(), params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise GoogleImportError(f"Photos mediaItems list failed: {exc}")
        data = resp.json()
        for mi in data.get("mediaItems", []):
            if mi.get("type") != "VIDEO":
                continue
            mf = mi.get("mediaFile", {}) or {}
            vmeta = (mf.get("mediaFileMetadata", {}) or {}).get("videoMetadata", {}) or {}
            dur = vmeta.get("durationMillis")
            items.append({
                "id": mi.get("id", ""),
                "name": mf.get("filename", "photos_video"),
                "base_url": mf.get("baseUrl", ""),
                "mimeType": mf.get("mimeType", ""),
                "duration_ms": int(dur) if dur else None,
            })
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break
    return items


def download_photos_item(base_url: str, dest: Path, max_bytes: int) -> int:
    """Download a picked Photos video (baseUrl + '=dv') to dest under max_bytes."""
    if not base_url:
        raise GoogleImportError("Photos item has no baseUrl")
    url = base_url + "=dv"  # '=dv' yields the full-resolution video bytes
    try:
        resp = requests.get(url, headers=_picker_headers(), stream=True, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise GoogleImportError(f"Photos download failed: {exc}")
    try:
        return _bounded_write(resp, dest, max_bytes)
    finally:
        resp.close()
