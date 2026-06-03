"""WhatsApp inbound webhook + contact management endpoints.

Twilio calls POST /whatsapp/inbound for every message received on the configured
WhatsApp number. We validate the Twilio signature, look up the sender, transcribe
any voice memo, run the Penny agent, and reply via Twilio.

V2 Section 1A adds:
  - PDF / image inbound → contract extraction → pending confirmation flow
  - Stateful correction parsing while a pending transaction is awaiting YES/NO

Contact management (register/list/delete realtor phone numbers) is done by the
brokerage admin from the frontend and requires a valid JWT.
"""

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.config import settings
from app.services import (
    ai_extract,
    compliance_checklist,
    media_extract,
    penny_agent,
    workflow,
)
from app.services.twilio_client import (
    TwilioNotConfigured,
    send_whatsapp_message,
    validate_twilio_signature,
    webhook_url,
)
from app.services.whisper import TranscriptionError, transcribe_twilio_audio

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

CONTRACTS_BUCKET = "contracts"

_CONFIRM_WORDS = frozenset({
    "yes", "yep", "yup", "correct", "looks good", "create it", "create", "confirmed", "confirm",
})
_CANCEL_WORDS = frozenset({"no", "nope", "cancel", "nevermind", "never mind", "stop", "abort"})


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


def _is_contract_media(content_type_raw: str) -> bool:
    """True for PDF and image content types Penny can extract contract data from."""
    return "pdf" in content_type_raw or content_type_raw.startswith("image/")


def _classify_pending_reply(text: str) -> str:
    """Return 'confirm', 'cancel', or 'correction' for a pending-flow reply."""
    t = re.sub(r"[^\w\s]", "", text.strip().lower())
    t = " ".join(t.split())
    if t in _CONFIRM_WORDS:
        return "confirm"
    if t in _CANCEL_WORDS:
        return "cancel"
    return "correction"


def _image_media_type(content_type_raw: str) -> str:
    """Return the bare media type ('jpeg'/'png') for Anthropic's image block."""
    if "png" in content_type_raw:
        return "png"
    return "jpeg"  # covers jpeg, heic (after conversion), and generic image/*


# --------------------------------------------------------------------------- #
# Media extraction flow (V2 Section 1A)
# --------------------------------------------------------------------------- #

async def _handle_media_extraction(
    phone_number: str,
    brokerage_id: str,
    media_url: str,
    content_type_raw: str,
) -> None:
    """Download, extract, store pending, and send summary for an inbound PDF/image."""
    # Download from Twilio
    try:
        media_bytes = await media_extract.download_twilio_media(media_url)
    except Exception:
        send_whatsapp_message(
            phone_number,
            "I had trouble downloading that file. Can you try sending it again?",
        )
        return

    is_pdf = "pdf" in content_type_raw

    # Size guard (WhatsApp PDFs only — images are typically small)
    if is_pdf and len(media_bytes) > media_extract.MAX_WHATSAPP_PDF_BYTES:
        mb = len(media_bytes) // (1024 * 1024)
        send_whatsapp_message(
            phone_number,
            f"That PDF is {mb} MB — too large for WhatsApp processing (15 MB limit). "
            "Please compress it or upload via the Penny web dashboard.",
        )
        return

    # Extract fields
    rules = await sb.get_confirmed_knowledge_rules(brokerage_id)
    pdf_storage_url: str | None = None

    try:
        if is_pdf:
            path = f"{brokerage_id}/{uuid.uuid4()}.pdf"
            await sb.upload_object(CONTRACTS_BUCKET, path, media_bytes, "application/pdf")
            pdf_storage_url = path
            fields = await ai_extract.extract_contract_fields(media_bytes, rules)
            await sb.save_whatsapp_message(
                brokerage_id, phone_number,
                direction="inbound", body="[PDF contract received]",
                content_type="document", media_url=media_url,
            )
        else:
            # Convert HEIC/HEIF before sending to Anthropic
            if "heic" in content_type_raw or "heif" in content_type_raw:
                try:
                    image_bytes = media_extract.convert_heic_to_jpeg(media_bytes)
                    img_type = "jpeg"
                except RuntimeError:
                    send_whatsapp_message(
                        phone_number,
                        "I received your image but couldn't process the HEIC format. "
                        "Please send the contract as a JPEG or PDF.",
                    )
                    return
            else:
                image_bytes = media_bytes
                img_type = _image_media_type(content_type_raw)

            fields = await ai_extract.extract_contract_fields_from_image(
                image_bytes, img_type, rules
            )
            await sb.save_whatsapp_message(
                brokerage_id, phone_number,
                direction="inbound", body="[Contract photo received]",
                content_type="image", media_url=media_url,
            )

    except ai_extract.AINotConfigured:
        send_whatsapp_message(
            phone_number,
            "I received your contract but AI extraction isn't configured yet. "
            "Please upload it via the Penny web dashboard.",
        )
        return
    except ai_extract.AIExtractionError as exc:
        send_whatsapp_message(
            phone_number,
            f"I couldn't extract the contract fields: {exc}. "
            "Please try again or upload via the web dashboard.",
        )
        return
    except Exception:
        send_whatsapp_message(
            phone_number,
            "I had trouble processing that file. Can you try sending it again?",
        )
        return

    # Duplicate detection — warn if an active transaction exists at this address
    address = (fields.get("address") or "").strip()
    duplicate_tx: dict[str, Any] | None = None
    if address:
        existing = await sb.search_transactions(brokerage_id, address)
        active = [tx for tx in existing if tx.get("stage") not in ("closed", "cancelled")]
        if active:
            duplicate_tx = active[0]

    # Store pending (upsert replaces any prior extraction for this contact)
    not_found = [k for k, v in fields.items() if v is None]
    await sb.upsert_pending_whatsapp_transaction({
        "brokerage_id": brokerage_id,
        "phone_number": phone_number,
        "extracted_fields": fields,
        "pdf_storage_url": pdf_storage_url,
    })

    # Reply with summary
    summary = media_extract.format_extraction_summary(fields, not_found, duplicate_tx)
    send_whatsapp_message(phone_number, summary)
    await sb.save_whatsapp_message(
        brokerage_id, phone_number, direction="outbound", body=summary,
    )


