"""
Telegram webhook receiver.
Validates X-Telegram-Bot-Api-Secret-Token header, dispatches to bot handler.
Webhook URL: /api/telegram/webhook/{secret}
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Header, Request

from backend.config import TELEGRAM_WEBHOOK_SECRET
from backend.api.auth import verify_token
from backend.pipeline.telegram_bot import handle_update

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


@router.post("/webhook/{secret}")
async def webhook(secret: str, request: Request):
    """
    Telegram sends POST here on every update.
    The secret in the path acts as a shared token — set in Caddy and matched here.
    """
    if not TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(403, "Webhook not configured")
    if not hmac.compare_digest(secret, TELEGRAM_WEBHOOK_SECRET):
        raise HTTPException(403, "Invalid webhook secret")

    update = await request.json()
    log.debug("telegram update: %s", update)
    handle_update(update)
    return {"ok": True}


@router.get("/webhook-info", dependencies=[Depends(verify_token)])
async def webhook_info():
    """Proxy getWebhookInfo for debugging."""
    from backend.config import TELEGRAM_BOT_TOKEN
    import requests as _req
    r = _req.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo", timeout=5)
    return r.json()
