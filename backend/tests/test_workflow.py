"""Trigger-matching tests for app.services.workflow (V2 Section 3)."""

import datetime as dt

from app.services import workflow as wf


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


def _echo_insert(sink=None):
    async def _f(rows):
        if sink is not None:
            sink.extend(rows)
        return rows
    return _f


async def test_generate_stage_tasks_matches_stage_and_sets_due(monkeypatch):
    tx = {"id": "t1", "brokerage_id": "b1", "transaction_type": "buy_side", "state": "TX"}
    steps = [
        {"id": "s1", "trigger_type": "stage_entry", "trigger_stage": "under_contract",
         "label": "Order title", "due_offset_days": 3},
        {"id": "s2", "trigger_type": "stage_entry", "trigger_stage": "pending", "label": "Other"},
        {"id": "s3", "trigger_type": "days_before_deadline", "trigger_stage": "under_contract",
         "label": "Deadline step"},
    ]
    monkeypatch.setattr(wf.sb, "find_workflow_template", _async_return({"id": "tpl"}))
    monkeypatch.setattr(wf.sb, "get_workflow_steps", _async_return(steps))
    monkeypatch.setattr(wf.sb, "list_transaction_tasks", _async_return([]))
    monkeypatch.setattr(wf.sb, "insert_transaction_tasks", _echo_insert())

    rows = await wf.generate_stage_tasks(tx, "under_contract")
    assert [r["step_id"] for r in rows] == ["s1"]  # only the matching stage_entry step
    assert rows[0]["due_date"] == (dt.date.today() + dt.timedelta(days=3)).isoformat()


async def test_generate_stage_tasks_dedupes_existing(monkeypatch):
    tx = {"id": "t1", "brokerage_id": "b1"}
    steps = [{"id": "s1", "trigger_type": "stage_entry", "trigger_stage": "under_contract", "label": "X"}]
    inserted: list = []
    monkeypatch.setattr(wf.sb, "find_workflow_template", _async_return({"id": "tpl"}))
    monkeypatch.setattr(wf.sb, "get_workflow_steps", _async_return(steps))
    monkeypatch.setattr(wf.sb, "list_transaction_tasks", _async_return([{"step_id": "s1"}]))
    monkeypatch.setattr(wf.sb, "insert_transaction_tasks", _echo_insert(inserted))

    rows = await wf.generate_stage_tasks(tx, "under_contract")
    assert rows == []
    assert inserted == []  # nothing re-created for an already-generated step


async def test_generate_deadline_tasks_matches_keyword_and_days(monkeypatch):
    tx = {"id": "t1", "brokerage_id": "b1"}
    steps = [
        {"id": "s1", "trigger_type": "days_before_deadline", "trigger_days": 2,
         "trigger_deadline_label": "inspection", "label": "Remind inspection"}
    ]
    monkeypatch.setattr(wf.sb, "find_workflow_template", _async_return({"id": "tpl"}))
    monkeypatch.setattr(wf.sb, "get_workflow_steps", _async_return(steps))
    monkeypatch.setattr(wf.sb, "list_transaction_tasks", _async_return([]))
    monkeypatch.setattr(wf.sb, "insert_transaction_tasks", _echo_insert())

    # keyword present + days match -> generated
    rows = await wf.generate_deadline_tasks(tx, "Inspection objection", 2, "2026-01-01")
    assert [r["step_id"] for r in rows] == ["s1"]
    # wrong days_until -> no match
    assert await wf.generate_deadline_tasks(tx, "Inspection objection", 5, None) == []
    # keyword absent from the label -> no match
    assert await wf.generate_deadline_tasks(tx, "Appraisal", 2, None) == []


def test_pending_overdue_count():
    today = dt.date.today()
    tasks = [
        {"status": "pending", "due_date": (today - dt.timedelta(days=1)).isoformat()},  # counts
        {"status": "pending", "due_date": (today + dt.timedelta(days=1)).isoformat()},  # future
        {"status": "complete", "due_date": (today - dt.timedelta(days=5)).isoformat()},  # not pending
        {"status": "pending", "due_date": None},  # undated
        {"status": "pending", "due_date": "garbage"},  # unparseable
    ]
    assert wf.pending_overdue_count(tasks) == 1
