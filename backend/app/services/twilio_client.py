"""Twilio helper — send WhatsApp messages back to realtors.

Intentionally thin: we only need to send text replies and (optionally) validate
incoming webhook signatures. All AI logic lives in sloane_agent.py.
"""

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
