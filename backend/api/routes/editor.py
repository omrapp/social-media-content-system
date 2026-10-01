"""
Reel Editor API — /api/editor/* (v2.0.0).

    GET    /api/editor/{media_id}            latest saved EDL, else hydrate()
    PUT    /api/editor/{media_id}            validate + save a new EDL version
    GET    /api/editor/{media_id}/versions   version list (no docs)
    POST   /api/editor/{media_id}/proxies    async proxy generation + WS progress
    POST   /api/editor/{media_id}/export     compile → render → edit → upload
    GET    /api/editor/proxy/{key}.mp4       signed, Range-capable proxy stream

Every route is gated on the `editor.enabled` setting. All of them sit behind
verify_token EXCEPT the proxy stream: a <video> element cannot attach an
Authorization header, so that one authenticates with a short-lived HMAC
signature over (key, exp) instead. See _sign/_verify_sig below.
"""

import asyncio
import hmac
import logging
import re
from hashlib import sha256
from pathlib import Path
from time import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.auth import verify_token
from backend.api.ws import broadcast
from backend.config import EDITOR_MEDIA_SECRET
from backend.db import (create_edit_project, get_edit_project_version,
                        get_latest_edit_project, get_media_by_id, get_posts,
                        get_setting, list_edit_projects, prune_edit_projects,
                        update_media, update_post)
from backend.pipeline import editor_proxy
from backend.pipeline.editor_edl import (EDL, EDLError, check_caps,
                                         compile as compile_edl, hydrate)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/editor", tags=["editor"], dependencies=[Depends(verify_token)])
# Router-level dependencies cannot be opted out of per-route in FastAPI, so the
# signed proxy stream lives on its own dependency-free router (registered
# alongside `router` in api/main.py). It authenticates with an HMAC signature —
# see stream_proxy for why verify_token is not usable there.
public_router = APIRouter(prefix="/api/editor", tags=["editor"])

# Signed proxy URLs are short-lived: long enough to open a reel and scrub it,
# short enough that a leaked URL is worthless by the time it is shared.
_SIG_TTL_S = 6 * 3600
_KEY_RE = re.compile(r"^[a-f0-9]{64}$")
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK = 256 * 1024
# A single Range request may not ask for more than this; a malicious client
# should not be able to make one request pin an arbitrary amount of memory.
_MAX_RANGE_BYTES = 64 * 1024 * 1024

# Caption/metadata carried from the edited reel onto its exported successor, so
# the post keeps its copy without re-running the caption stage.
_CAPTION_FIELDS = (
    "caption", "caption_ig", "caption_ig_ar", "caption_yt_title",
    "caption_yt_description", "caption_tt", "alt_text",
    "hashtags_en", "hashtags_en_b", "hashtags_ar",
)


# ── gating + helpers ──────────────────────────────────────────────────────

def _cfg() -> dict:
    return get_setting("editor") or {}


def _require_enabled() -> dict:
    cfg = _cfg()
    if not cfg.get("enabled", True):
        raise HTTPException(403, "Reel editor is disabled (settings: editor.enabled)")
    return cfg


def _require_media(media_id: str) -> dict:
    row = get_media_by_id(media_id)
    if not row:
        raise HTTPException(404, f"Media {media_id} not found")
    return row


def _sign(key: str, exp: int) -> str:
    return hmac.new(EDITOR_MEDIA_SECRET.encode("utf-8"),
                    f"{key}:{exp}".encode("utf-8"), sha256).hexdigest()


def _verify_sig(key: str, exp: int, sig: str) -> bool:
    if not EDITOR_MEDIA_SECRET:
        # No secret configured ⇒ no way to authenticate ⇒ deny. Never fall open.
        return False
    if exp < int(time()):
        return False
    return hmac.compare_digest(_sign(key, exp), sig or "")


def _signed_url(key: str) -> str:
    exp = int(time()) + _SIG_TTL_S
    return f"/api/editor/proxy/{key}.mp4?e={exp}&t={_sign(key, exp)}"


def _post_for_media(media_id: str) -> dict | None:
    """The queued post this reel belongs to (newest first). Export updates this
    row in place so the reel keeps its slot, schedule and caption."""
    try:
        posts = get_posts(filters={"media_id": media_id}, limit=5, desc=True) or []
    except Exception as exc:
        log.warning("editor: post lookup for %s failed (non-fatal): %s", media_id, exc)
        return None
    return posts[0] if posts else None


