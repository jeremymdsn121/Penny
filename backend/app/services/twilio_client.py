"""Twilio helper — send WhatsApp messages back to realtors.

Intentionally thin: we only need to send text replies and (optionally) validate
incoming webhook signatures. All AI logic lives in penny_agent.py.
"""

import json
from functools import lru_cache

from starlette.requests import Request
from twilio.rest import Client as TwilioClient
from twilio.request_validator import RequestValidator

from app.config import settings


class TwilioNotConfigured(Exception):
    """Raised when Twilio credentials are missing."""


def _client() -> TwilioClient:
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise TwilioNotConfigured("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set")
    return TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def _from_number() -> str:
    if not settings.TWILIO_WHATSAPP_FROM:
        raise TwilioNotConfigured("TWILIO_WHATSAPP_FROM must be set")
    return settings.TWILIO_WHATSAPP_FROM


def send_whatsapp_message(to_number: str, body: str) -> None:
    """Send a WhatsApp text message to a realtor.

    Args:
        to_number: E.164 phone number, e.g. "+15551234567". The "whatsapp:" prefix
                   is added automatically.
        body: The text to send. Keep under 1600 characters for a single segment.
    """
    client = _client()
    # Ensure the "whatsapp:" scheme prefix is present.
    to = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"
    client.messages.create(
        from_=_from_number(),
        to=to,
        body=body,
    )


@lru_cache(maxsize=4)
def _content_sids(raw: str) -> dict[str, str]:
    """Parse TWILIO_CONTENT_SIDS (JSON: template key -> ContentSid)."""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v}


def _template_var(value: str) -> str:
    """Sanitise a template variable: Meta rejects newlines/tabs and empties."""
    cleaned = " ".join(str(value or "").split())
    return cleaned[:300] or "—"


def send_whatsapp_template(
    to_number: str, template_key: str, variables: list[str], fallback_body: str
) -> None:
    """Send a proactive (business-initiated) WhatsApp message.

    The production WhatsApp API rejects free-form messages sent outside the
    24-hour customer-service window — exactly when proactive nudges fire — so
    these must go out as approved templates. When ``TWILIO_CONTENT_SIDS`` maps
    ``template_key`` to an approved ContentSid (see WHATSAPP_TEMPLATES.md), the
    message is sent via the Content API with positional ``variables`` (template
    {{1}}, {{2}}, …). With no mapping configured, falls back to free-form
    ``fallback_body`` — today's sandbox behavior, unchanged.

    In-window conversational replies (the agent texted Penny, she answers)
    don't need this — keep using ``send_whatsapp_message`` for those.
    """
    sid = _content_sids(settings.TWILIO_CONTENT_SIDS or "").get(template_key)
    if not sid:
        send_whatsapp_message(to_number, fallback_body)
        return
    client = _client()
    to = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"
    client.messages.create(
        from_=_from_number(),
        to=to,
        content_sid=sid,
        content_variables=json.dumps(
            {str(i + 1): _template_var(v) for i, v in enumerate(variables)}
        ),
    )


def _sms_from_number() -> str:
    if not settings.TWILIO_SMS_FROM:
        raise TwilioNotConfigured("TWILIO_SMS_FROM must be set for the SMS channel")
    return settings.TWILIO_SMS_FROM


def send_sms_message(to_number: str, body: str) -> None:
    """Send a standard SMS to a realtor (the WhatsApp fallback channel).

    Replies originate from TWILIO_SMS_FROM, not the WhatsApp sender. SMS segments
    are 160 chars (70 for unicode); long replies are split by the carrier.
    """
    client = _client()
    client.messages.create(
        from_=_sms_from_number(),
        to=to_number,
        body=body,
    )


def webhook_url(request: Request) -> str:
    """Reconstruct the public URL Twilio actually signed.

    Twilio signs the full https URL configured in the console, but behind a
    TLS-terminating proxy (e.g. Render) uvicorn sees the forwarded request as
    http unless it's been told to trust the proxy, so ``request.url.scheme`` is
    ``http`` and the HMAC never matches. Honour ``X-Forwarded-Proto`` so
    validation works regardless of the uvicorn start command.
    """
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    url = request.url
    if proto and proto != url.scheme:
        url = url.replace(scheme=proto)
    return str(url)


def validate_twilio_signature(url: str, params: dict, signature: str) -> bool:
    """Return True if the X-Twilio-Signature header is valid for this request.

    In local dev you can set TWILIO_SKIP_VALIDATION=true to bypass this check.
    """
    if settings.TWILIO_SKIP_VALIDATION:
        return True
    if not settings.TWILIO_AUTH_TOKEN:
        return False
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    return validator.validate(url, params, signature)
