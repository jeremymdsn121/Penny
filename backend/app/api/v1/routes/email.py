"""Inbound email reply threading (V2 Section 4).

SendGrid Inbound Parse delivers replies to Sloane-sent emails to POST /email/inbound.
Every outbound email Sloane sends carries Reply-To: tx-{transaction_id}@<reply domain>,
so the transaction id is recoverable from the recipient address. We store the reply
on the transaction and nudge the brokerage's WhatsApp contacts.

The thread (outbound + inbound, interleaved) is read via the per-transaction
endpoints, which require auth.
"""

import asyncio
import html
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.config import settings
from app.core import supabase_client as sb
from app.core.security import get_current_brokerage, get_current_user
from app.services import email_autoreply, email_client, twilio_client

router = APIRouter(tags=["email"])

_TX_RE = re.compile(r"tx-([0-9a-fA-F-]{8,})@")
_ADDR_RE = re.compile(r"<([^>]+)>")


def _extract_tx_id(to_field: str) -> str | None:
    m = _TX_RE.search(to_field or "")
    return m.group(1) if m else None


def _split_sender(from_field: str) -> tuple[str | None, str | None]:
    """Parse 'Jane Walsh <jane@x.com>' into (name, email)."""
    raw = (from_field or "").strip()
    addr = _ADDR_RE.search(raw)
    if addr:
        email = addr.group(1).strip()
        name = raw[: addr.start()].strip().strip('"').strip() or None
        return name, email
    return None, raw or None


def _forward_html(
    address: str, who: str, sender_email: str | None, subject: str | None,
    body_html: str | None, body_text: str,
) -> str:
    """Body for a reply forwarded to the deal's agent."""
    import html as _h

    inner = body_html or f"<p>{_h.escape(body_text).replace(chr(10), '<br/>')}</p>"
    frm = _h.escape(f"{who} <{sender_email}>" if sender_email else who)
    subj = _h.escape(subject or "(no subject)")
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#111827;">'
        '<p style="font-size:13px;color:#6B7280;">Sloane forwarded a reply on '
        f'<strong>{_h.escape(address)}</strong>. Reply to this email to continue the '
        'thread — Sloane will log your response on the transaction.</p>'
        '<hr style="border:none;border-top:1px solid #E5E7EB;margin:16px 0;"/>'
        f'<p style="font-size:13px;color:#6B7280;margin:0 0 4px;"><strong>From:</strong> {frm}</p>'
        f'<p style="font-size:13px;color:#6B7280;margin:0 0 12px;"><strong>Subject:</strong> {subj}</p>'
        f'{inner}</div>'
    )


def _forward_plain(
    address: str, who: str, sender_email: str | None, subject: str | None, body_text: str,
) -> str:
    frm = f"{who} <{sender_email}>" if sender_email else who
    return (
        f"Sloane forwarded a reply on {address}. Reply to this email to continue the "
        "thread — Sloane will log your response on the transaction.\n\n"
        f"From: {frm}\n"
        f"Subject: {subject or '(no subject)'}\n"
        f"{'-' * 40}\n"
        f"{body_text}"
    )


@router.post("/email/inbound")
async def inbound_email(request: Request) -> Any:
    """Receive a parsed inbound email from SendGrid Inbound Parse."""
    # Optional shared-secret check (Inbound Parse isn't signed by default).
    if settings.SENDGRID_WEBHOOK_KEY:
        if request.query_params.get("key") != settings.SENDGRID_WEBHOOK_KEY:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid key")

    form = await request.form()
    data = {k: str(v) for k, v in form.items()}

    transaction_id = _extract_tx_id(data.get("to", ""))
    if not transaction_id:
        # Nothing we can attribute this to — acknowledge so SendGrid stops retrying.
        return {"ok": True, "matched": False}

    tx = await sb.get_transaction_by_id(transaction_id)
    if tx is None:
        return {"ok": True, "matched": False}

    sender_name, sender_email = _split_sender(data.get("from", ""))
    subject = data.get("subject")
    body_text = data.get("text") or ""
    body_html = data.get("html")

    inbound_row = await sb.insert_transaction_email(
        {
            "transaction_id": transaction_id,
            "direction": "inbound",
            "sender_email": sender_email,
            "sender_name": sender_name,
            "recipient_emails": [data.get("to")] if data.get("to") else [],
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "read": False,
        }
    )
    inbound_id = inbound_row.get("id") if isinstance(inbound_row, dict) else None

    # Resolve the deal's agent — used to target the nudge and (optionally)
    # forward the reply to their inbox.
    brokerage = await sb.get_brokerage(tx["brokerage_id"])
    agent_id = tx.get("agent_id")
    agent: dict[str, Any] | None = None
    if agent_id:
        try:
            agent = await sb.get_agent(tx["brokerage_id"], agent_id)
        except sb.SupabaseError:
            agent = None

    preview = " ".join(body_text.split())[:120]
    who = sender_name or sender_email or "someone"
    address = tx.get("address") or "a transaction"

    # ── Optional: forward the reply to the responsible agent's inbox ───────── #
    if brokerage and brokerage.get("forward_replies_to_agent"):
        agent_email = (
            (agent or {}).get("email")
            or tx.get("listing_agent_email")
            or tx.get("selling_agent_email")
            or ""
        ).strip()
        # Don't echo the agent's own reply back to them.
        if agent_email and agent_email.lower() != (sender_email or "").strip().lower():
            try:
                await asyncio.to_thread(
                    email_client.send_email,
                    to_emails=[agent_email],
                    subject=f"Reply on {address} — {who}",
                    html=_forward_html(address, who, sender_email, subject, body_html, body_text),
                    plain=_forward_plain(address, who, sender_email, subject, body_text),
                    reply_to=email_client.reply_to_address(transaction_id),
                )
            except Exception:  # noqa: BLE001 — forwarding is best-effort
                pass

    # ── Two-way email: reply to our own agents, draft for outside parties ──── #
    # Phase 1. Internal-agent emails get a real reply (opt-in, default on);
    # outside-party emails get a queued suggested reply for the agent to approve.
    outcome = "skipped"
    try:
        outcome = await email_autoreply.maybe_autorespond(
            tx=tx,
            brokerage=brokerage or {},
            inbound_email_id=inbound_id,
            sender_name=sender_name,
            sender_email=sender_email,
            subject=subject,
            body_text=body_text,
            raw_form=data,
        )
    except Exception:  # noqa: BLE001 — never break the webhook
        outcome = "skipped"

    # When we've already replied to the agent in-thread, a WhatsApp nudge about
    # their own message would be noise — skip it.
    if outcome == "agent_replied":
        return {"ok": True, "matched": True, "action": outcome}

    # ── Targeted WhatsApp nudge: the deal's agent, not the whole brokerage ── #
    if outcome == "outside_drafted":
        nudge = (
            f"📨 Reply received on {address}\n"
            f"From: {who}\n"
            f'"{preview}"\n\n'
            "I drafted a suggested reply — review and send it in the dashboard."
        )
    else:
        nudge = (
            f"📨 Reply received on {address}\n"
            f"From: {who}\n"
            f'"{preview}"\n\n'
            "View the full message in the Sloane dashboard."
        )
    try:
        contacts = await sb.list_whatsapp_contacts(tx["brokerage_id"])
        if agent_id:
            # Only the agent on this deal. If they have no WhatsApp contact we
            # send nothing here — the reply is still in the dashboard (and
            # forwarded by email when that's enabled).
            recipients = [c for c in contacts if c.get("agent_id") == agent_id]
        else:
            # Unassigned deal — fall back to the brokerage's contacts.
            recipients = contacts
        for c in recipients:
            phone = c.get("phone_number")
            if not phone:
                continue
            try:
                await asyncio.to_thread(twilio_client.send_whatsapp_message, phone, nudge)
            except twilio_client.TwilioNotConfigured:
                break
            except Exception:  # noqa: BLE001
                pass
    except sb.SupabaseError:
        pass

    return {"ok": True, "matched": True, "action": outcome}


