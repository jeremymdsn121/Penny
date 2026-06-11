"""Tests for app.services.reporting (V2 Section 7)."""

import datetime as dt

from app.services import reporting as rp


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


def test_period_start():
    d = dt.date(2026, 5, 17)
    assert rp.period_start("month", d) == dt.date(2026, 5, 1)
    assert rp.period_start("quarter", d) == dt.date(2026, 4, 1)
    assert rp.period_start("ytd", d) == dt.date(2026, 1, 1)
    # quarter boundaries
    assert rp.period_start("quarter", dt.date(2026, 1, 5)) == dt.date(2026, 1, 1)
    assert rp.period_start("quarter", dt.date(2026, 12, 31)) == dt.date(2026, 10, 1)


def test_parse_date_and_deal_volume():
    assert rp._parse_date("2026-05-17T12:00:00Z") == dt.date(2026, 5, 17)
    assert rp._parse_date(None) is None
    assert rp._parse_date("nope") is None
    assert rp._deal_volume({"sale_price": 500000}) == 500000
    assert rp._deal_volume({"list_price": 400000}) == 400000
    # sale_price of 0 falls back to list_price
    assert rp._deal_volume({"sale_price": 0, "list_price": 300000}) == 300000


def test_month_end_including_leap_and_december():
    assert rp._month_end(dt.date(2026, 2, 10)) == dt.date(2026, 2, 28)
    assert rp._month_end(dt.date(2024, 2, 10)) == dt.date(2024, 2, 29)  # leap year
    assert rp._month_end(dt.date(2026, 12, 1)) == dt.date(2026, 12, 31)


def test_build_export_rows_neutralizes_csv_injection():
    txs = [
        {
            "id": "t1",
            "address": "=cmd()",  # spreadsheet formula injection attempt
            "buyer_name": "Bob",
            "seller_name": "Sue",
            "sale_price": 100,
            "closed_at": "2026-05-01T00:00:00Z",
            "agent_id": "a1",
            "created_at": "2026-04-01T00:00:00Z",
        }
    ]
    rows = rp.build_export_rows(txs, {"a1": "Agent A"}, {"t1": 90})
    assert rows[0][0] == "Address"  # header row
    body = rows[1]
    assert body[0] == "'=cmd()"  # leading apostrophe neutralizes the formula
    assert body[3] == "100"
    assert body[6] == "30"  # days to close: Apr 1 -> May 1
    assert body[7] == "90"  # checklist %


async def test_build_summary_excludes_past_closing_from_closing_soon(monkeypatch):
    """A deal whose closing date is in the past must not count as 'closing soon'."""
    today = dt.date.today()
    txs = [
        {
            "id": "a",
            "stage": "under_contract",
            "closing_date": (today + dt.timedelta(days=3)).isoformat(),  # future -> counts
            "last_activity_at": today.isoformat(),
        },
        {
            "id": "b",
            "stage": "under_contract",
            "closing_date": (today - dt.timedelta(days=3)).isoformat(),  # past -> excluded
            "last_activity_at": today.isoformat(),
        },
    ]
    monkeypatch.setattr(
        rp.compliance_checklist, "pct_for_transactions", _async_return({"a": 10, "b": 10})
    )
    monkeypatch.setattr(rp, "_open_items_total", _async_return(0))

    summary = await rp.build_summary("month", txs, deadlines=[], agents={})
    assert summary["at_risk"]["closing_soon_incomplete"] == 1
