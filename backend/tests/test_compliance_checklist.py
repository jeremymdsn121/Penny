"""Completion-math tests for app.services.compliance_checklist (V2 Section 2A)."""

from app.services import compliance_checklist as cc


def test_pct_from_items_counts_required_only():
    items = [
        {"required": True, "status": "complete"},        # done
        {"required": True, "status": "waived"},           # done
        {"required": True, "status": "not_applicable"},   # done
        {"required": True, "status": "pending"},          # not done
        {"required": False, "status": "pending"},         # ignored (not required)
    ]
    res = cc.pct_from_items(items)
    assert res == {"total": 4, "complete": 3, "pct": 75}


def test_pct_from_items_empty_and_no_required():
    assert cc.pct_from_items([]) == {"total": 0, "complete": 0, "pct": 0}
    # a checklist with only optional items has no required denominator -> 0, not crash
    assert cc.pct_from_items([{"required": False, "status": "pending"}]) == {
        "total": 0,
        "complete": 0,
        "pct": 0,
    }
