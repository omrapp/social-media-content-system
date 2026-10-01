"""
Server-side URL fetch for public video links (Google Drive / Dropbox / direct).

Used by POST /api/downloads/upload-url. Normalizes known share-link hosts to a
direct-download URL, then streams the body to disk in 1 MB chunks with a hard
size cap.

SECURITY: this fetches arbitrary user-supplied URLs server-side, so it is an SSRF
surface. _assert_public_url() resolves the hostname and rejects any private /
loopback / link-local / metadata IP range before a request is ever made, and only
http/https schemes are allowed. The whole feature is additionally gated behind the
uploads.url_fetch setting in the route layer.
"""

import ipaddress
import logging
import re
import socket
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

log = logging.getLogger(__name__)

_CHUNK = 1024 * 1024          # 1 MB stream chunk
_MAX_REDIRECTS = 5
_TIMEOUT = 30                 # per-request timeout (seconds)
_DRIVE_ID_RE = re.compile(r"/file/d/([A-Za-z0-9_-]+)")
_CONFIRM_RE = re.compile(r'confirm=([0-9A-Za-z_-]+)')


class FetchError(Exception):
    """Raised on any fetch validation or transfer failure."""


# ── URL normalization ────────────────────────────────────────

def normalize_url(url: str) -> str:
    """Rewrite known share-link hosts to a direct-download URL. Others pass through."""
    if not url:
        return url
    u = url.strip()
    parsed = urlparse(u)
    host = (parsed.hostname or "").lower()

    # Google Drive → uc?export=download&id=<ID>
    if "drive.google.com" in host or "docs.google.com" in host:
        file_id = None
        m = _DRIVE_ID_RE.search(parsed.path)
        if m:
            file_id = m.group(1)
        else:
            qs = parse_qs(parsed.query)
            if qs.get("id"):
                file_id = qs["id"][0]
        if file_id:
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        return u

    # Dropbox → force direct download
    if "dropbox.com" in host:
        if "dl.dropboxusercontent.com" in host:
            return u
        # Force dl=1 (replace existing dl=0 / dl=1 or append)
        new = re.sub(r"([?&])dl=[01]", r"\g<1>dl=1", u)
        if "dl=" not in new:
            sep = "&" if parsed.query else "?"
            new = f"{u}{sep}dl=1"
        return new

    return u


# ── SSRF guard ───────────────────────────────────────────────

def _is_blocked_ip(ip: str) -> bool:
    """True for private / loopback / link-local / metadata / reserved addresses."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _assert_public_url(url: str) -> None:
    """Reject non-http(s) schemes and any URL that resolves to a private/internal IP.

    Resolves the hostname to every address (IPv4 + IPv6) and rejects if ANY of them
    falls in a blocked range — defends against DNS-rebinding-style multi-A records.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"Only http/https URLs are allowed (got '{parsed.scheme}')")
    host = parsed.hostname
    if not host:
        raise FetchError("URL has no host")

    # Literal IP host — check directly.
    try:
        if _is_blocked_ip(host):
            raise FetchError(f"Refusing to fetch private/internal address: {host}")
        return
    except ValueError:
        pass  # not a literal IP — fall through to DNS resolution

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve host '{host}': {exc}")
    for info in infos:
        ip = info[4][0]
        if _is_blocked_ip(ip):
            raise FetchError(f"Host '{host}' resolves to blocked address {ip}")


# ── Fetch ────────────────────────────────────────────────────

def _looks_like_html(resp) -> bool:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    return "text/html" in ctype


def _stream_to_file(resp, dest_path: Path, max_bytes: int) -> int:
    """Write a streamed response body to disk, enforcing max_bytes. Returns bytes written."""
    clen = resp.headers.get("Content-Length")
    if clen and clen.isdigit() and int(clen) > max_bytes:
        raise FetchError(f"Remote file is {int(clen) // (1024 * 1024)} MB, exceeds cap")
    total = 0
    with open(dest_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=_CHUNK):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                fh.close()
                dest_path.unlink(missing_ok=True)
                raise FetchError(f"Download exceeds {max_bytes // (1024 * 1024)} MB limit")
            fh.write(chunk)
    return total


def _ytdlp_fallback(url: str, dest_path: Path, max_bytes: int) -> int:
    """Optional yt-dlp fallback for Drive interstitials. No-op if yt-dlp absent."""
    try:
        import yt_dlp  # noqa: F401
    except Exception:
        raise FetchError("Link returned an HTML page and yt-dlp is not installed")
    import yt_dlp as ydl
    opts = {
        "outtmpl": str(dest_path),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": max_bytes,
        "overwrites": True,
    }
    try:
        with ydl.YoutubeDL(opts) as dl:
            dl.download([url])
    except Exception as exc:
        raise FetchError(f"yt-dlp fetch failed: {exc}")
    if not dest_path.exists() or dest_path.stat().st_size == 0:
        raise FetchError("yt-dlp produced no file")
    return dest_path.stat().st_size


def fetch_to_file(url: str, dest_path: Path, max_bytes: int) -> int:
    """Fetch a normalized URL to dest_path, enforcing max_bytes. Returns bytes written.

    Handles the Google Drive confirm-token interstitial, and falls back to yt-dlp
    (if importable) when the body is still HTML. Raises FetchError on any failure.
    """
    _assert_public_url(url)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.max_redirects = _MAX_REDIRECTS

    try:
        resp = session.get(url, stream=True, timeout=_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()

        if _looks_like_html(resp):
            # Google Drive large-file confirm-token interstitial.
            body_head = resp.raw.read(65536) if hasattr(resp, "raw") else b""
            token = None
            if body_head:
                m = _CONFIRM_RE.search(body_head.decode("utf-8", "ignore"))
                if m:
                    token = m.group(1)
            # Also check the download_warning cookie Drive sets.
            if not token:
                for k, v in session.cookies.items():
                    if k.startswith("download_warning"):
                        token = v
                        break
            resp.close()
            if token and "drive.google.com" in url:
                sep = "&" if "?" in url else "?"
                confirm_url = f"{url}{sep}confirm={token}"
                _assert_public_url(confirm_url)
                resp2 = session.get(confirm_url, stream=True, timeout=_TIMEOUT, allow_redirects=True)
                resp2.raise_for_status()
                if _looks_like_html(resp2):
                    resp2.close()
                    return _ytdlp_fallback(url, dest_path, max_bytes)
                try:
                    return _stream_to_file(resp2, dest_path, max_bytes)
                finally:
                    resp2.close()
            # No token → try yt-dlp.
            return _ytdlp_fallback(url, dest_path, max_bytes)

        try:
            return _stream_to_file(resp, dest_path, max_bytes)
        finally:
            resp.close()
    except FetchError:
        raise
    except requests.TooManyRedirects:
        raise FetchError("Too many redirects")
    except requests.RequestException as exc:
        raise FetchError(f"Fetch failed: {exc}")
