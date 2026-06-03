"""SMS inbound webhook + contact management (V2 Section 1C).

The SMS fallback channel mirrors the WhatsApp agent for realtors who don't use
WhatsApp. Twilio calls POST /sms/inbound for every SMS to the configured number.
We validate the signature, look up the sender in agent_channels (channel='sms'),
run the same Penny tool-use agent, and reply via standard SMS.

Differences from WhatsApp: text only — no voice transcription and no inbound
media/PDF (WhatsApp handles document uploads). Replies originate from
TWILIO_SMS_FROM, not the WhatsApp sender.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.v1.routes.whatsapp import _normalise_phone
from app.config import settings
from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.services import penny_agent
from app.services.twilio_client import (
    TwilioNotConfigured,
    send_sms_message,
    validate_twilio_signature,
    webhook_url,
)

router = APIRouter(prefix="/sms", tags=["sms"])

CHANNEL = "sms"


@router.post("/inbound")
async def inbound(request: Request) -> Any:
    """Receive an inbound SMS from Twilio and reply via the Penny agent."""
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items()}

    if not settings.TWILIO_SKIP_VALIDATION:
        signature = request.headers.get("X-Twilio-Signature", "")
        url = webhook_url(request)
        if not validate_twilio_signature(url, form_data, signature):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature"
            )

    From = form_data.get("From", "")
    Body = form_data.get("Body", "")
    if not From:
        return {}  # status callback

    phone_number = _normalise_phone(From)
    message_body = Body.strip()

    contact = await sb.lookup_channel(phone_number, CHANNEL)
    if contact is None:
        try:
            send_sms_message(
                phone_number,
                "Hi! I don't recognise this number. Please ask your broker to "
                "register it for SMS in Penny first.",
            )
        except TwilioNotConfigured:
            pass
        return {}

    brokerage_id: str = contact["brokerage_id"]
    display_name: str | None = contact.get("display_name")

    if not message_body:
        send_sms_message(
            phone_number, "I received your message but couldn't read any text. Please try again."
        )
        return {}

    await sb.save_whatsapp_message(
        brokerage_id, phone_number, direction="inbound", body=message_body, content_type="text"
    )

    history = await sb.get_whatsapp_messages(brokerage_id, phone_number, limit=20)
    history = history[:-1]  # drop the message we just saved (passed separately)

    brokerage = await sb.get_brokerage(brokerage_id)
    brokerage_name = (brokerage or {}).get("name", "your brokerage")

    reply = await penny_agent.run_penny_agent(
        brokerage_id=brokerage_id,
        brokerage_name=brokerage_name,
        contact_display_name=display_name,
        history=history,
        current_message=message_body,
        agent_id=contact.get("agent_id"),
    )

    try:
        send_sms_message(phone_number, reply)
    except TwilioNotConfigured as exc:
        print(f"[sms] Could not send reply: {exc}")
        return {}

    await sb.save_whatsapp_message(
        brokerage_id, phone_number, direction="outbound", body=reply
    )
    return {}


# --------------------------------------------------------------------------- #
# Contact management — protected (requires valid JWT)
# --------------------------------------------------------------------------- #

class SmsContactIn(BaseModel):
    phone_number: str
    display_name: str | None = None
    agent_id: str | None = None


@router.get("/contacts")
async def list_contacts(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    return await sb.list_channels(brokerage["id"], CHANNEL)


@router.post("/contacts", status_code=status.HTTP_201_CREATED)
async def register_contact(
    body: SmsContactIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    phone = _normalise_phone(body.phone_number)
    if not phone.startswith("+"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Phone number must be in E.164 format, e.g. +15551234567",
        )
    return await sb.upsert_channel(
        brokerage["id"], CHANNEL, phone, body.display_name, body.agent_id
    )


@router.delete("/contacts/{phone_number}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_contact(
    phone_number: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    phone = _normalise_phone(phone_number)
    await sb.delete_channel(brokerage["id"], CHANNEL, phone)


@router.get("/config")
async def sms_config(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Return Penny's SMS number so the frontend can display it."""
    number = settings.TWILIO_SMS_FROM or None
    return {"penny_sms_number": number, "configured": number is not None}
