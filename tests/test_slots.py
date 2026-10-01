"""
Tests for pipeline.slots.next_free_slot:
- Returns a future datetime
- Skips past slots
- Uses correct timezone (ZoneInfo)
- Strips trailing whitespace from timezone name (Asia/Jerusalem regression)
- Raises RuntimeError when no slots configured
- Respects max_per_day cap
- Skips taken slots, advances to next
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch


FAKE_SCHEDULE = {
    "daily_slots": ["08:00", "11:00", "14:00", "18:00", "21:00"],
    "timezone": "Asia/Jerusalem",
    "max_per_day": 5,
}


def _next_slot(now=None, schedule=None, taken=None):
    from backend.pipeline.slots import next_free_slot
    sched = schedule if schedule is not None else FAKE_SCHEDULE
    taken_keys = taken if taken is not None else set()
    with patch("backend.db.get_setting", return_value=sched), \
         patch("backend.pipeline.slots._get_taken_slot_keys", return_value=taken_keys):
        return next_free_slot(now=now)


def test_returns_future_slot():
    now = datetime(2026, 6, 5, 5, 0, 0, tzinfo=timezone.utc)  # 08:00 Jerusalem = 05:00 UTC
    slot = _next_slot(now=now)
    assert slot > now


def test_slot_is_utc_aware():
    slot = _next_slot()
    assert slot.tzinfo is not None
    assert slot.tzinfo == timezone.utc or "UTC" in str(slot.tzinfo)


def test_past_slots_skipped():
    """All slots for today already past → returns tomorrow's first slot."""
    # 22:00 UTC = midnight-ish Jerusalem — all today's slots are gone
    now = datetime(2026, 6, 5, 22, 0, 0, tzinfo=timezone.utc)
    slot = _next_slot(now=now)
    assert slot > now
    # Should be tomorrow's 08:00 Jerusalem = 05:00 UTC
    assert slot.hour == 5
    assert slot.date() > now.date()


def test_taken_slot_skipped():
    """If next natural slot is taken, function advances to the one after."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Jerusalem")
    now = datetime(2026, 6, 5, 4, 0, 0, tzinfo=timezone.utc)  # before 08:00 Jerusalem

    # Mark 08:00 slot on 2026-06-05 as taken
    taken = {(2026, 6, 5, 8, 0)}
    slot = _next_slot(now=now, taken=taken)

    # Should skip 08:00 → return 11:00 Jerusalem slot
    slot_local = slot.astimezone(tz)
    assert (slot_local.hour, slot_local.minute) == (11, 0)


def test_trailing_space_timezone_stripped():
    """Regression: ZoneInfo('Asia/Jerusalem ') raises KeyError; name must be stripped."""
    sched = {**FAKE_SCHEDULE, "timezone": "Asia/Jerusalem "}  # trailing space
    slot = _next_slot(schedule=sched)
    assert slot > datetime.now(timezone.utc)


def test_no_slots_raises_runtime_error():
    sched = {**FAKE_SCHEDULE, "daily_slots": []}
    with patch("backend.db.get_setting", return_value=sched), \
         patch("backend.pipeline.slots._get_taken_slot_keys", return_value=set()):
        from backend.pipeline.slots import next_free_slot
        with pytest.raises(RuntimeError, match="No daily_slots configured"):
            next_free_slot()


def test_max_per_day_caps_slots():
    """max_per_day=2 means only first 2 configured slots are active."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Jerusalem")
    sched = {**FAKE_SCHEDULE, "max_per_day": 2}
    now = datetime(2026, 6, 5, 4, 0, 0, tzinfo=timezone.utc)

    # Mark both early slots taken
    taken = {(2026, 6, 5, 8, 0), (2026, 6, 5, 11, 0)}
    slot = _next_slot(now=now, schedule=sched, taken=taken)

    # 14:00 slot should be excluded (max_per_day=2 caps at 08:00 and 11:00)
    # So next available must be tomorrow's 08:00
    slot_local = slot.astimezone(tz)
    assert slot_local.date().day == 6  # next day
    assert (slot_local.hour, slot_local.minute) == (8, 0)


def test_all_30_days_full_raises():
    """When every slot across 30 days is taken → RuntimeError."""
    from zoneinfo import ZoneInfo
    from datetime import timedelta
    tz = ZoneInfo("Asia/Jerusalem")
    now = datetime(2026, 6, 5, 0, 0, 0, tzinfo=timezone.utc)
    sched = {**FAKE_SCHEDULE, "max_per_day": 1, "daily_slots": ["08:00"]}

    # Build taken set using real date arithmetic to handle month boundaries
    taken = set()
    for d in range(32):
        local = (now + timedelta(days=d)).astimezone(tz)
        taken.add((local.year, local.month, local.day, 8, 0))

    with patch("backend.db.get_setting", return_value=sched), \
         patch("backend.pipeline.slots._get_taken_slot_keys", return_value=taken):
        from backend.pipeline.slots import next_free_slot
        with pytest.raises(RuntimeError, match="No free slot found"):
            next_free_slot(now=now)
