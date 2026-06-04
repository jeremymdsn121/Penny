"""Tests for app.services.retention (HL6 document-retention policy math)."""

import datetime as dt

from app.services import retention as r


def test_clamp_years():
    assert r.clamp_years(7) == 7
    assert r.clamp_years("10") == 10
    assert r.clamp_years(0) == r.MIN_RETENTION_YEARS  # below floor
    assert r.clamp_years(100) == r.MAX_RETENTION_YEARS  # above ceiling
    assert r.clamp_years(None) == r.DEFAULT_RETENTION_YEARS
    assert r.clamp_years("seven") == r.DEFAULT_RETENTION_YEARS


def test_cutoff_date():
    today = dt.date(2026, 6, 1)
    assert r.cutoff_date(7, today) == dt.date(2019, 6, 1)
    # out-of-range years are clamped before the date math
    assert r.cutoff_date(0, today) == dt.date(2025, 6, 1)  # clamped to 1


def test_cutoff_date_leap_day():
    # Feb 29 minus a whole number of years lands on a non-leap year -> Feb 28.
    today = dt.date(2024, 2, 29)
    assert r.cutoff_date(1, today) == dt.date(2023, 2, 28)


def test_is_past_retention():
    today = dt.date(2026, 6, 1)
    # created 8 years ago -> past a 7-year window
    assert r.is_past_retention("2018-01-01", 7, today) is True
    # created 2 years ago -> within the window
    assert r.is_past_retention("2024-06-01T12:00:00Z", 7, today) is False
    # exactly on the cutoff counts as past (<=)
    assert r.is_past_retention("2019-06-01", 7, today) is True
    # unknown / unparseable age is never auto-eligible
    assert r.is_past_retention(None, 7, today) is False
    assert r.is_past_retention("not-a-date", 7, today) is False