# ── GET / PUT / versions ──────────────────────────────────────────────────

@router.get("/{media_id}")
def get_edl(media_id: str, fresh: bool = Query(False)):
    """Latest saved EDL for a reel, or a freshly hydrated one when it has never
    been edited. `approx` tells the UI whether the doc is an exact round-trip of
    how the reel was rendered or a lossy reconstruction of a legacy merge.

    `fresh=true` is revert-to-original: skip the saved project entirely and
    return hydrate(row). It deliberately DELETES NOTHING — the user reverts,
    edits, and saves a NEW version on top, so the discarded work is still one
    version-picker click away.
    """
    _require_enabled()
    row = _require_media(media_id)

    saved = None if fresh else get_latest_edit_project(media_id)
    if saved and isinstance(saved.get("doc"), dict):
        return {
            "media_id": media_id,
            "edl": saved["doc"],
            "approx": bool(saved.get("approx")),
            "version": saved.get("version"),
            "project_id": saved.get("id"),
            "saved_at": saved.get("created_at"),
        }

    edl = hydrate(row)
    return {
        "media_id": media_id,
        "edl": edl.model_dump(),
        "approx": edl.approx,
        "version": 0,
        "project_id": None,
        "saved_at": None,
    }


class SaveEDLRequest(BaseModel):
    edl: EDL
    label: str | None = Field(default=None, max_length=120)


@router.put("/{media_id}")
def save_edl(media_id: str, body: SaveEDLRequest):
    """Persist a new EDL version. The doc is validated by pydantic on the way in;
    history is pruned to editor.keep_versions right after the insert."""
    cfg = _require_enabled()
    _require_media(media_id)

    if body.edl.source_media_id != media_id:
        raise HTTPException(400, "edl.source_media_id does not match the URL media_id")
    # Refuse to persist a doc that could never be exported (and would otherwise
    # sit in history burning rows + jsonb).
    try:
        check_caps(body.edl)
    except EDLError as exc:
        raise HTTPException(400, f"Invalid edit: {exc}")

    prev = get_latest_edit_project(media_id)
    version = int((prev or {}).get("version") or 0) + 1
    post = _post_for_media(media_id)

    saved = create_edit_project({
        "media_id": media_id,
        "post_id": (post or {}).get("id"),
        "version": version,
        "doc": body.edl.model_dump(),
        "label": body.label,
        "approx": bool(body.edl.approx),
    })
    if not saved:
        raise HTTPException(503, "Edit projects require Supabase — no version was saved")

    try:
        prune_edit_projects(media_id, int(cfg.get("keep_versions", 20)))
    except Exception as exc:
        log.warning("editor: prune versions for %s failed (non-fatal): %s", media_id, exc)

    return {"media_id": media_id, "project_id": saved.get("id"), "version": version,
            "approx": bool(saved.get("approx"))}


@router.get("/{media_id}/versions")
def list_versions(media_id: str):
    """Version history WITHOUT the docs — the list is a picker, and the docs are
    large enough that shipping them all would dominate the response."""
    _require_enabled()
    _require_media(media_id)
    rows = list_edit_projects(media_id) or []
    return {"media_id": media_id, "versions": [
        {"id": r.get("id"), "version": r.get("version"), "label": r.get("label"),
         "approx": bool(r.get("approx")), "created_at": r.get("created_at")}
        for r in rows
    ]}


@router.get("/{media_id}/versions/{version}")
def get_version(media_id: str, version: int):
    """One saved version WITH its doc — what the picker loads when the user
    clicks a history entry. Addressed by version number rather than row id so a
    pruned version 404s instead of resolving to some other reel's project."""
    _require_enabled()
    _require_media(media_id)
    row = get_edit_project_version(media_id, version)
    if not row or not isinstance(row.get("doc"), dict):
        raise HTTPException(404, f"Version {version} not found for {media_id}")
    return {
        "media_id": media_id,
        "version": row.get("version"),
        "label": row.get("label"),
        "approx": bool(row.get("approx")),
        "created_at": row.get("created_at"),
        "edl": row["doc"],
    }


# ── proxies ───────────────────────────────────────────────────────────────

class ProxyRequest(BaseModel):
    edl: EDL | None = None


