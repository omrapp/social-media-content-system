from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from backend.db import get_setting
from backend.api.auth import verify_token

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"], dependencies=[Depends(verify_token)])


@router.get("/status")
def scheduler_status():
    from backend.pipeline.daemon import _scheduler
    from backend.pipeline.slots import next_free_slot, is_slot_due

    running = _scheduler is not None and _scheduler.running
    pipeline_cfg = get_setting("pipeline") or {}
    sched_cfg = get_setting("schedule") or {}

    now = datetime.now(timezone.utc)
    next_slot = None
    current_slot = None

    try:
        slot = next_free_slot(now)
        next_slot = slot.isoformat()
    except Exception:
        pass

    try:
        slot = is_slot_due(now)
        if slot:
            current_slot = slot.isoformat()
    except Exception:
        pass

    return {
        "running": running,
        "auto_publish_enabled": pipeline_cfg.get("auto_publish_enabled", True),
        "auto_create_enabled": pipeline_cfg.get("auto_create_enabled", True),
        "auto_create_mode": pipeline_cfg.get("auto_create_mode", "approval"),
        "auto_create_strategy": pipeline_cfg.get("auto_create_strategy", "diverse"),
        "auto_create_category": pipeline_cfg.get("auto_create_category", ""),
        "daily_slots": sched_cfg.get("daily_slots", []),
        "timezone": sched_cfg.get("timezone", "Asia/Beirut"),
        "max_per_day": sched_cfg.get("max_per_day", 5),
        "next_slot": next_slot,
        "current_slot": current_slot,
    }


@router.post("/run-now")
async def run_now():
    """Manually trigger one auto-create cycle regardless of slot timing."""
    from backend.pipeline.daemon import trigger_auto_create_now
    result = await trigger_auto_create_now()
    return result
