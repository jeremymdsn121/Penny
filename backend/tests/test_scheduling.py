"""Slot-math tests for app.services.scheduling (pure, I/O-free)."""

import datetime as dt
from zoneinfo import ZoneInfo

from app.services import scheduling as sc


def test_resolve_timezone():
    assert sc.resolve_timezone("CA") == ZoneInfo("America/Los_Angeles")
    assert sc.resolve_timezone("tx") == ZoneInfo("America/Chicago")  # case-insensitive
    assert sc.resolve_timezone("ZZ") == ZoneInfo(sc.DEFAULT_TZ)  # unknown -> default
    assert sc.resolve_timezone(None) == ZoneInfo(sc.DEFAULT_TZ)


def test_parse_hhmm():
    assert sc._parse_hhmm("08:30", dt.time(9, 0)) == dt.time(8, 30)
    assert sc._parse_hhmm(None, dt.time(9, 0)) == dt.time(9, 0)
    assert sc._parse_hhmm("garbage", dt.time(9, 0)) == dt.time(9, 0)


def test_propose_slots_basic_and_work_hour_bounds():
    tz = ZoneInfo("America/New_York")
    start = dt.date(2026, 6, 1)
    now = dt.datetime(2026, 5, 1, tzinfo=tz)  # well before the window -> nothing filtered
    slots = sc.propose_slots(
        work_start="09:00", work_end="11:00", buffer_minutes=0, tz=tz,
        start_day=start, days=1, duration_minutes=30, step_minutes=30, now=now,
    )
    # 09:00, 09:30, 10:00, 10:30 — the last 30-min slot must still finish by 11:00.
    assert slots == [
        dt.datetime(2026, 6, 1, 9, 0, tzinfo=tz),
        dt.datetime(2026, 6, 1, 9, 30, tzinfo=tz),
        dt.datetime(2026, 6, 1, 10, 0, tzinfo=tz),
        dt.datetime(2026, 6, 1, 10, 30, tzinfo=tz),
    ]
    assert all(s.tzinfo is not None for s in slots)


def test_propose_slots_skips_past():
    tz = ZoneInfo("America/New_York")
    now = dt.datetime(2026, 6, 1, 9, 45, tzinfo=tz)  # 09:00/09:30 already past
    slots = sc.propose_slots(
        work_start="09:00", work_end="11:00", buffer_minutes=0, tz=tz,
        start_day=dt.date(2026, 6, 1), days=1, now=now,
    )
    assert dt.datetime(2026, 6, 1, 9, 0, tzinfo=tz) not in slots
    assert slots[0] == dt.datetime(2026, 6, 1, 10, 0, tzinfo=tz)


def test_propose_slots_buffer_excludes_conflicts():
    tz = ZoneInfo("America/New_York")
    now = dt.datetime(2026, 5, 1, tzinfo=tz)
    busy = [(dt.datetime(2026, 6, 1, 9, 45, tzinfo=tz), dt.datetime(2026, 6, 1, 10, 15, tzinfo=tz))]
    slots = sc.propose_slots(
        work_start="09:00", work_end="12:00", buffer_minutes=15, tz=tz,
        start_day=dt.date(2026, 6, 1), days=1, duration_minutes=30, step_minutes=30,
        busy=busy, now=now,
    )
    nine = dt.datetime(2026, 6, 1, 9, 0, tzinfo=tz)
    nine_thirty = dt.datetime(2026, 6, 1, 9, 30, tzinfo=tz)
    ten = dt.datetime(2026, 6, 1, 10, 0, tzinfo=tz)
    ten_thirty = dt.datetime(2026, 6, 1, 10, 30, tzinfo=tz)
    # padded by 15m on each side, 09:30 and 10:00 collide with the busy block.
    assert nine_thirty not in slots
    assert ten not in slots
    # 09:00 (08:45–09:15) clears the busy block; 10:30 (10:15–11:00) starts exactly at busy-end.
    assert nine in slots
    assert ten_thirty in slots


def test_propose_slots_respects_max_slots():
    tz = ZoneInfo("America/New_York")
    now = dt.datetime(2026, 5, 1, tzinfo=tz)
    slots = sc.propose_slots(
        work_start="09:00", work_end="17:00", buffer_minutes=0, tz=tz,
        start_day=dt.date(2026, 6, 1), days=5, now=now, max_slots=3,
    )
    assert len(slots) == 3