# --------------------------------------------------------------------------- #
# Pending transaction confirmation / correction flow (V2 Section 1A)
# --------------------------------------------------------------------------- #

async def _handle_pending_reply(
    pending: dict[str, Any],
    message_body: str,
    brokerage_id: str,
    phone_number: str,
) -> None:
    """Process a text reply when the agent has a pending extraction awaiting confirmation."""
    intent = _classify_pending_reply(message_body)

    if intent == "cancel":
        await sb.delete_pending_whatsapp_transaction(pending["id"])
        reply = "Got it — I've discarded that contract. Send a new one whenever you're ready."
        send_whatsapp_message(phone_number, reply)
        await sb.save_whatsapp_message(
            brokerage_id, phone_number, direction="outbound", body=reply,
        )
        return

    if intent == "confirm":
        fields: dict[str, Any] = pending.get("extracted_fields") or {}
        tx_data = {k: v for k, v in fields.items() if v is not None}
        tx_data["brokerage_id"] = brokerage_id
        tx_data.setdefault("stage", "under_contract")
        if pending.get("pdf_storage_url"):
            tx_data["contract_pdf_url"] = pending["pdf_storage_url"]

        try:
            tx = await sb.insert_transaction(tx_data)
            try:
                await compliance_checklist.instantiate_for_transaction(tx)
                await workflow.generate_stage_tasks(tx, tx.get("stage") or "under_contract")
            except sb.SupabaseError:
                pass  # best-effort; can be rebuilt from the web app
            await sb.delete_pending_whatsapp_transaction(pending["id"])
            address = tx.get("address") or "the property"
            reply = (
                f"✅ Transaction created for {address}! "
                "You can view and edit all the details in the Penny dashboard."
            )
        except sb.SupabaseError as exc:
            reply = (
                f"I couldn't save the transaction: {exc.detail}. "
                "Please try again or create it via the web dashboard."
            )
        send_whatsapp_message(phone_number, reply)
        await sb.save_whatsapp_message(
            brokerage_id, phone_number, direction="outbound", body=reply,
        )
        return

    # Correction — ask Claude to parse and apply
    fields = pending.get("extracted_fields") or {}
    try:
        updates = await ai_extract.parse_correction(fields, message_body)
    except (ai_extract.AINotConfigured, ai_extract.AIExtractionError):
        updates = {}

    if updates:
        merged = {**fields, **updates}
        await sb.update_pending_whatsapp_transaction(pending["id"], {"extracted_fields": merged})
        not_found = [k for k, v in merged.items() if v is None]
        reply = "Got it — here's the updated summary:\n\n" + media_extract.format_extraction_summary(
            merged, not_found
        )
    else:
        # Could not parse correction — show summary again
        not_found = [k for k, v in fields.items() if v is None]
        reply = (
            "I'm still waiting on your response. "
            + media_extract.format_extraction_summary(fields, not_found)
        )

    send_whatsapp_message(phone_number, reply)
    await sb.save_whatsapp_message(
        brokerage_id, phone_number, direction="outbound", body=reply,
    )


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
        url = webhook_url(request)
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

    # No From field means this is a status callback — acknowledge and stop.
    if not From:
        return {}

    phone_number = _normalise_phone(From)
    num_media = int(NumMedia or "0")
    has_media = num_media > 0 and bool(MediaUrl0)
    content_type_raw = (MediaContentType0 or "").lower() if has_media else ""

    # ── Look up which brokerage this phone number belongs to ──────────────── #
    contact = await sb.lookup_whatsapp_contact(phone_number)
    if contact is None:
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

    # ── PDF / image media → contract extraction flow ──────────────────────── #
    if has_media and _is_contract_media(content_type_raw):
        await _handle_media_extraction(phone_number, brokerage_id, MediaUrl0, content_type_raw)
        return {}

    # ── Other non-audio media → guidance message ──────────────────────────── #
    if has_media and "audio" not in content_type_raw:
        send_whatsapp_message(
            phone_number,
            "I can read PDF contracts and contract photos. "
            "Please send the file as a PDF for best results.",
        )
        return {}

    # ── Resolve the message text ───────────────────────────────────────────── #
    content_type = "text"
    message_body = Body.strip()

    if has_media and "audio" in content_type_raw and MediaUrl0:
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

    # ── Pending transaction: confirmation or correction ────────────────────── #
    pending = await sb.get_pending_whatsapp_transaction(brokerage_id, phone_number)
    if pending:
        await _handle_pending_reply(pending, message_body, brokerage_id, phone_number)
        return {}

    # ── Fetch conversation history for context ─────────────────────────────── #
    history = await sb.get_whatsapp_messages(brokerage_id, phone_number, limit=20)
    # Drop the message we just saved (it's the last one) — we pass it separately.
    history = history[:-1]

    # ── Fetch brokerage details for system prompt ──────────────────────────── #
    brokerage = await sb.get_brokerage(brokerage_id)
    brokerage_name = (brokerage or {}).get("name", "your brokerage")

    # ── Run Penny agent ────────────────────────────────────────────────────── #
    # Never let a model/tool error become silence — the inbound is already saved,
    # so on failure send a graceful note instead of dropping the conversation.
    try:
        reply = await penny_agent.run_penny_agent(
            brokerage_id=brokerage_id,
            brokerage_name=brokerage_name,
            contact_display_name=display_name,
            history=history,
            current_message=message_body,
            agent_id=contact.get("agent_id"),
        )
    except Exception as exc:  # noqa: BLE001 — surface, don't crash the webhook
        print(f"[whatsapp] agent error: {exc!r}")
        reply = (
            "Sorry, I'm having trouble on my end right now and couldn't get to "
            "that. Please try me again in a few minutes."
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
    # Optionally link the number to an agent so their style applies to drafts.
    agent_id: str | None = None


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
    return await sb.upsert_channel(
        brokerage["id"], "whatsapp", phone, body.display_name, body.agent_id
    )


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


# --------------------------------------------------------------------------- #
# Brokerage messaging settings (reply routing) — protected
# --------------------------------------------------------------------------- #

# Brokerage-level toggles that govern how Penny routes communications. Kept here
# (with the Messaging page's other APIs) rather than under compliance settings.
_MESSAGING_SETTINGS_FIELDS = (
    "forward_replies_to_agent",
    "email_agent_autoreply_enabled",
    "email_outside_draft_enabled",
)


class MessagingSettingsIn(BaseModel):
    # Forward each inbound email reply to the deal's agent inbox (opt-in).
    forward_replies_to_agent: bool | None = None
    # Let Penny reply by email when one of the brokerage's own agents emails her
    # about a deal (two-way email, Phase 1 — defaults on).
    email_agent_autoreply_enabled: bool | None = None
    # When an outside party emails, have Penny draft a suggested reply for the
    # agent to review and send (never auto-sends to outside parties).
    email_outside_draft_enabled: bool | None = None


@router.get("/settings")
async def get_messaging_settings(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Return the brokerage's messaging/reply-routing settings."""
    return {k: brokerage.get(k) for k in _MESSAGING_SETTINGS_FIELDS}


@router.put("/settings")
async def update_messaging_settings(
    body: MessagingSettingsIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Update the brokerage's messaging/reply-routing settings."""
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update"
        )
    updated = await sb.update_brokerage(brokerage["id"], data)
    return {k: updated.get(k) for k in _MESSAGING_SETTINGS_FIELDS}
