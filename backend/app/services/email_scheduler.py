"""Fire deferred/scheduled replies (two-way email, Phase 2).

A scheduled job hits POST /email/run-scheduled-replies (same idempotent-scan
pattern as deadline reminders — no in-process scheduler). For each brokerage's
armed/held suggested replies:

- 'scheduled' (time trigger): once scheduled_send_at has passed, RE-SURFACE for
  the agent's final confirm (status → 'pending', briefed by email). Never
  auto-sent — Penny never sends to an outside party without a fresh human tap.
- 'awaiting_event' (event trigger): when the event becomes true on the deal,
  RE-SURFACE for the agent's final confirm (status → 'pending', briefed by
  email). Never auto-sent — the deal may have changed.
- 'held' (manual): periodically REMIND the agent it's waiting. Never auto-sent.

Best-effort throughout; one bad row never blocks the rest.
"""

import asyncio
import html as _html
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core import supabase_client as sb
from app.services import email_client

# How long a free-form held reply waits between agent reminders.
_HOLD_REMINDER_EVERY = timedelta(days=3)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _event_met(tx: dict[str, Any], event: str) -> bool:
    e = (event or "").strip()
    if e.startswith("stage:"):
        return (tx.get("stage") or "") == e.split(":", 1)[1]
    if e == "emd_received":
        return bool(tx.get("emd_received"))
    if e.startswith("checklist:"):
        label = e.split(":", 1)[1].strip().lower()
        if not label:
            return False
        try:
            items = await sb.list_checklist_items(tx["id"])
        except sb.SupabaseError:
            return False
        return any(
            label in (i.get("label") or "").lower() and i.get("status") == "complete"
            for i in items
        )
    return False


def _event_label(event: str) -> str:
    e = (event or "").strip()
    if e.startswith("stage:"):
        return f"the deal moved to {e.split(':', 1)[1].replace('_', ' ')}"
    if e == "emd_received":
        return "the EMD was marked received"
    if e.startswith("checklist:"):
        return f"\"{e.split(':', 1)[1]}\" was checked off"
    return e


def _html_body(text: str) -> str:
    return (
        '<html><body><div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        "white-space:pre-wrap;color:#111827;font-size:15px;line-height:1.6;\">"
        f"{_html.escape(text)}</div></body></html>"
    )


async def _agent_email(tx: dict[str, Any]) -> str:
    agent_id = tx.get("agent_id")
    email = ""
    if agent_id:
        try:
            agent = await sb.get_agent(tx["brokerage_id"], agent_id)
            email = ((agent or {}).get("email") or "").strip()
        except sb.SupabaseError:
            email = ""
    return email or (tx.get("listing_agent_email") or tx.get("selling_agent_email") or "").strip()


async def _notify_agent(tx: dict[str, Any], subject: str, body: str) -> None:
    """Email the deal's agent; fall back to a WhatsApp nudge."""
    email = await _agent_email(tx)
    if email:
        try:
            ok = await asyncio.to_thread(
                email_client.send_email,
                to_emails=[email],
                subject=subject,
                html=_html_body(body),
                plain=body,
                reply_to=email_client.reply_to_address(tx["id"]),
            )
            if ok:
                return
        except Exception:  # noqa: BLE001
            pass
    try:
        from app.services import twilio_client

        contacts = await sb.list_whatsapp_contacts(tx["brokerage_id"])
        agent_id = tx.get("agent_id")
        recipients = (
            [c for c in contacts if c.get("agent_id") == agent_id] if agent_id else contacts
        )
        for c in recipients:
            phone = c.get("phone_number")
            if not phone:
                continue
            try:
                await asyncio.to_thread(twilio_client.send_whatsapp_message, phone, body)
            except twilio_client.TwilioNotConfigured:
                break
            except Exception:  # noqa: BLE001
                pass
    except sb.SupabaseError:
        pass


def _resurface_brief(who: str, address: str, lead: str, draft_body: str) -> str:
    """The body Penny emails the agent when a deferred reply comes due."""
    return (
        f"{lead} You asked me to hold a reply to {who} on {address}. Want me to "
        "send it now? Reply \"send it\" to go ahead (or tell me to change it or "
        f"keep waiting).\n\nDraft:\n{draft_body}"
    )


async def run_for_brokerage(brokerage_id: str) -> dict[str, int]:
    """Process armed/held suggested replies for one brokerage. Idempotent.

    Nothing is sent here — due time triggers and met event triggers both
    re-surface for the agent's final confirm. The actual send only ever happens
    when the agent approves (approve_and_send_reply in the agent loop).
    """
    counts = {"resurfaced": 0, "reminded": 0}
    try:
        rows = await sb.list_email_replies_by_statuses(
            brokerage_id, ["scheduled", "awaiting_event", "held"]
        )
    except sb.SupabaseError:
        return counts
    if not rows:
        return counts

    now = _now()
    # Cache transactions across rows on the same deal.
    tx_cache: dict[str, dict[str, Any] | None] = {}

    async def _tx(tx_id: str) -> dict[str, Any] | None:
        if tx_id not in tx_cache:
            try:
                tx_cache[tx_id] = await sb.get_transaction_by_id(tx_id)
            except sb.SupabaseError:
                tx_cache[tx_id] = None
        return tx_cache[tx_id]

    for row in rows:
        status = row.get("status")
        tx = await _tx(row.get("transaction_id"))
        if tx is None:
            continue
        who = row.get("to_name") or row.get("to_email") or "the other party"
        address = tx.get("address") or "a transaction"

        draft_body = (row.get("draft_body") or "").strip()

        if status == "scheduled":
            when = _parse_dt(row.get("scheduled_send_at"))
            if when and when <= now:
                # The time the agent set has arrived — re-surface for a final
                # confirm. Never auto-sent.
                await sb.update_pending_email_reply(
                    row["id"], {"status": "pending", "trigger_type": "none"}
                )
                counts["resurfaced"] += 1
                await _notify_agent(
                    tx,
                    f"Ready to send on {address}?",
                    _resurface_brief(
                        who, address, "The time you set to reply has arrived.", draft_body
                    ),
                )

        elif status == "awaiting_event":
            if await _event_met(tx, row.get("trigger_event") or ""):
                # The event happened — re-surface for a final confirm. Never auto-sent.
                await sb.update_pending_email_reply(
                    row["id"], {"status": "pending", "trigger_type": "none"}
                )
                counts["resurfaced"] += 1
                label = _event_label(row.get("trigger_event") or "")
                await _notify_agent(
                    tx,
                    f"Ready to send on {address}? — {label}",
                    _resurface_brief(who, address, f"{label.capitalize()}.", draft_body),
                )

        elif status == "held":
            last = _parse_dt(row.get("last_reminder_at"))
            if last is None or (now - last) >= _HOLD_REMINDER_EVERY:
                await sb.update_pending_email_reply(
                    row["id"], {"last_reminder_at": now.isoformat()}
                )
                counts["reminded"] += 1
                note = (row.get("hold_note") or "").strip()
                await _notify_agent(
                    tx,
                    f"Still holding a reply to {who} on {address}",
                    (
                        f"Reminder: I'm holding a reply to {who} on {address}"
                        + (f" ({note})" if note else "")
                        + ". Reply \"send it\" when you're ready, or tell me to drop it."
                    ),
                )

    return counts
