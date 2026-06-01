"""Deadline reminders (PRD task ``deadline-reminders``).

Two halves:
  * **Marks logic** (pure, testable): given a deadline row and today's date,
    decide which of the 5-day / 2-day / day-of marks should fire and which
    ``reminder_*_sent`` flags to flip. Idempotent — a mark fires at most once.
  * **Orchestration**: ``run_reminders`` scans a brokerage's deadlines and, for
    each due mark, sends the agent a WhatsApp nudge (internal, always sent) and
    — only when ``deadline-reminders`` is autonomous for the brokerage — emails
    the responsible parties. When it isn't autonomous, party emails are NOT sent
    automatically; the agent is told to confirm via the dashboard (the hard rule
    that external sends require confirmation still holds).

This module is invoked by an idempotent scan endpoint (POST /deadlines/run-
reminders), which a scheduled job can call. There is no in-process scheduler.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.core import supabase_client as sb
from app.services import email_client, twilio_client, workflow

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Mark:
    key: str
    threshold_days: int  # fires once days-until-due falls to/under this
    flag: str            # the deadline column tracking that it has fired


# Most-urgent first. day-of (<= 0), then 2-day (<= 2), then 5-day (<= 5).
MARKS: list[Mark] = [
    Mark("day", 0, "reminder_day_sent"),
    Mark("2day", 2, "reminder_2day_sent"),
    Mark("5day", 5, "reminder_5day_sent"),
]


def _parse_due(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def due_marks(
    deadline: dict[str, Any], today: date
) -> tuple[Mark | None, dict[str, bool]]:
    """Decide which mark to message and which flags to flip.

    Returns ``(fire, flags_to_set)``. ``fire`` is the most-urgent crossed mark
    that hasn't been sent yet (or None if nothing is due). ``flags_to_set``
    marks *every* crossed threshold as sent, so a deadline created close to its
    due date doesn't fire 5-day then 2-day on consecutive scans — the passed
    marks are consumed silently and only the most urgent one is messaged.
    """
    due = _parse_due(deadline.get("due_date"))
    if due is None:
        return None, {}
    days_until = (due - today).days

    crossed = [m for m in MARKS if days_until <= m.threshold_days]
    if not crossed:
        return None, {}

    flags_to_set = {m.flag: True for m in crossed}
    # MARKS is ordered most-urgent-first, so the first unsent crossed mark is
    # the one to actually message.
    fire = next((m for m in crossed if not deadline.get(m.flag)), None)
    if fire is None:
        return None, {}
    return fire, flags_to_set


# --------------------------------------------------------------------------- #
# Content
# --------------------------------------------------------------------------- #

def describe_timing(days_until: int) -> str:
    if days_until > 1:
        return f"is due in {days_until} days"
    if days_until == 1:
        return "is due tomorrow"
    if days_until == 0:
        return "is due today"
    overdue = abs(days_until)
    return f"was due {overdue} day{'s' if overdue != 1 else ''} ago"


def build_agent_nudge(
    tx: dict[str, Any],
    deadline: dict[str, Any],
    days_until: int,
    parties: list[dict[str, str]],
    party_action: str,
) -> str:
    """Plain-text WhatsApp nudge to the agent. ``party_action`` is one of
    'sent' | 'pending_confirm' | 'none'."""
    label = (deadline.get("label") or "A deadline").strip()
    address = (tx.get("address") or "a transaction").strip()
    timing = describe_timing(days_until)
    lines = [f"⏰ Reminder: {label} for {address} {timing}."]
    if parties:
        who = ", ".join(p["name"] for p in parties)
        if party_action == "sent":
            lines.append(f"I've emailed the responsible parties ({who}).")
        elif party_action == "pending_confirm":
            lines.append(
                f"Want me to notify the responsible parties ({who})? "
                "Confirm from the dashboard and I'll send it."
            )
    return " ".join(lines)


def build_party_notice(
    tx: dict[str, Any], deadline: dict[str, Any], brokerage_name: str
) -> tuple[str, str, str]:
    """Build ``(subject, html, plain)`` for the responsible-party notice."""
    label = (deadline.get("label") or "an upcoming deadline").strip()
    address = (tx.get("address") or "your transaction").strip()
    due = _parse_due(deadline.get("due_date"))
    due_str = due.strftime("%B %d, %Y") if due else "soon"
    subject = f"Upcoming deadline: {label} — {address}"

    violet, dark, muted, bg, white = "#7C3AED", "#111827", "#6B7280", "#F9FAFB", "#FFFFFF"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /></head>
<body style="margin:0;padding:0;background:{bg};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{bg};padding:40px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:{white};border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08);">
        <tr><td style="background:{violet};padding:28px 40px;text-align:center;">
          <p style="margin:0;color:{white};font-size:24px;font-weight:700;letter-spacing:-0.5px;">Sloane</p>
          <p style="margin:6px 0 0;color:rgba(255,255,255,.85);font-size:13px;font-weight:500;">Transaction Coordinator · {brokerage_name}</p>
        </td></tr>
        <tr><td style="padding:36px 40px 32px;">
          <h1 style="margin:0 0 16px;font-size:20px;font-weight:700;color:{dark};">Upcoming deadline</h1>
          <p style="margin:0 0 16px;font-size:15px;color:{dark};line-height:1.6;">
            A quick heads-up that <strong>{label}</strong> for the transaction at
            <strong>{address}</strong> is due on <strong>{due_str}</strong>.
          </p>
          <p style="margin:0;font-size:14px;color:{muted};line-height:1.6;">
            Please reach out if you have any questions or need anything ahead of this date.
          </p>
        </td></tr>
        <tr><td style="background:{bg};padding:18px 40px;border-top:1px solid #E5E7EB;text-align:center;">
          <p style="margin:0;font-size:12px;color:{muted};">Sent by Sloane on behalf of {brokerage_name}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
    plain = (
        f"Upcoming deadline — {address}\n"
        f"{'=' * 40}\n\n"
        f"A quick heads-up that {label} for the transaction at {address} is due on "
        f"{due_str}.\n\n"
        "Please reach out if you have any questions or need anything ahead of this date.\n\n"
        f"—\nSent by Sloane on behalf of {brokerage_name}"
    )
    return subject, html, plain


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

async def _is_autonomous(brokerage_id: str) -> bool:
    try:
        autonomy = await sb.get_task_autonomy(brokerage_id)
    except Exception:
        return False
    return any(
        r.get("task_id") == "deadline-reminders" and r.get("autonomous")
        for r in autonomy
    )


async def _send_nudge(contacts: list[dict[str, Any]], text: str) -> bool:
    """Best-effort WhatsApp nudge to every registered contact. Returns True if
    at least one send was attempted without Twilio being unconfigured."""
    if not contacts:
        return False
    sent_any = False
    for c in contacts:
        phone = c.get("phone_number")
        if not phone:
            continue
        try:
            await asyncio.to_thread(twilio_client.send_whatsapp_message, phone, text)
            sent_any = True
        except twilio_client.TwilioNotConfigured:
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Deadline nudge to %s failed: %s", phone, exc)
    return sent_any


async def run_reminders(brokerage_id: str) -> dict[str, Any]:
    """Scan one brokerage's deadlines and fire any due reminders.

    Idempotent: each mark flips its ``reminder_*_sent`` flag so it won't repeat.
    Agent nudges always go out (internal); party emails only when the
    ``deadline-reminders`` task is autonomous for the brokerage.
    """
    txs = await sb.list_transactions(brokerage_id)
    tx_by_id = {t["id"]: t for t in txs}
    if not tx_by_id:
        return {"processed": 0, "items": []}

    deadlines = await sb.list_deadlines_in(list(tx_by_id.keys()))
    autonomous = await _is_autonomous(brokerage_id)
    contacts = await sb.list_whatsapp_contacts(brokerage_id)
    brokerage = await sb.get_brokerage(brokerage_id)
    brokerage_name = (brokerage or {}).get("name", "the brokerage")
    today = date.today()

    items: list[dict[str, Any]] = []
    for deadline in deadlines:
        tx = tx_by_id.get(deadline.get("transaction_id"))
        if tx is None:
            continue
        fire, flags = due_marks(deadline, today)
        if fire is None:
            continue

        due = _parse_due(deadline.get("due_date"))
        days_until = (due - today).days if due else 0

        # Generate any workflow tasks tied to this deadline at this mark
        # (e.g. "Confirm inspection is scheduled" 5 days before inspection).
        if fire.threshold_days > 0:
            try:
                await workflow.generate_deadline_tasks(
                    tx,
                    deadline.get("label") or "",
                    fire.threshold_days,
                    deadline.get("due_date"),
                )
            except Exception:  # noqa: BLE001 — task gen is best-effort
                pass

        keys = deadline.get("responsible_parties") or []
        parties = email_client.gather_parties_by_keys(tx, keys)

        if not parties:
            party_action = "none"
        elif autonomous:
            party_action = "sent"
        else:
            party_action = "pending_confirm"

        nudge = build_agent_nudge(tx, deadline, days_until, parties, party_action)
        nudged = await _send_nudge(contacts, nudge)

        emailed: list[str] = []
        if party_action == "sent":
            subject, html, plain = build_party_notice(tx, deadline, brokerage_name)
            ok = await asyncio.to_thread(
                email_client.send_email,
                to_emails=[p["email"] for p in parties],
                subject=subject,
                html=html,
                plain=plain,
                reply_to=email_client.reply_to_address(tx["id"]),
                disclosure=email_client.disclosure_text(brokerage),
            )
            if ok:
                emailed = [p["email"] for p in parties]
                try:
                    await sb.insert_transaction_email({
                        "transaction_id": tx["id"],
                        "direction": "outbound",
                        "sender_email": email_client.from_email(),
                        "recipient_emails": emailed,
                        "subject": subject,
                        "body_text": plain,
                        "body_html": html,
                        "read": True,
                    })
                except Exception:  # noqa: BLE001
                    pass

        # Flip the crossed flags so this mark (and any passed ones) won't repeat.
        await sb.update_deadline(deadline["id"], flags)

        items.append({
            "deadline_id": deadline["id"],
            "label": deadline.get("label"),
            "address": tx.get("address"),
            "mark": fire.key,
            "days_until": days_until,
            "nudged": nudged,
            "party_action": party_action,
            "parties_emailed": emailed,
        })

    return {"processed": len(items), "items": items}
