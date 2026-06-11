"""Compliance checklist instantiation and completion math (V2 Section 2A).

When a transaction is created, we instantiate a per-transaction checklist from
the best-matching template (brokerage custom > system default, preferring a
state match). Completion percentage is computed over *required* items only;
'complete', 'waived', and 'not_applicable' all count as done.
"""

from typing import Any

from app.core import supabase_client as sb

DONE_STATUSES = {"complete", "waived", "not_applicable"}


def pct_from_items(items: list[dict[str, Any]]) -> dict[str, int]:
    """Return {'total', 'complete', 'pct'} computed over required items."""
    required = [i for i in items if i.get("required")]
    total = len(required)
    complete = sum(1 for i in required if i.get("status") in DONE_STATUSES)
    pct = round(complete / total * 100) if total else 0
    return {"total": total, "complete": complete, "pct": pct}


async def instantiate_for_transaction(tx: dict[str, Any]) -> list[dict[str, Any]]:
    """Create checklist items for a transaction from its matching template.

    Idempotent: does nothing if the transaction already has checklist items.
    Returns the checklist items (existing or newly created). Never raises on a
    missing template — it just returns an empty checklist.
    """
    existing = await sb.list_checklist_items(tx["id"])
    if existing:
        return existing

    tx_type = tx.get("transaction_type") or "buy_side"
    template = await sb.find_compliance_template(
        tx["brokerage_id"], tx_type, tx.get("state")
    )
    if not template:
        return []

    template_items = await sb.get_template_items(template["id"])
    if not template_items:
        return []

    rows = [
        {
            "transaction_id": tx["id"],
            "template_item_id": ti["id"],
            "label": ti["label"],
            "required": ti.get("required", True),
            "document_required": ti.get("document_required", False),
            "status": "pending",
            "sort_order": ti.get("sort_order", 0),
        }
        for ti in template_items
    ]
    return await sb.insert_checklist_items(rows)


async def pct_for_transactions(transaction_ids: list[str]) -> dict[str, int]:
    """Return {transaction_id: pct} for many transactions in one query.

    Required-only, matching ``pct_from_items``: ``checklist_items_in`` filters
    ``required=eq.true`` server-side, so every row here already counts.
    """
    rows = await sb.checklist_items_in(transaction_ids)
    totals: dict[str, list[int]] = {}  # tx_id -> [total, complete]
    for r in rows:
        tid = r["transaction_id"]
        agg = totals.setdefault(tid, [0, 0])
        agg[0] += 1
        if r.get("status") in DONE_STATUSES:
            agg[1] += 1
    return {
        tid: (round(c / t * 100) if t else 0) for tid, (t, c) in totals.items()
    }
