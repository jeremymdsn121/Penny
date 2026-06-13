"""Recurring status updates (Autonomy task ``status-updates``).

A transaction coordinator's most routine job is the regular status update: a
short "here's where we stand" to the parties on a deal, summarizing what's
done, what's coming up, and what's still outstanding. Penny sends these on a
weekly cadence from an idempotent scan, the same shape as the deadline-reminder
and scheduled-reply scans.

Two halves:
  * **Content + cadence** (pure, testable): build the digest from a deal's
    deadlines / tasks / checklist, and decide whether a deal is due for one.
  * **Orchestration** (``run_status_updates``): for each active deal that's due,
    either send to the parties immediately — only when the ``status-updates``
    task is autonomous for the brokerage — or queue a ``pending_status_updates``
    row and WhatsApp-nudge the deal's agent to approve the send (confirm-gated
    default). Sending to the parties is external comms, so the autonomy toggle is
    the only thing that lets it run without a human; otherwise it waits for a
    one-click confirm.

``transactions.last_status_update_at`` is both the cadence anchor and the
idempotency claim — it's stamped when a deal is handled so a re-run can't repeat.
"""

import asyncio
import html as _html
import logging
from datetime import date, datetime, timezone
from typing import Any

from app.core import supabase_client as sb
from app.services import email_client, twilio_client

logger = logging.getLogger(__name__)

CADENCE_DAYS = 7
ACTIVE_STAGES = ("under_contract", "pending")

_STAGE_LABELS = {
    "under_contract": "under contract",
    "pending": "pending (clear to close)",
    "closed": "closed",
    "cancelled": "cancelled",
}


# --------------------------------------------------------------------------- #
# Cadence
# --------------------------------------------------------------------------- #

def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def status_update_due(
    tx: dict[str, Any], today: date, cadence_days: int = CADENCE_DAYS
) -> bool:
    """Whether ``tx`` is due for a status update as of ``today``.

    A deal that has never had one is due immediately; otherwise it's due once
    the cadence has elapsed since the last update. (Stage filtering is the
    caller's job — the scan only considers active deals.)
    """
    last = _parse_date(tx.get("last_status_update_at"))
    if last is None:
        return True
    return (today - last).days >= cadence_days


# --------------------------------------------------------------------------- #
# Content (deterministic — no LLM, so it degrades cleanly and is testable)
# --------------------------------------------------------------------------- #

def _stage_label(tx: dict[str, Any]) -> str:
    stage = (tx.get("stage") or "under_contract").strip().lower()
    return _STAGE_LABELS.get(stage, stage.replace("_", " "))


def _closing_line(tx: dict[str, Any], today: date) -> str | None:
    closing = _parse_date(tx.get("closing_date"))
    if closing is None:
        return None
    days = (closing - today).days
    when = closing.strftime("%B %d, %Y")
    if days > 1:
        return f"On track to close on {when} ({days} days away)."
    if days == 1:
        return f"Closing is tomorrow, {when}."
    if days == 0:
        return f"Closing is today, {when}."
    return f"Closing was scheduled for {when}."


