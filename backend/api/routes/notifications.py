import requests
from fastapi import APIRouter, Depends

from backend.config import IG_TOKEN, IG_API_BASE
from backend.db import get_notifications, create_notification, _use_supabase, get_supabase, db_retry
from backend.api.auth import verify_token

router = APIRouter(prefix="/api/notifications", tags=["notifications"], dependencies=[Depends(verify_token)])


@router.get("")
def list_notifications(unread: bool = False, limit: int = 20):
    return get_notifications(unread_only=unread, limit=limit)


@router.put("/{notification_id}/read")
def mark_read(notification_id: str):
    if not _use_supabase():
        return {"ok": True}
    db_retry(lambda: get_supabase().table("notifications").update({"read": True}).eq("id", notification_id).execute())
    return {"ok": True}


@router.put("/read-all")
def mark_all_read():
    if not _use_supabase():
        return {"ok": True}
    db_retry(lambda: get_supabase().table("notifications").update({"read": True}).eq("read", False).execute())
    return {"ok": True}


@router.get("/token-status")
def token_status():
    if not IG_TOKEN:
        return {"status": "not_configured", "message": "IG_TOKEN not set"}

    try:
        resp = requests.get(
            f"{IG_API_BASE}/debug_token",
            params={
                "input_token": IG_TOKEN,
                "access_token": IG_TOKEN,
            },
            timeout=10,
        )
        data = resp.json().get("data", {})

        expires_at = data.get("expires_at", 0)
        if expires_at == 0:
            return {"status": "never_expires", "message": "Token does not expire"}

        import datetime
        expiry = datetime.datetime.fromtimestamp(expires_at, tz=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        days_left = (expiry - now).days

        status = "ok"
        if days_left <= 3:
            status = "critical"
        elif days_left <= 7:
            status = "warning"

        if days_left <= 7:
            create_notification(
                "warning" if days_left > 3 else "error",
                "Token expiring soon",
                f"Instagram token expires in {days_left} days ({expiry.strftime('%Y-%m-%d')})",
            )

        return {
            "status": status,
            "days_left": days_left,
            "expires_at": expiry.isoformat(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
