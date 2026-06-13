"""Broker review queue (V2 Section 2B).

A single place for the broker-owner to see which deals need attention, so she
doesn't find out a deal is in trouble only when an agent texts her in a panic.
Categories, computed from existing data in one pass:

  - compliance_attention    : compliance_status = 'needs_attention'
  - closing_soon_incomplete : closing within 5 days AND checklist < 80%
  - past_closing_not_closed : closing date is in the past, stage still active
                              (a data-hygiene problem distinct from "rush to
                              complete file" — usually means someone forgot to
                              transition the stage to closed/cancelled)
  - overdue_deadlines       : at least one unresolved past-due deadline
  - emd_overdue             : EMD past due and not received (Section 5)
  - stale_transactions      : no activity in 7+ days
  - needs_agent_routing     : a drafted reply / status update that's stuck —
                              unassigned (ambiguous on a co-listing) or waiting
                              past the escalation window. The broker catches the
                              silent-drop failure mode instead of a reply rotting.

Visible to the brokerage owner (admin). Like the rest of the app, everything is
scoped to the caller's brokerage.
"""

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage, require_admin
from app.services import compliance_checklist

# Admin-only surface (see security.require_admin — a no-op until multi-seat).
router = APIRouter(
    prefix="/broker", tags=["broker"], dependencies=[Depends(require_admin)]
)

ACTIVE_STAGES = ("under_contract", "pending")
STALE_DAYS = 7
CLOSING_SOON_DAYS = 5
INCOMPLETE_PCT = 80
# How long a drafted reply / status update may sit before the broker is pulled in.
ESCALATE_HOURS = 24


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


def build_routing_escalations(
    pending: list[tuple[str, dict[str, Any]]],
    tx_by_id: dict[str, dict[str, Any]],
    agents: dict[str, str | None],
    now: datetime,
    *,
    escalate_hours: int = ESCALATE_HOURS,
) -> list[dict[str, Any]]:
    """Surface drafts that are stuck. Pure + testable.

    ``pending`` is a list of ``(kind_label, row)`` where each row is a
    pending_email_reply / pending_status_update (has ``transaction_id`` and
    ``created_at``). A draft escalates when it's unassigned (no agent to route it
    to — the co-listing ambiguity case) or has waited past ``escalate_hours``.
    """
    rows: list[dict[str, Any]] = []
    for kind_label, item in pending:
        tx = tx_by_id.get(item.get("transaction_id"))
        if tx is None:
            continue
        reasons: list[str] = []
        if not tx.get("agent_id"):
            reasons.append("no agent assigned to act on it")
        created = _parse_dt(item.get("created_at"))
        if created is not None:
            hours = (now - created).total_seconds() / 3600
            if hours >= escalate_hours:
                reasons.append(f"waiting {int(hours)}h for a response")
        if not reasons:
            continue
        rows.append(
            _row(tx, agents.get(tx.get("agent_id")), 0,
                 f"{kind_label} stuck — {', '.join(reasons)}")
        )
    return rows


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

    # Stuck-draft escalation: drafts can outlive the agent who should act on them
    # (co-listing ambiguity, or just no answer). Scoped to all deals, not only
    # active ones, since a reply can land after closing. Best-effort.
    tx_by_id = {t["id"]: t for t in txs}
    pending: list[tuple[str, dict[str, Any]]] = []
    try:
        for r in await sb.list_pending_email_replies(brokerage["id"], status_filter="pending"):
            pending.append(("A drafted reply", r))
    except sb.SupabaseError:
        pass
    try:
        for r in await sb.list_pending_status_updates(brokerage["id"], status_filter="pending"):
            pending.append(("A status update", r))
    except sb.SupabaseError:
        pass
    needs_agent_routing = build_routing_escalations(pending, tx_by_id, agents, now)

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
    past_closing_not_closed: list[dict[str, Any]] = []
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
            if days < 0:
                past = abs(days)
                past_closing_not_closed.append(
                    _row(
                        tx,
                        agent,
                        pct,
                        f"Closed {past} day{'s' if past != 1 else ''} ago, "
                        f"stage still {tx.get('stage') or 'active'}",
                    )
                )
            elif days <= CLOSING_SOON_DAYS and pct < INCOMPLETE_PCT:
                when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
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

        # Rows predating migration 010 have no last_activity_at — fall back to
        # created_at rather than flagging a deal created today as stale.
        last = _parse_dt(tx.get("last_activity_at")) or _parse_dt(tx.get("created_at"))
        if last is not None and (now - last).days >= STALE_DAYS:
            stale_transactions.append(
                _row(tx, agent, pct, f"No activity in {(now - last).days} days")
            )

    return {
        "compliance_attention": compliance_attention,
        "closing_soon_incomplete": closing_soon_incomplete,
        "past_closing_not_closed": past_closing_not_closed,
        "overdue_deadlines": overdue_deadlines,
        "emd_overdue": emd_overdue,
        "stale_transactions": stale_transactions,
        "needs_agent_routing": needs_agent_routing,
        "total": (
            len(compliance_attention)
            + len(closing_soon_incomplete)
            + len(past_closing_not_closed)
            + len(overdue_deadlines)
            + len(emd_overdue)
            + len(stale_transactions)
            + len(needs_agent_routing)
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
