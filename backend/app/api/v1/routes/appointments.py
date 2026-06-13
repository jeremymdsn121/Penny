"""Appointment scheduling (PRD task ``scheduling``).

Appointments (showings, inspections, walk-throughs) hang off a transaction
(`appointments` table, scoped through its parent — verified per request since
the backend bypasses RLS). ``/propose`` computes open slots from the brokerage's
working hours + buffer, avoiding existing appointments (and the connected
calendar's busy times once that lands). ``/book`` is the confirmed write that
records the appointment and creates a calendar event when one is connected.

Booking has an external effect (calendar invite), so it's gated: confirmation is
required unless the brokerage's ``scheduling`` task is autonomous — mirroring the
intro-email pattern.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.services import activity, calendar_provider, email_client, scheduling

router = APIRouter(prefix="/appointments", tags=["appointments"])


class ProposeIn(BaseModel):
    transaction_id: str
    start_date: str | None = None  # YYYY-MM-DD; defaults to today (brokerage tz)
    days: int = 7
    duration_minutes: int = scheduling.DEFAULT_DURATION_MIN


class BookIn(BaseModel):
    transaction_id: str
    type: str = "showing"
    scheduled_at: str  # ISO 8601, ideally a proposed slot
    duration_minutes: int = scheduling.DEFAULT_DURATION_MIN
    attendees: list[str] = []
    confirmed: bool = False


class AppointmentUpdate(BaseModel):
    type: str | None = None
    scheduled_at: str | None = None
    attendees: list[str] | None = None
    confirmed: bool | None = None


class NotifyPartiesIn(BaseModel):
    confirmed: bool = False
    parties: list[str] = []  # role keys (buyer/listing_agent/…)


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


def _parse_dt(value: str, tz=None) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scheduled_at must be an ISO 8601 datetime.",
        )
    # A naive datetime stored into a timestamptz column is assumed-UTC by
    # Postgres, silently shifting the local time. Anchor it to the brokerage
    # timezone when the caller supplied no offset.
    if parsed.tzinfo is None and tz is not None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


async def _require_owned_transaction(brokerage_id: str, transaction_id: str) -> dict[str, Any]:
    tx = await sb.get_transaction(brokerage_id, transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return tx


async def _scoped_appointment(
    brokerage_id: str, appointment_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    appt = await sb.get_appointment(appointment_id)
    if appt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    tx = await sb.get_transaction(brokerage_id, appt.get("transaction_id"))
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return appt, tx


async def _resolve_agent(
    brokerage: dict[str, Any], tx: dict[str, Any]
) -> dict[str, Any] | None:
    """The deal's assigned agent row, or None. Swallows lookup errors — a missing
    agent never blocks scheduling (it just falls back to brokerage defaults)."""
    agent_id = tx.get("agent_id")
    if not agent_id:
        return None
    try:
        return await sb.get_agent(brokerage["id"], agent_id)
    except sb.SupabaseError:
        return None


async def _resolve_account(
    brokerage: dict[str, Any], tx: dict[str, Any]
) -> dict[str, Any] | None:
    """The calendar a deal should use: its agent's if connected, else the
    brokerage's."""
    agent = await _resolve_agent(brokerage, tx)
    return calendar_provider.resolve_account(brokerage, agent)


async def _scheduling_autonomous(brokerage_id: str) -> bool:
    try:
        autonomy = await sb.get_task_autonomy(brokerage_id)
    except Exception:
        return False
    return any(
        r.get("task_id") == "scheduling" and r.get("autonomous") for r in autonomy
    )


async def _busy_intervals(
    brokerage: dict[str, Any],
    account: dict[str, Any] | None,
    start: datetime,
    end: datetime,
) -> tuple[list[tuple[datetime, datetime]], bool]:
    """Existing local appointments (padded to a default duration) + the resolved
    calendar's busy times. The bool is False when a connected calendar couldn't be
    read — the caller surfaces that so slots aren't trusted as conflict-free."""
    txs = await sb.list_transactions(brokerage["id"])
    appts = await sb.list_appointments_in([t["id"] for t in txs])
    busy: list[tuple[datetime, datetime]] = []
    for a in appts:
        when = a.get("scheduled_at")
        if not when:
            continue
        try:
            b_start = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        except ValueError:
            continue
        busy.append((b_start, b_start + timedelta(minutes=scheduling.DEFAULT_DURATION_MIN)))
    cal_busy, cal_ok = await calendar_provider.get_busy_checked(account, start, end)
    busy.extend(cal_busy)
    return busy, cal_ok


