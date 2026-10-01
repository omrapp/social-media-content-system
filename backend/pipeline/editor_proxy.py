"""
Reel Editor — 480p proxy generator (v2.0.0).

The browser player cannot stream the 1080p source clips (bandwidth, and a
cross-origin R2 video would taint the WebGL LUT canvas). Instead each EDL cut is
re-cut once into a small same-origin proxy, cached CONTENT-ADDRESSED under
EDITOR_DIR/proxies/<sha256>.mp4.

Why content-addressed: the cache key is a hash of (src_path, in_s, out_s,
height), so re-opening an unchanged reel is instant, two cuts of the same window
share one file, and — the part that matters for security — the URL path
component is a 64-hex digest, never a user-supplied path. Nothing under
EDITOR_DIR is reachable through a StaticFiles mount; the signed route in
api/routes/editor.py is the only way in.

EDITOR_DIR is a SIBLING of MERGE_DIR on purpose: merge_clips._cleanup() does
shutil.rmtree(MERGE_DIR/<merge_id>) after every render and would otherwise wipe
the proxy cache mid-session.
"""

import hashlib
import logging
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend.config import EDITOR_DIR

log = logging.getLogger(__name__)

PROXY_DIR = EDITOR_DIR / "proxies"

# the VPS is CPU-limited and the merge render already holds a semaphore — two
# concurrent ffmpeg proxy jobs is the most we can spend without starving it.
_MAX_WORKERS = 2

_FFMPEG_TIMEOUT_S = 120


def proxy_key(src_path: str, in_s: float, out_s: float, height: int) -> str:
    """Stable content-address for one proxy. Times are rounded to 3 dp so a
    float-noise difference doesn't force a re-encode of an identical window."""
    raw = "|".join([
        str(src_path),
        f"{float(in_s):.3f}",
        f"{float(out_s):.3f}",
        str(int(height)),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def proxy_path(key: str) -> Path:
    return PROXY_DIR / f"{key}.mp4"


def ensure_proxy(src_path: str, in_s: float, out_s: float, height: int = 480) -> Path:
    """Return the cached proxy for [in_s, out_s] of *src_path*, encoding it first
    if absent. Raises RuntimeError when ffmpeg fails — the caller reports it over
    WS rather than leaving the editor waiting on a file that will never appear."""
    key = proxy_key(src_path, in_s, out_s, height)
    dest = proxy_path(key)
    if dest.exists() and dest.stat().st_size > 0:
        # Touch so an actively-used proxy survives the TTL sweep.
        try:
            dest.touch()
        except OSError:
            pass
        return dest

    dur = max(0.05, float(out_s) - float(in_s))
    PROXY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.mp4")
    # -ss BEFORE -i = fast keyframe seek; the editor tolerates the small seek
    # imprecision on a preview proxy, and it keeps cold-open latency bearable.
    # No audio: the timeline plays the music bed as a separate <Audio> track.
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{float(in_s):.3f}", "-t", f"{dur:.3f}",
        "-i", str(src_path),
        "-vf", f"scale=-2:{int(height)}",
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
        "-pix_fmt", "yuv420p", "-threads", "1",
        "-movflags", "+faststart",
        "-y", str(tmp),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"proxy encode timed out after {_FFMPEG_TIMEOUT_S}s")
    if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        stderr = (r.stderr or b"").decode("utf-8", "replace").strip()
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"proxy encode failed (rc={r.returncode}): {stderr[-300:]}")
    # Atomic publish so a concurrent reader never sees a half-written proxy.
    tmp.replace(dest)
    return dest


def ensure_proxies_for_edl(edl, progress_cb=None, height: int | None = None) -> dict[str, str]:
    """Generate every proxy an EDL needs, bounded to two workers.

    Returns {cut_id: proxy_key}; cuts whose source can't be resolved or encoded
    are omitted (the editor shows those as unavailable rather than failing the
    whole open). *progress_cb(done, total)* fires once per completed cut.
    """
    from backend.db import get_media_by_id, get_setting
    from backend.pipeline import merge_clips as _mc

    if height is None:
        height = int((get_setting("editor") or {}).get("proxy_height", 480))

    jobs: list[tuple[str, str, float, float]] = []
    for cut in edl.cuts:
        row = get_media_by_id(cut.src_media_id)
        src = _mc._source_path(row) if row else None
        if not src:
            log.warning("editor proxy: cut %s — no readable source for %s",
                        cut.id, cut.src_media_id)
            continue
        jobs.append((cut.id, src, float(cut.in_s), float(cut.out_s)))

    out: dict[str, str] = {}
    total = len(jobs)
    if not total:
        if progress_cb:
            progress_cb(0, 0)
        return out

    done = 0
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {
            pool.submit(ensure_proxy, src, a, b, height): (cid, src, a, b)
            for cid, src, a, b in jobs
        }
        for fut in as_completed(futures):
            cid, src, a, b = futures[fut]
            try:
                fut.result()
                out[cid] = proxy_key(src, a, b, height)
            except Exception as exc:
                log.warning("editor proxy: cut %s failed: %s", cid, exc)
            done += 1
            if progress_cb:
                try:
                    progress_cb(done, total)
                except Exception:
                    pass   # progress reporting must never fail the job
    return out


def sweep(ttl_days: float = 7.0) -> int:
    """Delete proxies whose mtime is older than *ttl_days*. Returns the number of
    files removed. ensure_proxy() touches on cache hit, so a reel someone keeps
    reopening never expires under them."""
    if ttl_days <= 0 or not PROXY_DIR.exists():
        return 0
    cutoff = time.time() - ttl_days * 86400.0
    removed = 0
    for f in PROXY_DIR.glob("*.mp4"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError as exc:
            log.warning("editor proxy sweep: could not remove %s: %s", f, exc)
    if removed:
        log.info("editor proxy sweep: removed %d proxies older than %.1f days",
                 removed, ttl_days)
    return removed