# --------------------------------------------------------------------------- #
# Suggested-reply queue (outside-party drafts) — protected, confirm-gated send.
# Sloane drafts a reply when an outside party emails; the agent reviews and
# sends. Sends to outside parties are NEVER automatic.
# --------------------------------------------------------------------------- #

class SendPendingReplyIn(BaseModel):
    # Allow the agent to edit before sending; fall back to the stored draft.
    subject: str | None = None
    body: str | None = None
    confirmed: bool = False


@router.get("/email/pending-replies")
async def list_pending_replies(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    """Outstanding suggested replies awaiting the agent's review."""
    return await sb.list_pending_email_replies(brokerage["id"])


@router.get("/transactions/{transaction_id}/pending-replies")
async def list_pending_replies_for_transaction(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return await sb.list_pending_email_replies_for_transaction(transaction_id)


@router.post("/email/pending-replies/{reply_id}/send")
async def send_pending_reply(
    reply_id: str,
    body: SendPendingReplyIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Send a reviewed suggested reply to the outside party. Confirm-gated."""
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required before sending.",
        )
    row = await sb.get_pending_email_reply(reply_id)
    if row is None or row.get("brokerage_id") != brokerage["id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if row.get("status") != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Already resolved."
        )
    to_email = (row.get("to_email") or "").strip()
    if not to_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No recipient on file."
        )
    subject = (body.subject if body.subject is not None else row.get("subject")) or ""
    text = (body.body if body.body is not None else row.get("draft_body")) or ""
    html_body = (
        '<html><body><div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        f'white-space:pre-wrap;color:#111827;font-size:15px;line-height:1.6;">{html.escape(text)}</div></body></html>'
    )
    sent = await asyncio.to_thread(
        email_client.send_email,
        to_emails=[to_email],
        subject=subject,
        html=html_body,
        plain=text,
        reply_to=email_client.reply_to_address(row["transaction_id"]),
        disclosure=email_client.disclosure_text(brokerage),
    )
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send — email isn't configured or the send failed.",
        )
    await sb.update_pending_email_reply(
        reply_id,
        {"status": "sent", "resolved_at": datetime.now(timezone.utc).isoformat(), "resolved_by": user.get("id")},
    )
    try:
        await sb.insert_transaction_email(
            {
                "transaction_id": row["transaction_id"],
                "direction": "outbound",
                "sender_email": email_client.from_email(),
                "recipient_emails": [to_email],
                "subject": subject,
                "body_text": text,
                "body_html": html_body,
                "read": True,
            }
        )
    except sb.SupabaseError:
        pass
    return {"sent": True, "recipient": to_email}


@router.post("/email/pending-replies/{reply_id}/dismiss")
async def dismiss_pending_reply(
    reply_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Discard a suggested reply without sending it."""
    row = await sb.get_pending_email_reply(reply_id)
    if row is None or row.get("brokerage_id") != brokerage["id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await sb.update_pending_email_reply(
        reply_id,
        {"status": "dismissed", "resolved_at": datetime.now(timezone.utc).isoformat(), "resolved_by": user.get("id")},
    )
    return {"ok": True}


@router.get("/transactions/{transaction_id}/emails")
async def list_emails(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return await sb.list_transaction_emails(transaction_id)


@router.post("/transactions/{transaction_id}/emails/read")
async def mark_read(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    await sb.mark_transaction_emails_read(transaction_id, user.get("id"))
    return {"ok": True}
