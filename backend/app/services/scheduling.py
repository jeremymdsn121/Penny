"""Scheduling — open-slot proposal (PRD task ``scheduling``).

Pure, I/O-free logic: given a brokerage's working hours, buffer, an appointment
duration, and a set of already-busy intervals (existing appointments now, plus
the connected calendar's free/busy once that lands), compute the open slots in a
date range. Times are produced timezone-aware in the brokerage's local zone (so
calendar events later carry the right wall-clock time).

Conflict rule: a candidate slot is open when, padded by the buffer on both ends,
it overlaps none of the busy intervals.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_DURATION_MIN = 30
DEFAULT_STEP_MIN = 30
DEFAULT_TZ = "America/New_York"

# Dominant IANA timezone per US state/DC. States spanning zones use the most
# populous one — good enough for slot math; not a substitute for a per-property
# timezone if that's ever needed.
STATE_TIMEZONES: dict[str, str] = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix",
    "AR": "America/Chicago", "CA": "America/Los_Angeles", "CO": "America/Denver",
    "CT": "America/New_York", "DE": "America/New_York", "DC": "America/New_York",
    "FL": "America/New_York", "GA": "America/New_York", "HI": "Pacific/Honolulu",
    "ID": "America/Boise", "IL": "America/Chicago", "IN": "America/Indiana/Indianapolis",
    "IA": "America/Chicago", "KS": "America/Chicago", "KY": "America/New_York",
    "LA": "America/Chicago", "ME": "America/New_York", "MD": "America/New_York",
    "MA": "America/New_York", "MI": "America/Detroit", "MN": "America/Chicago",
    "MS": "America/Chicago", "MO": "America/Chicago", "MT": "America/Denver",
    "NE": "America/Chicago", "NV": "America/Los_Angeles", "NH": "America/New_York",
    "NJ": "America/New_York", "NM": "America/Denver", "NY": "America/New_York",
    "NC": "America/New_York", "ND": "America/Chicago", "OH": "America/New_York",
    "OK": "America/Chicago", "OR": "America/Los_Angeles", "PA": "America/New_York",
    "RI": "America/New_York", "SC": "America/New_York", "SD": "America/Chicago",
    "TN": "America/Chicago", "TX": "America/Chicago", "UT": "America/Denver",
    "VT": "America/New_York", "VA": "America/New_York", "WA": "America/Los_Angeles",
    "WV": "America/New_York", "WI": "America/Chicago", "WY": "America/Denver",
}


def resolve_timezone(state: str | None) -> ZoneInfo:
    code = (state or "").strip().upper()
    return ZoneInfo(STATE_TIMEZONES.get(code, DEFAULT_TZ))


def _parse_hhmm(value: str | None, fallback: time) -> time:
    if not value:
        return fallback
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return fallback


def _overlaps(
    start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]
) -> bool:
    return any(start < b_end and b_start < end for b_start, b_end in busy)


def propose_slots(
    *,
    work_start: str | None,
    work_end: str | None,
    buffer_minutes: int,
    tz: ZoneInfo,
    start_day: date,
    days: int = 7,
    duration_minutes: int = DEFAULT_DURATION_MIN,
    step_minutes: int = DEFAULT_STEP_MIN,
    busy: list[tuple[datetime, datetime]] | None = None,
    now: datetime | None = None,
    max_slots: int = 12,
) -> list[datetime]:
    """Return open appointment start times (tz-aware) across ``days`` days.

    ``busy`` intervals must be tz-aware. Slots in the past (relative to ``now``)
    are skipped. Each slot is padded by ``buffer_minutes`` on both sides when
    checking conflicts.
    """
    busy = busy or []
    now = now or datetime.now(tz)
    open_start = _parse_hhmm(work_start, time(9, 0))
    open_end = _parse_hhmm(work_end, time(17, 0))
    buffer = timedelta(minutes=max(0, buffer_minutes or 0))
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=max(5, step_minutes))

    slots: list[datetime] = []
    for offset in range(max(1, days)):
        day = start_day + timedelta(days=offset)
        cursor = datetime.combine(day, open_start, tzinfo=tz)
        day_end = datetime.combine(day, open_end, tzinfo=tz)
        while cursor + duration <= day_end:
            slot_start, slot_end = cursor, cursor + duration
            if slot_start >= now and not _overlaps(
                slot_start - buffer, slot_end + buffer, busy
            ):
                slots.append(slot_start)
                if len(slots) >= max_slots:
                    return slots
            cursor += step
    return slots
