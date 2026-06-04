"""Document-retention policy math (BLOCKERS Hard Limit 6, interim).

Pure helpers for a brokerage's configured retention window. This module computes
*whether* a document is past retention and the cutoff date; it deliberately does
**not** delete anything. Enforcement (purging expired objects from storage) is a
separately-gated follow-up — destroying client transaction documents must never
run blind. Keeping the policy math here, unit-tested and isolated, means the
enforcement seam can be wired later without re-deriving the dates.
"""

from datetime import date, datetime
from typing import Any

DEFAULT_RETENTION_YEARS = 7
MIN_RETENTION_YEARS = 1
MAX_RETENTION_YEARS = 30


def clamp_years(value: Any) -> int:
    """Coerce a retention-years input to a sane integer in [MIN, MAX].

    Anything missing or non-numeric falls back to the 7-year default.
    """
    try:
        years = int(value)
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_YEARS
    return max(MIN_RETENTION_YEARS, min(MAX_RETENTION_YEARS, years))


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def cutoff_date(retention_years: int, today: date | None = None) -> date:
    """The date on/before which a document is past its retention window."""
    today = today or date.today()
    years = clamp_years(retention_years)
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        # Feb 29 -> Feb 28 in a non-leap target year.
        return today.replace(year=today.year - years, day=28)


def is_past_retention(
    created_at: Any, retention_years: int, today: date | None = None
) -> bool:
    """True when a document created at ``created_at`` is older than the window."""
    created = _to_date(created_at)
    if created is None:
        return False  # unknown age -> never auto-eligible for purge
    return created <= cutoff_date(retention_years, today)