@router.post("/{media_id}/proxies")
async def build_proxies(media_id: str, body: ProxyRequest | None = None):
    """Kick off proxy generation for the reel's cuts and return immediately.

    Progress arrives over /ws/pipeline as `editor_proxy_progress`, then
    `editor_proxy_complete` carrying {cut_id: signed_url}. Encoding runs in a
    thread executor (bounded to 2 workers inside editor_proxy) so the event loop
    stays responsive. Follows the async pattern in routes/edit.py:129-183.
    """
    cfg = _require_enabled()
    if not EDITOR_MEDIA_SECRET:
        # Without a secret every signed URL we hand back would 403 on playback,
        # which reads as "the editor is broken" rather than "it is unconfigured".
        raise HTTPException(503, "Editor proxy streaming is unconfigured: set "
                                 "EDITOR_MEDIA_SECRET (or SUPABASE_JWT_SECRET) in .env")
    row = _require_media(media_id)

    edl = (body.edl if body and body.edl else None) or hydrate(row)
    if not edl.cuts:
        return {"media_id": media_id, "status": "no_cuts", "proxies": {}}

    height = int(cfg.get("proxy_height", 480))
    asyncio.create_task(_run_proxies(media_id, edl, height))
    return {"media_id": media_id, "status": "started", "cuts": len(edl.cuts)}


async def _run_proxies(media_id: str, edl: EDL, height: int) -> None:
    loop = asyncio.get_running_loop()

    def _progress(done: int, total: int) -> None:
        # Called from the worker threads — hop back onto the loop to broadcast.
        asyncio.run_coroutine_threadsafe(
            broadcast("editor_proxy_progress",
                      {"media_id": media_id, "done": done, "total": total}),
            loop,
        )

    def _sync():
        return editor_proxy.ensure_proxies_for_edl(edl, progress_cb=_progress, height=height)

    try:
        keys = await loop.run_in_executor(None, _sync)
        await broadcast("editor_proxy_complete", {
            "media_id": media_id,
            "proxies": {cid: _signed_url(k) for cid, k in keys.items()},
        })
    except Exception as exc:
        log.exception("editor: proxy generation failed for %s", media_id)
        await broadcast("editor_proxy_failed", {"media_id": media_id, "error": str(exc)})


# ── export ────────────────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    edl: EDL
    label: str | None = Field(default=None, max_length=120)


def _merge_render_fn():
    """Indirection over merge_clips.render(plan), which lands with the
    build_plan()/render() split (Phase 1, after the golden fixtures are
    captured). Raising here is deliberate — a stub that pretended to render would
    silently ship a wrong reel."""
    from backend.pipeline import merge_clips
    fn = getattr(merge_clips, "render", None)
    if not callable(fn):
        raise NotImplementedError(
            "merge_clips.render(plan) is not available yet — the build_plan()/render(plan) "
            "split must land (after the golden fixtures are captured) before an editor "
            "export can be rendered."
        )
    return fn


@router.post("/{media_id}/export")
async def export_edl(media_id: str, body: ExportRequest):
    """Compile the EDL, then render → edit → upload in the background.

    Compilation (validation, path containment, caps) happens SYNCHRONOUSLY so a
    bad doc returns a 400 instead of failing minutes later inside a worker. The
    export always produces a NEW media row; the post is repointed at it and keeps
    its scheduled_at / publish_after / caption.
    """
    _require_enabled()
    row = _require_media(media_id)

    if body.edl.source_media_id != media_id:
        raise HTTPException(400, "edl.source_media_id does not match the URL media_id")

    try:
        plan, overrides = compile_edl(body.edl, row)
    except EDLError as exc:
        raise HTTPException(400, f"Invalid edit: {exc}")

    post = _post_for_media(media_id)
    asyncio.create_task(_run_export(media_id, plan, overrides, post, row))
    return {
        "media_id": media_id,
        "status": "export_started",
        "merge_id": plan.merge_id,
        "post_id": (post or {}).get("id"),
        "cuts": len(plan.cuts),
    }


