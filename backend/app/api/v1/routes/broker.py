"""Broker review queue (V2 Section 2B).

A single place for the broker-owner to see which deals need attention, so she
doesn't find out a deal is in trouble only when an agent texts her in a panic.
Four categories, computed from existing data in one pass:

  - compliance_attention   : compliance_status = 'needs_attention'
  - closing_soon_incomplete: closing within 5 days AND checklist < 80%
  - overdue_deadlines      : at least one unresolved past-due deadline
  - emd_overdue            : EMD past due and not received (Section 5)
  - stale_transactions     : no activity in 7+ days

Visible to the brokerage owner (admin). Like the rest of the app, everything is
scoped to the caller's brokerage.
"""

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.services import compliance_checklist

router = APIRouter(prefix="/broker", tags=["broker"])

ACTIVE_STAGES = ("under_contract", "pending")
STALE_DAYS = 7
CLOSING_SOON_DAYS = 5
INCOMPLETE_PCT = 80


def _is_active(tx: dict[str, Any]) -> bool:
    return (tx.get("stage") or "under_contract") in ACTIVE_STAGES


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _row(tx: dict[str, Any], agent_name: str | None, pct: int, reason: str) -> dict[str, Any]:
    return {
        "id": tx["id"],
        "address": tx.get("address"),
        "buyer_name": tx.get("buyer_name"),
        "closing_date": tx.get("closing_date"),
        "stage": tx.get("stage"),
        "checklist_pct": pct,
        "agent_name": agent_name,
        "reason": reason,
    }


@router.get("/review-queue")
async def review_queue(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    today = date.today()
    now = datetime.now(timezone.utc)

    txs = await sb.list_transactions(brokerage["id"])
    active = [t for t in txs if _is_active(t)]
    active_ids = [t["id"] for t in active]

    pct_map = await compliance_checklist.pct_for_transactions(active_ids)
    agents = {a["id"]: a.get("name") for a in await sb.list_agents(brokerage["id"])}
    deadlines = await sb.list_deadlines_in(active_ids)

    # Count unresolved, past-due deadlines per transaction.
    overdue_by_tx: dict[str, int] = {}
    for d in deadlines:
        if d.get("resolved"):
            continue
        due = _parse_date(d.get("due_date"))
        if due and due < today:
            overdue_by_tx[d["transaction_id"]] = overdue_by_tx.get(d["transaction_id"], 0) + 1

    compliance_attention: list[dict[str, Any]] = []
    closing_soon_incomplete: list[dict[str, Any]] = []
    overdue_deadlines: list[dict[str, Any]] = []
    emd_overdue: list[dict[str, Any]] = []
    stale_transactions: list[dict[str, Any]] = []

    for tx in active:
        pct = pct_map.get(tx["id"], 0)
        agent = agents.get(tx.get("agent_id"))

        if tx.get("compliance_status") == "needs_attention":
            compliance_attention.append(
                _row(tx, agent, pct, "Compliance flagged — needs attention")
            )

        closing = _parse_date(tx.get("closing_date"))
        if closing is not None:
            days = (closing - today).days
            if days <= CLOSING_SOON_DAYS and pct < INCOMPLETE_PCT:
                when = "today" if days == 0 else (
                    f"in {days} days" if days > 0 else f"{abs(days)} days ago"
                )
                closing_soon_incomplete.append(
                    _row(tx, agent, pct, f"Closing {when}, file {pct}% complete")
                )

        n_overdue = overdue_by_tx.get(tx["id"], 0)
        if n_overdue:
            overdue_deadlines.append(
                _row(tx, agent, pct, f"{n_overdue} overdue deadline{'s' if n_overdue != 1 else ''}")
            )

        emd_due = _parse_date(tx.get("emd_due_date"))
        if emd_due is not None and not tx.get("emd_received") and emd_due < today:
            emd_overdue.append(
                _row(tx, agent, pct, f"EMD not received — was due {tx.get('emd_due_date')}")
            )

        last = _parse_dt(tx.get("last_activity_at"))
        if last is None or (now - last).days >= STALE_DAYS:
            days_txt = f"{(now - last).days} days" if last else "a while"
            stale_transactions.append(_row(tx, agent, pct, f"No activity in {days_txt}"))

    return {
        "compliance_attention": compliance_attention,
        "closing_soon_incomplete": closing_soon_incomplete,
        "overdue_deadlines": overdue_deadlines,
        "emd_overdue": emd_overdue,
        "stale_transactions": stale_transactions,
        "total": (
            len(compliance_attention)
            + len(closing_soon_incomplete)
            + len(overdue_deadlines)
            + len(emd_overdue)
            + len(stale_transactions)
        ),
    }


class ReviewNoteIn(BaseModel):
    note: str


@router.post("/transactions/{transaction_id}/review-note")
async def add_review_note(
    transaction_id: str,
    body: ReviewNoteIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Append a broker review note to a transaction (tagged broker_review)."""
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Note is empty")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"[{stamp}] (broker review) {note}"
    combined = f"{(tx.get('notes') or '').strip()}\n{entry}".strip()
    updated = await sb.update_transaction(brokerage["id"], transaction_id, {"notes": combined})
    return {"notes": updated.get("notes") if updated else combined}
