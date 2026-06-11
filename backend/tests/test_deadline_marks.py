"""Tests for the deadline-reminder mark/flag math (app.services.deadline_reminders).

``due_marks`` decides which reminder mark to message and which sent-flags to flip.
The subtle behavior — a deadline created close to its due date consumes the
already-passed marks silently and only messages the most-urgent one — is what
these lock in.
"""

import datetime as dt

from app.services import deadline_reminders as dr

TODAY = dt.date(2026, 6, 1)


def _dl(days_until: int, **flags) -> dict:
    due = (TODAY + dt.timedelta(days=days_until)).isoformat()
    return {"due_date": due, **flags}


def test_no_due_date():
    assert dr.due_marks({"due_date": None}, TODAY) == (None, {})


def test_not_yet_within_any_window():
    assert dr.due_marks(_dl(6), TODAY) == (None, {})


def test_5day_fires_and_flags_only_5day():
    fire, flags = dr.due_marks(_dl(5), TODAY)
    assert fire.key == "5day"
    assert flags == {"reminder_5day_sent": True}


def test_5day_already_sent_fires_nothing():
    # Only the 5-day mark is crossed and it's already been sent -> no fire, no
    # flags to write (the scan is a no-op for this deadline).
    assert dr.due_marks(_dl(5, reminder_5day_sent=True), TODAY) == (None, {})


def test_2day_consumes_the_passed_5day_mark():
    # Created at 2 days out: both 2-day and 5-day thresholds are crossed. Only the
    # 2-day is messaged, but both flags flip so the 5-day never fires retroactively.
    fire, flags = dr.due_marks(_dl(2), TODAY)
    assert fire.key == "2day"
    assert flags == {"reminder_2day_sent": True, "reminder_5day_sent": True}


def test_day_of_is_most_urgent_and_flags_all():
    fire, flags = dr.due_marks(_dl(0), TODAY)
    assert fire.key == "day"
    assert flags == {
        "reminder_day_sent": True,
        "reminder_2day_sent": True,
        "reminder_5day_sent": True,
    }


def test_overdue_still_fires_day_mark():
    fire, _ = dr.due_marks(_dl(-3), TODAY)
    assert fire.key == "day"


def test_nothing_left_when_all_marks_sent():
    dl = _dl(0, reminder_day_sent=True, reminder_2day_sent=True, reminder_5day_sent=True)
    fire, _ = dr.due_marks(dl, TODAY)
    assert fire is None
