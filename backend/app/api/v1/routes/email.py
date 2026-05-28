"""Inbound email reply threading (V2 Section 4).

SendGrid Inbound Parse delivers replies to Penny-sent emails to POST /email/inbound.
Every outbound email Penny sends carries Reply-To: tx-{transaction_id}@<reply domain>,
so the transaction id is recoverable from the recipient address. We store the reply
on the transaction and nudge the brokerage's WhatsApp contacts.

The thread (outbound + inbound, interleaved) is read via the per-transaction
endpoints, which require auth.
"""

import asyncio
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import settings
from app.core import supabase_client as sb
from app.core.security import get_current_brokerage, get_current_user
from app.services import twilio_client

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

    await sb.insert_transaction_email(
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

    # Nudge the brokerage's WhatsApp contacts with a short preview.
    preview = " ".join(body_text.split())[:120]
    who = sender_name or sender_email or "someone"
    address = tx.get("address") or "a transaction"
    nudge = (
        f"📨 Reply received on {address}\n"
        f"From: {who}\n"
        f'"{preview}"\n\n'
        "View the full message in the Penny dashboard."
    )
    try:
        contacts = await sb.list_whatsapp_contacts(tx["brokerage_id"])
        for c in contacts:
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

    return {"ok": True, "matched": True}


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