def build_status_update_content(
    tx: dict[str, Any],
    deadlines: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    checklist_items: list[dict[str, Any]],
    brokerage_name: str,
    today: date | None = None,
) -> tuple[str, str, str]:
    """Build ``(subject, html, plain)`` for a status update.

    Plain, human-typed style — no branded header/card/footer — so parties read
    it as a real note from a coordinator. Sections are omitted when empty.
    """
    today = today or date.today()
    address = (tx.get("address") or "your transaction").strip()
    subject = f"Status update — {address}"

    # Where we stand.
    standing = f"The deal is currently {_stage_label(tx)}."
    closing = _closing_line(tx, today)

    # Coming up (next 14 days): unresolved deadlines + dated pending tasks.
    upcoming: list[str] = []
    for dl in deadlines:
        if dl.get("resolved"):
            continue
        due = _parse_date(dl.get("due_date"))
        if due is None or not (0 <= (due - today).days <= 14):
            continue
        upcoming.append(f"{(dl.get('label') or 'A deadline').strip()} — due {due.strftime('%b %d')}")
    for t in tasks:
        if t.get("status") != "pending":
            continue
        due = _parse_date(t.get("due_date"))
        if due is None or not (0 <= (due - today).days <= 14):
            continue
        upcoming.append(f"{(t.get('label') or 'A task').strip()} — by {due.strftime('%b %d')}")

    # Still outstanding: missing required checklist items + EMD not yet received.
    outstanding: list[str] = []
    for it in checklist_items:
        if it.get("required") and it.get("status") not in ("complete", "waived", "not_applicable"):
            outstanding.append((it.get("label") or "A required document").strip())
    emd_due = _parse_date(tx.get("emd_due_date"))
    if tx.get("emd_amount") and not tx.get("emd_received"):
        if emd_due:
            outstanding.append(f"Earnest money receipt (due {emd_due.strftime('%b %d')})")
        else:
            outstanding.append("Earnest money receipt")

    # ---- plain ----
    lines = ["Hi everyone,", "", f"Here's a quick status update on {address}.", "", standing]
    if closing:
        lines.append(closing)
    if upcoming:
        lines += ["", "Coming up:"] + [f"  - {u}" for u in upcoming]
    if outstanding:
        lines += ["", "Still outstanding:"] + [f"  - {o}" for o in outstanding]
    if not upcoming and not outstanding:
        lines += ["", "Nothing outstanding on my end right now. I'll flag anything as it comes up."]
    lines += [
        "",
        "Reply all with any questions and I'll keep this thread updated.",
        "",
        "Thanks,",
        "Penny",
        f"Transaction Coordinator, {brokerage_name}",
    ]
    plain = "\n".join(lines)

    # ---- html (escape extracted/user values) ----
    esc = _html.escape
    parts = [
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;line-height:1.5;">',
        "<p>Hi everyone,</p>",
        f"<p>Here's a quick status update on {esc(address)}.</p>",
        f"<p>{esc(standing)}" + (f"<br>{esc(closing)}" if closing else "") + "</p>",
    ]
    if upcoming:
        parts.append("<p>Coming up:</p><ul>" + "".join(f"<li>{esc(u)}</li>" for u in upcoming) + "</ul>")
    if outstanding:
        parts.append("<p>Still outstanding:</p><ul>" + "".join(f"<li>{esc(o)}</li>" for o in outstanding) + "</ul>")
    if not upcoming and not outstanding:
        parts.append("<p>Nothing outstanding on my end right now. I'll flag anything as it comes up.</p>")
    parts.append("<p>Reply all with any questions and I'll keep this thread updated.</p>")
    parts.append(f"<p>Thanks,<br>Penny<br>Transaction Coordinator, {esc(brokerage_name)}</p></div>")
    html = "".join(parts)

    return subject, html, plain


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

async def _is_autonomous(brokerage_id: str) -> bool:
    try:
        autonomy = await sb.get_task_autonomy(brokerage_id)
    except Exception:  # noqa: BLE001
        return False
    return any(
        r.get("task_id") == "status-updates" and r.get("autonomous") for r in autonomy
    )


async def _gather_deal_context(
    tx: dict[str, Any], brokerage_name: str, today: date
) -> tuple[str, str, str, list[str]]:
    """Build content + recipient emails for one deal. Best-effort on each fetch."""
    tx_id = tx["id"]
    try:
        deadlines = await sb.list_deadlines_in([tx_id])
    except Exception:  # noqa: BLE001
        deadlines = []
    try:
        tasks = await sb.list_transaction_tasks(tx_id)
    except Exception:  # noqa: BLE001
        tasks = []
    try:
        checklist = await sb.list_checklist_items(tx_id)
    except Exception:  # noqa: BLE001
        checklist = []
    subject, html, plain = build_status_update_content(
        tx, deadlines, tasks, checklist, brokerage_name, today
    )
    emails = [p["email"] for p in email_client.gather_intro_parties(tx)]
    return subject, html, plain, emails


async def compose_status_update(
    tx: dict[str, Any], brokerage_name: str, today: date | None = None
) -> tuple[str, str, str, list[str]]:
    """Public composer: build (subject, html, plain, recipient_emails) for a deal.

    Used by the agent tool to preview/send a status update on request, sharing
    the same content the recurring scan produces.
    """
    return await _gather_deal_context(tx, brokerage_name, today or date.today())


async def _nudge_agent(tx: dict[str, Any], contacts: list[dict[str, Any]]) -> None:
    """WhatsApp the deal's agent that a status update is waiting for approval."""
    address = tx.get("address") or "a transaction"
    msg = (
        f"📋 Status update ready for {address}.\n"
        "Review and send it to the parties from the Penny dashboard (Communications)."
    )
    agent_id = tx.get("agent_id")
    recipients = (
        [c for c in contacts if c.get("agent_id") == agent_id] if agent_id else contacts
    )
    for c in recipients:
        phone = c.get("phone_number")
        if not phone:
            continue
        try:
            await asyncio.to_thread(
                twilio_client.send_whatsapp_template,
                phone, "agent_action_needed", [address, "status update"], msg,
            )
        except twilio_client.TwilioNotConfigured:
            break
        except Exception:  # noqa: BLE001 — nudges are best-effort
            pass


