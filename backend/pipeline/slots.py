"""
slots — daily publish slot scheduling.

next_free_slot(now) → returns the next unoccupied slot datetime (UTC) based on:
  schedule.daily_slots   list of "HH:MM" strings (default 5 slots)
  schedule.timezone      IANA tz name (default "Asia/Beirut")
  schedule.max_per_day   int cap on posts per day (default 5)

A slot is "occupied" when a post already has slot_at matching that datetime
and status is not cancelled/error/posted.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

DEFAULT_SLOTS = ["08:00", "11:00", "14:00", "18:00", "21:00"]
DEFAULT_TZ = "Asia/Beirut"
DEFAULT_MAX_PER_DAY = 5


def _get_taken_slot_keys(tz: ZoneInfo) -> set[tuple]:
    """
    Return a set of (year, month, day, hour, minute) tuples (in local tz)
    for all posts with slot_at set and status in active states.
    """
    from backend.db import _use_supabase, get_supabase
    if not _use_supabase():
        return set()

    ACTIVE = ["draft", "scheduled", "preview", "publishing"]
    rows = (
        get_supabase()
        .table("posts")
        .select("slot_at")
        .not_.is_("slot_at", "null")
        .in_("status", ACTIVE)
        .execute()
        .data or []
    )

    taken = set()
    for row in rows:
        raw = row.get("slot_at")
        if not raw:
            continue
        try:
            if isinstance(raw, str):
                if raw.endswith("Z"):
                    raw = raw[:-1] + "+00:00"
                dt_utc = datetime.fromisoformat(raw)
                if dt_utc.tzinfo is None:
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            else:
                dt_utc = raw
            dt_local = dt_utc.astimezone(tz)
            taken.add((dt_local.year, dt_local.month, dt_local.day, dt_local.hour, dt_local.minute))
        except Exception:
            pass
    return taken


def is_slot_due(now: datetime | None = None, window_seconds: int = 90) -> datetime | None:
    """
    Return the slot datetime (UTC) if *now* falls within *window_seconds* of any daily slot,
    else return None. Used by the auto-create daemon job to fire once per slot.
    """
    from backend.db import get_setting

    if now is None:
        now = datetime.now(timezone.utc)

    sched = get_setting("schedule") or {}
    slots_raw = sched.get("daily_slots", DEFAULT_SLOTS)
    tz_name = sched.get("timezone", DEFAULT_TZ)
    max_per_day = int(sched.get("max_per_day", DEFAULT_MAX_PER_DAY))

    tz = ZoneInfo(tz_name.strip())
    parsed: list[tuple[int, int]] = []
    for s in slots_raw:
        try:
            h, m = map(int, str(s).split(":"))
            parsed.append((h, m))
        except Exception:
            pass
    parsed.sort()
    active_slots = parsed[:max_per_day]

    now_local = now.astimezone(tz)
    today = now_local.date()

    for hour, minute in active_slots:
        slot_local = datetime(today.year, today.month, today.day, hour, minute, 0, tzinfo=tz)
        slot_utc = slot_local.astimezone(timezone.utc)
        delta = abs((now - slot_utc).total_seconds())
        if delta <= window_seconds:
            return slot_utc

    return None


def next_free_slot(now: datetime | None = None) -> datetime:
    """
    Return the next unoccupied daily slot as a UTC datetime.
    Raises RuntimeError if no slot found in 30 days.
    """
    from backend.db import get_setting

    if now is None:
        now = datetime.now(timezone.utc)

    sched = get_setting("schedule") or {}
    slots_raw = sched.get("daily_slots", DEFAULT_SLOTS)
    tz_name = sched.get("timezone", DEFAULT_TZ)
    max_per_day = int(sched.get("max_per_day", DEFAULT_MAX_PER_DAY))

    tz = ZoneInfo(tz_name.strip())

    # Parse + sort slot times; cap at max_per_day
    parsed: list[tuple[int, int]] = []
    for s in slots_raw:
        try:
            h, m = map(int, str(s).split(":"))
            parsed.append((h, m))
        except Exception:
            pass
    parsed.sort()
    active_slots = parsed[:max_per_day]

    if not active_slots:
        raise RuntimeError("No daily_slots configured")

    # Enhancement C: when enabled, order each day's free slots by historical
    # engagement for that hour (best first) instead of strictly chronologically.
    # Falls back to time order whenever there is no analytics signal yet.
    day_slots = active_slots
    if sched.get("optimize_times", True):
        try:
            from backend.pipeline.feedback_aggregator import slot_engagement_scores
            scores = slot_engagement_scores(tz_name)
        except Exception as exc:
            log.warning("next_free_slot: engagement scores unavailable (%s)", exc)
            scores = {}
        if scores:
            day_slots = sorted(active_slots, key=lambda hm: (-scores.get(hm[0], 0.0), hm[0], hm[1]))

    taken = _get_taken_slot_keys(tz)
    now_local = now.astimezone(tz)

    for day_offset in range(30):
        check_date: date = (now_local + timedelta(days=day_offset)).date()

        for hour, minute in day_slots:
            slot_local = datetime(
                check_date.year, check_date.month, check_date.day,
                hour, minute, 0, tzinfo=tz,
            )
            slot_utc = slot_local.astimezone(timezone.utc)

            if slot_utc <= now:
                continue

            key = (check_date.year, check_date.month, check_date.day, hour, minute)
            if key in taken:
                continue

            log.debug("next_free_slot → %s (%s)", slot_utc.isoformat(), slot_local.strftime("%a %d %b %H:%M %Z"))
            return slot_utc

    raise RuntimeError("No free slot found in next 30 days — increase max_per_day or add more daily_slots")