async def _sync_event_update(
    account: dict[str, Any] | None,
    event_id: str,
    appt: dict[str, Any],
    tx: dict[str, Any],
) -> None:
    """Mirror an appointment change onto its calendar event (reschedule/retitle)."""
    try:
        start = datetime.fromisoformat(str(appt["scheduled_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return
    end = start + timedelta(minutes=scheduling.DEFAULT_DURATION_MIN)
    appt_type = appt.get("type") or "showing"
    address = (tx.get("address") or "the property").strip()
    summary = f"{appt_type.replace('_', ' ').title()} — {address}"
    await calendar_provider.update_event(
        account,
        event_id,
        summary=summary,
        start=start,
        end=end,
        attendees=[a for a in (appt.get("attendees") or []) if a and a.strip()],
    )


@router.post("/propose")
async def propose(
    body: ProposeIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    tx = await _require_owned_transaction(brokerage["id"], body.transaction_id)
    agent = await _resolve_agent(brokerage, tx)
    account = calendar_provider.resolve_account(brokerage, agent)
    work_start, work_end, buffer_minutes = scheduling.resolve_working_hours(brokerage, agent)
    tz = scheduling.resolve_timezone(brokerage.get("state"))
    now = datetime.now(tz)
    if body.start_date:
        try:
            start_day = datetime.strptime(body.start_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date must be YYYY-MM-DD.",
            )
    else:
        start_day = now.date()

    window_end = datetime.combine(
        start_day + timedelta(days=max(1, body.days)), datetime.min.time(), tzinfo=tz
    )
    busy, cal_ok = await _busy_intervals(brokerage, account, now, window_end)
    slots = scheduling.propose_slots(
        work_start=work_start,
        work_end=work_end,
        buffer_minutes=buffer_minutes,
        tz=tz,
        start_day=start_day,
        days=max(1, body.days),
        duration_minutes=body.duration_minutes,
        busy=busy,
        now=now,
    )
    return {
        "timezone": tz.key,
        "duration_minutes": body.duration_minutes,
        "calendar": calendar_provider.account_status(account),
        # True only when a connected calendar couldn't be read — the UI warns that
        # these slots may not account for real events.
        "calendar_unavailable": account is not None and not cal_ok,
        "slots": [s.isoformat() for s in slots],
    }


@router.post("/book")
async def book(
    body: BookIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    tx = await _require_owned_transaction(brokerage["id"], body.transaction_id)
    autonomous = await _scheduling_autonomous(brokerage["id"])
    if not body.confirmed and not autonomous:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required before booking.",
        )
    tz = scheduling.resolve_timezone(brokerage.get("state"))
    start = _parse_dt(body.scheduled_at, tz)
    end = start + timedelta(minutes=body.duration_minutes)
    address = (tx.get("address") or "the property").strip()
    summary = f"{body.type.replace('_', ' ').title()} — {address}"

    account = await _resolve_account(brokerage, tx)
    event_id = await calendar_provider.create_event(
        account,
        summary=summary,
        start=start,
        end=end,
        attendees=[a for a in body.attendees if a and a.strip()],
    )

    appt = await sb.insert_appointment({
        "transaction_id": body.transaction_id,
        "type": body.type,
        "showing_method": brokerage.get("showing_method"),
        "scheduled_at": start.isoformat(),
        "confirmed": True,
        "calendar_event_id": event_id,
        "attendees": [a for a in body.attendees if a and a.strip()],
    })
    # "You" booked when an explicit confirm came in; "Penny" when the autonomous
    # scheduling task let it proceed without one.
    await activity.record(
        brokerage_id=brokerage["id"],
        transaction_id=body.transaction_id,
        kind="appointment_booked",
        title=f"{body.type.replace('_', ' ').title()} booked",
        detail=start.strftime("%b %d, %Y at %I:%M %p ").strip() + tz.key,
        actor="You" if body.confirmed else "Penny",
        via="web" if body.confirmed else "system",
    )
    return {"appointment": appt, "calendar_event_created": event_id is not None}


@router.get("")
async def list_for_transaction(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    await _require_owned_transaction(brokerage["id"], transaction_id)
    return await sb.list_appointments_for_transaction(transaction_id)


@router.patch("/{appointment_id}")
async def update(
    appointment_id: str,
    body: AppointmentUpdate,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    appt, tx = await _scoped_appointment(brokerage["id"], appointment_id)
    data = body.model_dump(exclude_unset=True)
    if "scheduled_at" in data and data["scheduled_at"]:
        tz = scheduling.resolve_timezone(brokerage.get("state"))
        data["scheduled_at"] = _parse_dt(data["scheduled_at"], tz).isoformat()
    updated = await sb.update_appointment(appointment_id, data)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    # Mirror reschedule / retitle / attendee changes onto the calendar event.
    event_id = updated.get("calendar_event_id") or appt.get("calendar_event_id")
    if event_id and any(k in data for k in ("scheduled_at", "type", "attendees")):
        account = await _resolve_account(brokerage, tx)
        await _sync_event_update(account, event_id, updated, tx)
    return updated


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    appointment_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    appt, tx = await _scoped_appointment(brokerage["id"], appointment_id)
    event_id = appt.get("calendar_event_id")
    if event_id:
        account = await _resolve_account(brokerage, tx)
        await calendar_provider.delete_event(account, event_id)
    await sb.delete_appointment(appointment_id)


# --------------------------------------------------------------------------- #
# Coordinate with parties — propose the booked time to outside parties. This is
# external comms, so it ALWAYS requires confirmation (no autonomy bypass), and
# the wording proposes rather than confirms the time — parties may still need to
# agree. Mirrors the deadline notify-parties pattern.
# --------------------------------------------------------------------------- #

def _format_appointment_time(appt: dict[str, Any], brokerage: dict[str, Any]) -> str:
    """Human-readable local time for the appointment, in the brokerage tz."""
    raw = appt.get("scheduled_at")
    if not raw:
        return "a time to be confirmed"
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return "a time to be confirmed"
    tz = scheduling.resolve_timezone(brokerage.get("state"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    local = dt.astimezone(tz)
    hour = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    return local.strftime("%A, %b %d, ") + f"{hour}:{local.minute:02d} {ampm} ({tz.key})"


@router.post("/{appointment_id}/notify-parties")
async def notify_parties(
    appointment_id: str,
    body: NotifyPartiesIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required before notifying parties.",
        )
    appt, tx = await _scoped_appointment(brokerage["id"], appointment_id)
    keys = _clean_parties(body.parties)
    parties = email_client.gather_parties_by_keys(tx, keys)
    if not parties:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No parties with an email on file to coordinate with.",
        )
    address = (tx.get("address") or "your transaction").strip()
    when_str = _format_appointment_time(appt, brokerage)
    subject, html, plain = email_client.build_appointment_coordination_content(
        address, appt.get("type") or "appointment", when_str, brokerage.get("name", "your brokerage")
    )
    recipients = [p["email"] for p in parties]
    sent = await asyncio.to_thread(
        email_client.send_email,
        to_emails=recipients,
        subject=subject,
        html=html,
        plain=plain,
        reply_to=email_client.reply_to_address(tx["id"]),
        disclosure=email_client.disclosure_text(brokerage),
    )
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send — email isn't configured or the send failed.",
        )
    try:
        await sb.insert_transaction_email({
            "transaction_id": tx["id"],
            "direction": "outbound",
            "sender_email": email_client.from_email(),
            "recipient_emails": recipients,
            "subject": subject,
            "body_text": plain,
            "body_html": html,
            "read": True,
        })
    except sb.SupabaseError:
        pass
    return {"sent": True, "recipients": recipients}
