from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.db import get_captions, save_caption, get_media_by_id, update_media
from backend.pipeline.caption_gen import generate
from backend.api.auth import verify_token

router = APIRouter(prefix="/api/captions", tags=["captions"], dependencies=[Depends(verify_token)])


def _derive_platform_captions(result: dict) -> dict:
    """Locally derive per-platform caption fields from the base caption so a
    regenerate keeps caption_ig / caption_tt / caption_yt_title / _description in
    sync (no extra LLM call). The base LLM already wrote them; we re-derive to
    guarantee none go stale when only `caption` changed."""
    en = (result.get("caption") or "").strip()
    ar = (result.get("caption_ar") or "").strip()
    first_line = en.split("\n", 1)[0].strip()
    return {
        "caption_ig": en,
        "caption_ig_ar": ar or None,
        # Prefer the LLM's tailored variants when present; else derive from base.
        "caption_tt": (result.get("caption_tt") or en[:150]).strip() or None,
        "caption_yt_title": (result.get("caption_yt_title") or first_line)[:97].strip() or None,
        "caption_yt_description": (result.get("caption_yt_description") or en).strip() or None,
    }


class CaptionRequest(BaseModel):
    media_id: str | None = None
    category: str = Field(..., max_length=50)
    tags: list[str] | None = None
    context: str = Field(default="", max_length=1000)


@router.post("/generate")
def gen_caption(body: CaptionRequest):
    result = generate(body.category, body.tags, body.context)
    platform_caps = _derive_platform_captions(result)
    # Surface the per-platform fields to the caller so the UI can push them to
    # the post record (fixes stale caption_ig/caption_tt/caption_yt_* on regen).
    result = {**result, **platform_caps}
    if body.media_id:
        save_caption({
            "media_id": body.media_id,
            "caption": result["caption"],
            "hashtags_en": result["hashtags_en"],
            "hashtags_ar": result["hashtags_ar"],
            "alt_text": result["alt_text"],
            "category": body.category,
            "tags": body.tags,
            "context": body.context or None,
        })
        # Keep the media row's per-platform captions in sync so a later enqueue
        # snapshots the fresh text (not the stale pre-regen values).
        combined = (result.get("caption") or "").strip()
        if platform_caps.get("caption_ig_ar"):
            combined = f"{combined}\n\n{platform_caps['caption_ig_ar']}"
        try:
            update_media(body.media_id, {
                "caption": combined,
                **{k: v for k, v in platform_caps.items() if v is not None},
            })
        except Exception:
            pass  # non-fatal: caller still gets the fields to persist to the post
    return result


@router.get("/{media_id}")
def list_captions(media_id: str):
    media = get_media_by_id(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    return get_captions(media_id)
