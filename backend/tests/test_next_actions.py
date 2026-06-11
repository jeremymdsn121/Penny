"""Tests for app.services.next_actions — the proactive synthesizer."""

import datetime as dt

from app.services import next_actions as na


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


def test_action_for_task_label_mappings():
    # inspection -> propose times
    assert na.action_for_task_label("Schedule inspection", "123 Main")[1] == (
        "Propose inspection times for 123 Main"
    )
    # appraisal -> lender email
    assert "lender" in na.action_for_task_label("Order appraisal", "X")[0]
    # unknown label -> generic fallback that echoes the label
    offer, prompt = na.action_for_task_label("Random chore", "X")
    assert "Random chore" in prompt


def test_top_actions_sorts_by_priority_and_counts_remainder():
    actions = [{"priority": 3}, {"priority": 1}, {"priority": 2}, {"priority": 1}]
    top, remainder = na.top_actions(actions, limit=2)
    assert [a["priority"] for a in top] == [1, 1]
    assert remainder == 2


async def test_collect_for_transaction_surfaces_all_action_types(monkeypatch):
    today = dt.date.today()
    tx = {
        "id": "t1",
        "address": "123 Main St, Austin, TX",
        "stage": "under_contract",
        "compliance_status": "needs_attention",
        "emd_due_date": (today - dt.timedelta(days=3)).isoformat(),
        "emd_received": False,
        "title_email": "title@example.com",  # present -> not flagged as missing
        "closing_date": (today + dt.timedelta(days=10)).isoformat(),  # within 14d window
        # lender_email intentionally missing
    }
    tasks = [
        {"status": "pending", "due_date": (today - dt.timedelta(days=1)).isoformat(), "label": "Schedule inspection"},
        {"status": "complete", "due_date": today.isoformat(), "label": "already done"},  # skipped
        {"status": "pending", "due_date": None, "label": "undated"},  # skipped
    ]
    deadlines = [
        {"resolved": False, "due_date": (today + dt.timedelta(days=1)).isoformat(), "label": "Inspection"},
    ]
    checklist = [
        {"required": True, "status": "pending"},        # missing -> counts
        {"required": True, "status": "complete"},        # done -> excluded
        {"required": False, "status": "pending"},        # not required -> excluded
    ]
    monkeypatch.setattr(na.sb, "list_transaction_tasks", _async_return(tasks))
    monkeypatch.setattr(na.sb, "list_deadlines_in", _async_return(deadlines))
    monkeypatch.setattr(na.sb, "list_checklist_items", _async_return(checklist))

    actions = await na.collect_for_transaction(tx)
    headlines = [a["headline"] for a in actions]

    assert any("Compliance is flagged" in h for h in headlines)

    emd = next(a for a in actions if "EMD is" in a["headline"])
    assert "3 days overdue" in emd["headline"]
    assert "title" in emd["offer"]  # title email on file -> offer to draft to title

    assert any("Schedule inspection" in h and "overdue" in h for h in headlines)
    assert any("Inspection deadline is tomorrow" in h for h in headlines)
    # required-only counting: exactly 1 missing required item
    assert any("1 required file item" in h for h in headlines)
    # missing lender email surfaces; title (present) does not
    assert any("No lender email" in h for h in headlines)
    assert not any("No title company email" in h for h in headlines)