async def _run_export(media_id: str, plan, overrides, post: dict | None,
                      parent_row: dict) -> None:
    loop = asyncio.get_running_loop()
    post_id = (post or {}).get("id")
    new_id = plan.merge_id

    await broadcast("editor_export_start", {
        "media_id": media_id, "merge_id": new_id, "post_id": post_id,
        "cuts": len(plan.cuts),
    })

    def _render():
        return _merge_render_fn()(plan.model_dump())

    try:
        result = await loop.run_in_executor(None, _render)
        if isinstance(result, dict) and result.get("status") not in (None, "completed"):
            raise RuntimeError(result.get("error") or "merge render failed")
        rendered_id = (result or {}).get("media_id", new_id) if isinstance(result, dict) else new_id

        # Carry the caption forward so the post's copy survives and the edit
        # stage's hook/hashtag overlays still have real text to draw.
        carry = {k: parent_row[k] for k in _CAPTION_FIELDS
                 if parent_row.get(k) not in (None, "")}
        if carry:
            await loop.run_in_executor(None, lambda: update_media(rendered_id, carry))

        await broadcast("editor_export_progress", {
            "media_id": media_id, "merge_id": rendered_id, "stage": "edit",
        })

        def _tail():
            from backend.pipeline.orchestrator import run as orch_run
            # The rendered reel is already a 9:16 "resized" file, and the editor
            # already decided the grade — so only the composite + upload run.
            # edl_overrides carries the LUT, eq, overlay layers and the
            # branding/voiceover/intro/cast toggles; lut_override/no_lut stay in
            # the call as the belt-and-braces path for the legacy code branch.
            return orch_run(stages=["edit", "upload"], media_id=rendered_id,
                            lut_override=overrides.lut, no_lut=not overrides.lut,
                            edl_overrides=overrides.model_dump())

        await loop.run_in_executor(None, _tail)

        if post_id:
            # Same post row: keep scheduled_at / publish_after / status, just
            # point it at the newly rendered reel.
            await loop.run_in_executor(None, lambda: update_post(post_id, {"media_id": rendered_id}))

        await broadcast("editor_export_complete", {
            "media_id": media_id, "merge_id": rendered_id, "post_id": post_id,
        })
    except Exception as exc:
        log.exception("editor: export failed for %s", media_id)
        await broadcast("editor_export_failed", {
            "media_id": media_id, "merge_id": new_id, "post_id": post_id,
            "error": str(exc),
        })


# ── signed proxy stream (the one unauthenticated route) ───────────────────

def _file_iter(path: Path, start: int, length: int):
    with path.open("rb") as fh:
        fh.seek(start)
        left = length
        while left > 0:
            chunk = fh.read(min(_CHUNK, left))
            if not chunk:
                break
            left -= len(chunk)
            yield chunk


@public_router.get("/proxy/{key}.mp4")
def stream_proxy(key: str, request: Request,
                 e: int = Query(..., description="signature expiry (unix seconds)"),
                 t: str = Query(..., description="HMAC-SHA256 over '<key>:<exp>'")):
    """Serve a cached editor proxy.

    UNAUTHENTICATED BY NECESSITY: a <video> element cannot send an Authorization
    header, so this route lives on `public_router` and carries its own
    short-lived HMAC signature instead of verify_token. The path component is a
    sha256 content address — never a user-supplied path — and is shape-checked
    before the filesystem is touched.

    Starlette's FileResponse does not implement Range, and the player needs to
    seek, so 206 handling is done manually here.
    """
    _require_enabled()

    if not _KEY_RE.match(key or ""):
        raise HTTPException(404, "Not found")
    if not _verify_sig(key, int(e), t):
        raise HTTPException(403, "Invalid or expired proxy signature")

    path = editor_proxy.proxy_path(key)
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Proxy not found")
    size = path.stat().st_size

    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    rng = request.headers.get("range")
    if not rng:
        headers["Content-Length"] = str(size)
        return StreamingResponse(_file_iter(path, 0, size), media_type="video/mp4",
                                 headers=headers)

    m = _RANGE_RE.match(rng.strip())
    if not m or (not m.group(1) and not m.group(2)):
        raise HTTPException(416, "Malformed Range header")
    first, last = m.group(1), m.group(2)
    if first:
        start = int(first)
        end = int(last) if last else size - 1
    else:
        # Suffix form "bytes=-N" — the last N bytes.
        start = max(0, size - int(last))
        end = size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        raise HTTPException(416, "Requested range not satisfiable")
    length = end - start + 1
    if length > _MAX_RANGE_BYTES:
        end = start + _MAX_RANGE_BYTES - 1
        length = _MAX_RANGE_BYTES

    headers.update({
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(length),
    })
    return StreamingResponse(_file_iter(path, start, length), status_code=206,
                             media_type="video/mp4", headers=headers)
