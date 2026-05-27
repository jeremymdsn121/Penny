"""WhatsApp inbound webhook + contact management endpoints.

Twilio calls POST /whatsapp/inbound for every message received on the configured
WhatsApp number. We validate the Twilio signature, look up the sender, transcribe
any voice memo, run the Penny agent, and reply via Twilio.

Contact management (register/list/delete realtor phone numbers) is done by the
brokerage admin from the frontend and requires a valid JWT.
"""

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.config import settings
from app.services import penny_agent
from app.services.twilio_client import (
    TwilioNotConfigured,
    send_whatsapp_message,
    validate_twilio_signature,
)
from app.services.whisper import TranscriptionError, transcribe_twilio_audio

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _strip_scheme(number: str) -> str:
    """Remove 'whatsapp:' prefix and return the bare E.164 number."""
    return number.removeprefix("whatsapp:")


def _normalise_phone(raw: str) -> str:
    """Normalise a phone number to E.164 format ('+1XXXXXXXXXX').

    The product is US-focused, so US/NANP heuristics take priority: a 10-digit
    number — with or without a stray leading "+" — is treated as a US number
    missing its country code. This means a user can type the number however
    feels natural and it lands in the same canonical form Twilio sends.

      "4054139444"        -> "+14054139444"  (10 digits, assume US, add +1)
      "+4054139444"       -> "+14054139444"  (10 digits + stray "+", still US)
      "(405) 413-9444"    -> "+14054139444"  (formatting stripped)
      "14054139444"       -> "+14054139444"  (11 digits w/ country code)
      "+14054139444"      -> "+14054139444"  (already E.164)
    Anything that isn't a 10- or 11-digit US number is treated as an
    international E.164 number and preserved as-is (after stripping formatting),
    so non-US numbers aren't mangled — e.g. "+447911123456" -> "+447911123456".
    """
    digits = re.sub(r"\D", "", _strip_scheme(raw))  # keep digits only

    # US/NANP first: a 10-digit number (even one typed with a stray "+") is
    # almost certainly a US number missing its "+1" country code.
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits

    # Otherwise trust it as an international number (or let the caller's
    # validation catch genuinely malformed input).
    return "+" + digits


# --------------------------------------------------------------------------- #
# Twilio inbound webhook
# --------------------------------------------------------------------------- #

