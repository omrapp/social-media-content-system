import logging
import subprocess
import threading
from pathlib import Path
from backend.config import ORGANIZED_DIR, REELS_READY_DIR, THUMBS_DIR
from backend.db import get_media, get_media_by_id, update_media, update_status
from backend.pipeline.thumbnail import pick_bright_frame

log = logging.getLogger(__name__)

_RENDER_SEM = threading.Semaphore(2)   # allow 2 concurrent encodes per stage


def resize(src, dest):
    cmd = [
        "ffmpeg", "-i", src,
        # lanczos scaling resolves sharper than the default bilinear — free
        # quality win when up/down-scaling archive footage to the 9:16 frame.
        "-vf", "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920:flags=lanczos,setsar=1,fps=30",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-y", str(dest)
    ]
    with _RENDER_SEM:
        result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        # Surface ffmpeg's own diagnostics (tail keeps log readable).
        stderr = (result.stderr or b"").decode("utf-8", "replace").strip()
        log.error("ffmpeg failed (exit %s) for %s\n%s",
                  result.returncode, src, stderr[-1500:])
    return result.returncode == 0


def run(highlight=None, media_id=None):
    # Supabase-first via db high-level helpers (falls back to SQLite when unset).
    if media_id:
        log.info("resize: single media_id=%s", media_id)
        m = get_media_by_id(media_id)
        if not m:
            log.error("resize: media_id=%s not found in DB — nothing to resize", media_id)
            return {"processed": 0, "failed": 0, "total": 0,
                    "error": f"media_id {media_id} not found"}
        rows = [m]
    else:
        filters = {"media_type": "VIDEO", "status": "raw"}
        if highlight:
            filters["highlight_name"] = highlight
        rows = get_media(filters=filters, limit=1000) or []
        log.info("resize: batch highlight=%s — %d raw video(s) to process",
                 highlight or "*", len(rows))

    processed = 0
    failed = 0
    skipped = 0

    for row in rows:
        # Prefer the decaptioned (cleaned) file when the decaption stage produced
        # one; fall back to the raw clip. decaptioned_path is stored absolute under
        # DECAPTIONED_DIR, so it needs no ORGANIZED_DIR resolution.
        mid, src = row["id"], (row.get("decaptioned_path") or row.get("local_path"))
        # Resolve relative local_path (stored relative to ORGANIZED_DIR) to absolute.
        if src and not Path(src).is_absolute():
            src = str(ORGANIZED_DIR / src)
        # Only resize raw videos; media_id path may hand back any status/type.
        if row.get("media_type") != "VIDEO":
            log.warning("resize: skip %s — not a VIDEO (media_type=%s)",
                        mid, row.get("media_type"))
            skipped += 1
            continue
        if row.get("status") != "raw":
            status = row.get("status")
            # Never auto-regenerate terminal statuses — the clip has already shipped.
            # Only 'resized', 'enhanced', 'edited', and 'error' with a missing file
            # are legitimate regeneration candidates.
            if status in ("posted", "uploaded", "scheduled", "preview", "rejected"):
                log.warning("resize: skip %s — terminal status '%s', not regenerating",
                            mid, status)
                skipped += 1
                continue
            # For in-progress statuses, check if the reel file is actually on disk.
            # If present, the clip is already processed — skip.
            # If missing (purged after upload, deleted intermediate, etc.), self-heal.
            rrp = row.get("reel_ready_path")
            if rrp and Path(rrp).exists():
                log.warning("resize: skip %s — status is '%s' and reel file present "
                            "(already processed)", mid, status)
                skipped += 1
                continue
            else:
                log.warning("resize: %s — status is '%s' but reel file missing (%s) — "
                            "resetting to raw for regeneration", mid, status, rrp)
                # Clear the stale reel_ready_path pointer alongside the status reset.
                from backend.db import update_media as _update_media
                _update_media(mid, {"status": "raw", "reel_ready_path": None})
                row = dict(row)
                row["status"] = "raw"
                # Fall through to resize below
        if not src:
            log.error("resize: skip %s — no local_path on record", mid)
            skipped += 1
            continue
        if not Path(src).exists():
            log.error("resize: skip %s — local file missing on disk: %s", mid, src)
            update_status(mid, "error", error_message=f"source file missing: {src}")
            failed += 1
            continue

        dest = REELS_READY_DIR / f"{mid}_9x16.mp4"
        log.info("resize: %s → %s", src, dest)
        ok = resize(src, dest)
        if ok:
            thumb_path = THUMBS_DIR / f"{mid}.jpg"
            thumb_url = f"/static/thumbs/{mid}.jpg" if pick_bright_frame(str(dest), str(thumb_path)) else ""
            update_media(mid, {"status": "resized", "reel_ready_path": str(dest), "thumbnail_url": thumb_url})
            log.info("resize: ok %s (status → resized, thumb=%s)", mid, bool(thumb_url))
            processed += 1
        else:
            update_status(mid, "error", error_message="ffmpeg resize failed")
            failed += 1

    log.info("resize: done — processed=%d failed=%d skipped=%d total=%d",
             processed, failed, skipped, len(rows))
    return {"processed": processed, "failed": failed,
            "skipped": skipped, "total": len(rows)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    result = run()
    print(f"Resized {result['processed']}/{result['total']}. Failed: {result['failed']}")
