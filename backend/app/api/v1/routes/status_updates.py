"""Recurring status updates (Autonomy task ``status-updates``).

  * ``POST /status-updates/run`` — the idempotent per-brokerage scan (a dev
    button / scheduled job calls it; the cron route runs it for every brokerage).
  * Pending queue — when status-updates autonomy is off, due updates land here;
    the deal's agent reviews and confirms each send (confirm-gated, never auto).

Sending to the parties is a hard-rule confirmed action: ``/pending/{id}/send``
requires ``confirmed=true``. There is no bypass flag.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage, get_current_user
from app.services import status_updates

router = APIRouter(prefix="/status-updates", tags=["status-updates"])


class SendIn(BaseModel):
    confirmed: bool = False


@router.post("/run")
async def run_scan(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Send/queue any due status updates for this brokerage. Idempotent."""
    return await status_updates.run_status_updates(brokerage["id"])


@router.get("/pending")
async def list_pending(
    transaction_id: str | None = None,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    if transaction_id:
        rows = await sb.list_pending_status_updates_for_transaction(transaction_id)
        # Defence in depth: only return rows the caller's brokerage owns.
        return [r for r in rows if r.get("brokerage_id") == brokerage["id"]]
    return await sb.list_pending_status_updates(brokerage["id"], status_filter="pending")


async def _require_pending(brokerage_id: str, row_id: str) -> dict[str, Any]:
    row = await sb.get_pending_status_update(row_id)
    if row is None or row.get("brokerage_id") != brokerage_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Status update not found")
    return row


@router.post("/pending/{row_id}/send")
async def send_pending(
    row_id: str,
    body: SendIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required before sending.",
        )
    row = await _require_pending(brokerage["id"], row_id)
    if row.get("status") != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Status update is already {row.get('status')}.",
        )
    tx = await sb.get_transaction(brokerage["id"], row["transaction_id"])
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    sent, reason = await status_updates.send_pending_status_update(row, tx, brokerage)
    if not sent:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=reason or "Send failed.")
    return await sb.update_pending_status_update(
        row_id,
        {
            "status": "sent",
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolved_by": user.get("id"),
        },
    )


@router.post("/pending/{row_id}/dismiss")
async def dismiss_pending(
    row_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    row = await _require_pending(brokerage["id"], row_id)
    if row.get("status") != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Status update is already {row.get('status')}.",
        )
    return await sb.update_pending_status_update(
        row_id,
        {
            "status": "dismissed",
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolved_by": user.get("id"),
        },
    )