async def log_and_record(
    tx: dict[str, Any], subject: str, plain: str, html: str, emails: list[str]
) -> None:
    try:
        await sb.insert_transaction_email({
            "transaction_id": tx["id"],
            "direction": "outbound",
            "sender_email": email_client.from_email(),
            "recipient_emails": emails,
            "subject": subject,
            "body_text": plain,
            "body_html": html,
            "read": True,
        })
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services import activity

        await activity.record(
            brokerage_id=tx["brokerage_id"],
            transaction_id=tx["id"],
            kind="status_update_sent",
            title="Status update sent",
            detail="to " + ", ".join(emails),
            actor="Penny",
            via="system",
        )
    except Exception:  # noqa: BLE001
        pass


async def run_status_updates(brokerage_id: str) -> dict[str, Any]:
    """Scan one brokerage's active deals and send/queue any due status updates.

    Idempotent: ``last_status_update_at`` is claimed before the side effect, so
    overlapping or repeated runs can't double-send. Sends to parties only when
    ``status-updates`` is autonomous; otherwise the update is queued for the
    deal's agent to confirm.
    """
    txs = await sb.list_transactions(brokerage_id)
    active = [t for t in txs if (t.get("stage") or "under_contract") in ACTIVE_STAGES]
    if not active:
        return {"processed": 0, "items": []}

    today = date.today()
    due = [t for t in active if status_update_due(t, today)]
    if not due:
        return {"processed": 0, "items": []}

    autonomous = await _is_autonomous(brokerage_id)
    brokerage = await sb.get_brokerage(brokerage_id)
    brokerage_name = (brokerage or {}).get("name", "the brokerage")
    contacts = await sb.list_whatsapp_contacts(brokerage_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    items: list[dict[str, Any]] = []
    for tx in due:
        subject, html, plain, emails = await _gather_deal_context(tx, brokerage_name, today)
        if not emails:
            # No one to update — don't claim the cycle, so it fires once a party
            # email is added.
            continue

        if autonomous:
            # Claim BEFORE sending so a crash can't re-send to outside parties.
            try:
                await sb.update_transaction(brokerage_id, tx["id"], {"last_status_update_at": now_iso})
            except sb.SupabaseError as exc:
                logger.error("Could not claim status-update cycle for %s: %s", tx["id"], exc)
                continue
            sent = await asyncio.to_thread(
                email_client.send_email,
                to_emails=emails,
                subject=subject,
                html=html,
                plain=plain,
                reply_to=email_client.reply_to_address(tx["id"]),
                disclosure=email_client.disclosure_text(brokerage),
            )
            if sent:
                await log_and_record(tx, subject, plain, html, emails)
                try:
                    await sb.insert_pending_status_update({
                        "brokerage_id": brokerage_id,
                        "transaction_id": tx["id"],
                        "subject": subject,
                        "body_text": plain,
                        "body_html": html,
                        "recipient_emails": emails,
                        "status": "sent",
                        "resolved_at": now_iso,
                    })
                except Exception:  # noqa: BLE001
                    pass
            items.append({"transaction_id": tx["id"], "address": tx.get("address"),
                          "action": "sent" if sent else "send_failed", "recipients": emails})
        else:
            # Queue for confirm. Insert first (unique index = idempotency guard);
            # only claim the cadence if we actually queued one.
            row = await sb.insert_pending_status_update({
                "brokerage_id": brokerage_id,
                "transaction_id": tx["id"],
                "subject": subject,
                "body_text": plain,
                "body_html": html,
                "recipient_emails": emails,
                "status": "pending",
            })
            if row is None:
                continue  # an open status update already waits — don't re-nudge
            try:
                await sb.update_transaction(brokerage_id, tx["id"], {"last_status_update_at": now_iso})
            except sb.SupabaseError:
                pass
            await _nudge_agent(tx, contacts)
            items.append({"transaction_id": tx["id"], "address": tx.get("address"),
                          "action": "queued", "recipients": emails})

    return {"processed": len(items), "items": items}


async def send_pending_status_update(
    row: dict[str, Any], tx: dict[str, Any], brokerage: dict[str, Any] | None
) -> tuple[bool, str | None]:
    """Send a queued status update after human confirmation. Returns (sent, reason)."""
    emails = row.get("recipient_emails") or [
        p["email"] for p in email_client.gather_intro_parties(tx)
    ]
    if not emails:
        return False, "no recipient email addresses on file for this deal"
    sent = await asyncio.to_thread(
        email_client.send_email,
        to_emails=emails,
        subject=row.get("subject") or f"Status update — {tx.get('address')}",
        html=row.get("body_html") or f"<p>{_html.escape(row.get('body_text') or '')}</p>",
        plain=row.get("body_text") or "",
        reply_to=email_client.reply_to_address(tx.get("id")),
        disclosure=email_client.disclosure_text(brokerage),
    )
    if sent:
        await log_and_record(
            tx, row.get("subject") or "Status update",
            row.get("body_text") or "", row.get("body_html") or "", emails,
        )
    return (sent, None if sent else "SendGrid not configured or the send failed")