@router.post("/inbound")
async def inbound(request: Request) -> Any:
    """Receive an inbound WhatsApp message from Twilio.

    Twilio expects a 200 response quickly, so we keep the path lean.
    Heavy work (Whisper, Claude) happens synchronously here because FastAPI /
    uvicorn is async — no background task infrastructure needed.

    Returns an empty 200 (we reply via the Twilio REST API rather than TwiML
    so we control the send timing after the AI finishes).

    We read the form body exactly once and pull every field from it — mixing
    Form(...) params with a manual request.form() call double-reads the body
    and can intermittently come up empty.
    """
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items()}

    # Validate Twilio signature to reject spoofed requests.
    if not settings.TWILIO_SKIP_VALIDATION:
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        if not validate_twilio_signature(url, form_data, signature):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Twilio signature",
            )

    From = form_data.get("From", "")
    Body = form_data.get("Body", "")
    NumMedia = form_data.get("NumMedia", "0")
    MediaUrl0 = form_data.get("MediaUrl0", "")
    MediaContentType0 = form_data.get("MediaContentType0", "")

    # No From field means this is a status callback (delivery receipt) or other
    # non-message event rather than an inbound message — acknowledge and stop.
    if not From:
        return {}

    phone_number = _normalise_phone(From)
    num_media = int(NumMedia or "0")
    has_audio = num_media > 0 and "audio" in (MediaContentType0 or "")

    # ── Look up which brokerage this phone number belongs to ──────────────── #
    contact = await sb.lookup_whatsapp_contact(phone_number)
    if contact is None:
        # Unrecognised number — send a polite rejection and stop.
        try:
            send_whatsapp_message(
                phone_number,
                "Hi! I don't recognise this number. Please ask your broker to "
                "register your WhatsApp number in Penny first.",
            )
        except TwilioNotConfigured:
            pass
        return {}

    brokerage_id: str = contact["brokerage_id"]
    display_name: str | None = contact.get("display_name")

    # ── Resolve the message text ───────────────────────────────────────────── #
    content_type = "text"
    message_body = Body.strip()

    if has_audio and MediaUrl0:
        content_type = "audio"
        try:
            message_body = await transcribe_twilio_audio(MediaUrl0)
        except TranscriptionError as exc:
            send_whatsapp_message(
                phone_number,
                f"I received your voice message but couldn't transcribe it: {exc}. "
                "Please try texting me instead.",
            )
            return {}

    if not message_body:
        # Image-only or unsupported media — acknowledge gracefully.
        send_whatsapp_message(
            phone_number,
            "I received your message but couldn't read it. "
            "Please send text or a voice memo.",
        )
        return {}

    # ── Persist inbound message ────────────────────────────────────────────── #
    await sb.save_whatsapp_message(
        brokerage_id,
        phone_number,
        direction="inbound",
        body=message_body,
        media_url=MediaUrl0 or None,
        content_type=content_type,
    )

    # ── Fetch conversation history for context ─────────────────────────────── #
    history = await sb.get_whatsapp_messages(brokerage_id, phone_number, limit=20)
    # Drop the message we just saved (it's the last one) — we pass it separately.
    history = history[:-1]

    # ── Fetch brokerage details for system prompt ──────────────────────────── #
    brokerage = await sb.get_brokerage(brokerage_id)
    brokerage_name = (brokerage or {}).get("name", "your brokerage")

    # ── Run Penny agent ────────────────────────────────────────────────────── #
    reply = await penny_agent.run_penny_agent(
        brokerage_id=brokerage_id,
        brokerage_name=brokerage_name,
        contact_display_name=display_name,
        history=history,
        current_message=message_body,
    )

    # ── Send reply & persist outbound message ──────────────────────────────── #
    try:
        send_whatsapp_message(phone_number, reply)
    except TwilioNotConfigured as exc:
        # Log but don't fail — the agent ran fine, just delivery is broken.
        print(f"[whatsapp] Could not send reply: {exc}")
        return {}

    await sb.save_whatsapp_message(
        brokerage_id,
        phone_number,
        direction="outbound",
        body=reply,
    )

    return {}


# --------------------------------------------------------------------------- #
# Contact management — protected endpoints (requires valid JWT)
# --------------------------------------------------------------------------- #

class ContactIn(BaseModel):
    phone_number: str
    display_name: str | None = None


@router.get("/contacts")
async def list_contacts(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    """List all registered WhatsApp contacts for this brokerage."""
    return await sb.list_whatsapp_contacts(brokerage["id"])


@router.post("/contacts", status_code=status.HTTP_201_CREATED)
async def register_contact(
    body: ContactIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Register a realtor's WhatsApp phone number with this brokerage."""
    phone = _normalise_phone(body.phone_number)
    if not phone.startswith("+"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Phone number must be in E.164 format, e.g. +15551234567",
        )
    return await sb.upsert_whatsapp_contact(brokerage["id"], phone, body.display_name)


@router.delete("/contacts/{phone_number}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_contact(
    phone_number: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    """Remove a realtor's WhatsApp phone number from this brokerage."""
    phone = _normalise_phone(phone_number)
    await sb.delete_whatsapp_contact(brokerage["id"], phone)


@router.get("/config")
async def whatsapp_config(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Return Penny's WhatsApp number so the frontend can display it."""
    raw = settings.TWILIO_WHATSAPP_FROM or ""
    penny_number = _strip_scheme(raw) if raw else None
    return {
        "penny_whatsapp_number": penny_number,
        "configured": penny_number is not None,
    }
