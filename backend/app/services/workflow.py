"""Workflow task generation engine (V2 Section 3).

Generates per-transaction tasks from the matching workflow template when a
transaction enters a stage or as a named deadline approaches. Dedupes on the
originating step so re-triggering the same event doesn't create duplicates.
"""

from datetime import date, timedelta
from typing import Any

from app.core import supabase_client as sb


async def _template_steps(tx: dict[str, Any]) -> list[dict[str, Any]]:
    template = await sb.find_workflow_template(
        tx["brokerage_id"], tx.get("transaction_type") or "buy_side", tx.get("state")
    )
    if not template:
        return []
    return await sb.get_workflow_steps(template["id"])


async def _existing_step_ids(transaction_id: str) -> set[str]:
    tasks = await sb.list_transaction_tasks(transaction_id)
    return {t["step_id"] for t in tasks if t.get("step_id")}


async def generate_stage_tasks(tx: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    """Create tasks for steps triggered by entering ``stage``. Idempotent."""
    steps = await _template_steps(tx)
    if not steps:
        return []
    have = await _existing_step_ids(tx["id"])
    today = date.today()
    rows: list[dict[str, Any]] = []
    for s in steps:
        if s.get("trigger_type") != "stage_entry" or s.get("trigger_stage") != stage:
            continue
        if s["id"] in have:
            continue
        due = today + timedelta(days=s.get("due_offset_days") or 0)
        rows.append(
            {
                "transaction_id": tx["id"],
                "step_id": s["id"],
                "label": s["label"],
                "description": s.get("description"),
                "due_date": due.isoformat(),
                "assigned_to_role": s.get("assigned_to_role"),
                "status": "pending",
            }
        )
    return await sb.insert_transaction_tasks(rows)


async def generate_deadline_tasks(
    tx: dict[str, Any], deadline_label: str, days_until: int, deadline_due: str | None
) -> list[dict[str, Any]]:
    """Create tasks for days_before_deadline steps matching a deadline at this mark.

    ``deadline_label`` is the deadline's free-form label; a step matches when its
    trigger_deadline_label keyword appears in it (case-insensitive) and its
    trigger_days equals ``days_until``.
    """
    steps = await _template_steps(tx)
    if not steps:
        return []
    have = await _existing_step_ids(tx["id"])
    label_low = (deadline_label or "").lower()
    rows: list[dict[str, Any]] = []
    for s in steps:
        if s.get("trigger_type") != "days_before_deadline":
            continue
        if s.get("trigger_days") != days_until:
            continue
        keyword = (s.get("trigger_deadline_label") or "").lower()
        if keyword and keyword not in label_low:
            continue
        if s["id"] in have:
            continue
        rows.append(
            {
                "transaction_id": tx["id"],
                "step_id": s["id"],
                "label": s["label"],
                "description": s.get("description"),
                "due_date": deadline_due,
                "assigned_to_role": s.get("assigned_to_role"),
                "status": "pending",
            }
        )
    return await sb.insert_transaction_tasks(rows)


def pending_overdue_count(tasks: list[dict[str, Any]]) -> int:
    """Number of pending tasks past their due date."""
    today = date.today()
    n = 0
    for t in tasks:
        if t.get("status") != "pending":
            continue
        due = t.get("due_date")
        try:
            if due and date.fromisoformat(str(due)[:10]) < today:
                n += 1
        except ValueError:
            pass
    return n
