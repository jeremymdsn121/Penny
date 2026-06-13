"""Tests for the deterministic parts of app.services.status_updates: the
weekly cadence gate and the status-update content builder. The scan
orchestration (sends/queues) needs live Supabase + SendGrid and is exercised
manually."""

import datetime as dt

from app.services import status_updates as su


def test_status_update_due_when_never_sent():
    today = dt.date(2026, 6, 13)
    assert su.status_update_due({}, today) is True
    assert su.status_update_due({"last_status_update_at": None}, today) is True


def test_status_update_due_respects_cadence():
    today = dt.date(2026, 6, 13)
    six_days = (today - dt.timedelta(days=6)).isoformat()
    seven_days = (today - dt.timedelta(days=7)).isoformat()
    assert su.status_update_due({"last_status_update_at": six_days}, today) is False
    assert su.status_update_due({"last_status_update_at": seven_days}, today) is True


def test_status_update_due_parses_timestamp_form():
    today = dt.date(2026, 6, 13)
    ts = "2026-06-01T09:30:00+00:00"  # 12 days prior
    assert su.status_update_due({"last_status_update_at": ts}, today) is True


def test_content_includes_standing_upcoming_and_outstanding():
    today = dt.date(2026, 6, 13)
    tx = {
        "address": "123 Main St",
        "stage": "under_contract",
        "closing_date": (today + dt.timedelta(days=10)).isoformat(),
        "emd_amount": 5000,
        "emd_received": False,
        "emd_due_date": (today + dt.timedelta(days=2)).isoformat(),
    }
    deadlines = [
        {"label": "Inspection", "due_date": (today + dt.timedelta(days=3)).isoformat(), "resolved": False},
        {"label": "Old", "due_date": (today - dt.timedelta(days=1)).isoformat(), "resolved": False},  # past → excluded
    ]
    tasks = [{"label": "Order appraisal", "status": "pending",
              "due_date": (today + dt.timedelta(days=5)).isoformat()}]
    checklist = [
        {"label": "Seller disclosure", "required": True, "status": "pending"},
        {"label": "Done item", "required": True, "status": "complete"},  # excluded
    ]
    subject, html, plain = su.build_status_update_content(
        tx, deadlines, tasks, checklist, "Acme Realty", today
    )
    assert "123 Main St" in subject
    assert "under contract" in plain
    assert "Inspection" in plain and "Order appraisal" in plain
    assert "Old" not in plain  # past deadline filtered out
    assert "Seller disclosure" in plain
    assert "Done item" not in plain
    assert "Earnest money receipt" in plain
    assert "Penny" in plain and "Acme Realty" in plain


def test_content_handles_empty_deal_gracefully():
    today = dt.date(2026, 6, 13)
    tx = {"address": "9 Quiet Ln", "stage": "pending"}
    subject, html, plain = su.build_status_update_content(tx, [], [], [], "Acme", today)
    assert "Nothing outstanding" in plain
    assert "<ul>" not in html  # no upcoming/outstanding lists rendered


# --------------------------------------------------------------------------- #
# Staleness guard — what may auto-send when status-updates is autonomous.
# --------------------------------------------------------------------------- #

def _healthy_tx(today):
    """A current-looking deal that should clear every guard."""
    return {
        "address": "123 Main St",
        "stage": "under_contract",
        "closing_date": (today + dt.timedelta(days=20)).isoformat(),
        "last_activity_at": (today - dt.timedelta(days=1)).isoformat(),
        "created_at": (today - dt.timedelta(days=30)).isoformat(),
        "buyer_name": "Jane Buyer",
        "seller_name": "John Seller",
    }


def test_blockers_empty_for_healthy_deal():
    today = dt.date(2026, 6, 13)
    assert su.status_update_blockers(_healthy_tx(today), today) == []


def test_blockers_flag_past_closing_date():
    today = dt.date(2026, 6, 13)
    tx = _healthy_tx(today)
    tx["closing_date"] = (today - dt.timedelta(days=3)).isoformat()
    reasons = su.status_update_blockers(tx, today)
    assert any("closing date" in r for r in reasons)


def test_blockers_flag_missing_closing_date():
    today = dt.date(2026, 6, 13)
    tx = _healthy_tx(today)
    tx["closing_date"] = None
    assert any("no closing date" in r for r in su.status_update_blockers(tx, today))


def test_blockers_flag_stale_deal():
    today = dt.date(2026, 6, 13)
    tx = _healthy_tx(today)
    tx["last_activity_at"] = (today - dt.timedelta(days=su.STALE_DAYS + 1)).isoformat()
    assert any("no activity" in r for r in su.status_update_blockers(tx, today))


def test_blockers_flag_thin_record():
    today = dt.date(2026, 6, 13)
    tx = _healthy_tx(today)
    tx["buyer_name"] = ""
    tx["seller_name"] = ""
    assert any("buyer and seller" in r for r in su.status_update_blockers(tx, today))


def test_blockers_recent_activity_not_stale():
    today = dt.date(2026, 6, 13)
    tx = _healthy_tx(today)
    # Missing last_activity_at falls back to created_at, which is recent enough.
    tx["last_activity_at"] = None
    tx["created_at"] = (today - dt.timedelta(days=su.STALE_DAYS - 1)).isoformat()
    assert su.status_update_blockers(tx, today) == []
