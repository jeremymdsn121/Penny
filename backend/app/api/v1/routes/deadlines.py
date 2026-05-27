"""Deadline tracking + reminders (PRD task ``deadline-reminders``).

Deadlines hang off a transaction (the ``deadlines`` table is scoped through its
parent transaction, which carries the brokerage_id). Every handler verifies the
parent transaction belongs to the caller's brokerage before reading or writing,
because the backend uses the service-role key and bypasses RLS.

Reminders fire from POST /deadlines/run-reminders (idempotent scan); a scheduled
job calls it. Notifying outside parties is external comms, so it is gated:
``/notify-parties`` always requires confirmation, and the scan only auto-emails
parties when the brokerage has made ``deadline-reminders`` autonomous.
"""

import asyncio
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.services import deadline_reminders, email_client

router = APIRouter(prefix="/deadlines", tags=["deadlines"])


class DeadlineCreate(BaseModel):
    transaction_id: str
    label: str
    due_date: str | None = None  # YYYY-MM-DD
    responsible_parties: list[str] = []
    status: str | None = None


class DeadlineUpdate(BaseModel):
    label: str | None = None
    due_date: str | None = None
    responsible_parties: list[str] | None = None
    status: str | None = None


class NotifyPartiesIn(BaseModel):
    confirmed: bool = False


def _valid_due(due_date: str | None) -> None:
    if due_date:
        try:
            date.fromisoformat(due_date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="due_date must be YYYY-MM-DD.",
            )


def _clean_parties(keys: list[str] | None) -> list[str]:
    """Keep only recognised party role keys, de-duplicated in order."""
    if not keys:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k in email_client.PARTY_KEYS and k not in seen:
            seen.add(k)
            out.append(k)
    return out


async def _require_owned_transaction(brokerage_id: str, transaction_id: str) -> dict[str, Any]:
    tx = await sb.get_transaction(brokerage_id, transaction_id)
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found"
        )
    return tx


async def _scoped_deadline(
    brokerage_id: str, deadline_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a deadline and confirm its transaction belongs to the brokerage."""
    deadline = await sb.get_deadline(deadline_id)
    if deadline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deadline not found")
    tx = await sb.get_transaction(brokerage_id, deadline.get("transaction_id"))
    if tx is None:
        # Belongs to another brokerage (or orphaned) — treat as not found.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deadline not found")
    return deadline, tx


# --------------------------------------------------------------------------- #
# Reminder scan — declared before the dynamic routes for clarity.
# --------------------------------------------------------------------------- #

@router.post("/run-reminders")
async def run_reminders(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Fire any due deadline reminders for this brokerage. Idempotent."""
    return await deadline_reminders.run_reminders(brokerage["id"])


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #

@router.get("")
async def list_for_transaction(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    await _require_owned_transaction(brokerage["id"], transaction_id)
    return await sb.list_deadlines_for_transaction(transaction_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    body: DeadlineCreate,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    await _require_owned_transaction(brokerage["id"], body.transaction_id)
    _valid_due(body.due_date)
    data: dict[str, Any] = {
        "transaction_id": body.transaction_id,
        "label": body.label,
        "responsible_parties": _clean_parties(body.responsible_parties),
    }
    if body.due_date:
        data["due_date"] = body.due_date
    data["status"] = body.status or "pending"
    return await sb.insert_deadline(data)


@router.patch("/{deadline_id}")
async def update(
    deadline_id: str,
    body: DeadlineUpdate,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    await _scoped_deadline(brokerage["id"], deadline_id)
    data = body.model_dump(exclude_unset=True)
    if "due_date" in data:
        _valid_due(data["due_date"])
    if "responsible_parties" in data:
        data["responsible_parties"] = _clean_parties(data["responsible_parties"])
    updated = await sb.update_deadline(deadline_id, data)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deadline not found")
    return updated


@router.delete("/{deadline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    deadline_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    await _scoped_deadline(brokerage["id"], deadline_id)
    await sb.delete_deadline(deadline_id)


# --------------------------------------------------------------------------- #
# Manual party notification — explicit, confirmed send (the gate for external
# comms). Allowed regardless of autonomy because a human is confirming here.
# --------------------------------------------------------------------------- #

@router.post("/{deadline_id}/notify-parties")
async def notify_parties(
    deadline_id: str,
    body: NotifyPartiesIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required before notifying parties.",
        )
    deadline, tx = await _scoped_deadline(brokerage["id"], deadline_id)
    keys = deadline.get("responsible_parties") or []
    parties = email_client.gather_parties_by_keys(tx, keys)
    if not parties:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No responsible parties with an email on file to notify.",
        )
    subject, html, plain = deadline_reminders.build_party_notice(
        tx, deadline, brokerage.get("name", "your brokerage")
    )
    sent = await asyncio.to_thread(
        email_client.send_email,
        to_emails=[p["email"] for p in parties],
        subject=subject,
        html=html,
        plain=plain,
    )
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send — email isn't configured or the send failed.",
        )
    return {"sent": True, "recipients": [p["email"] for p in parties]}
