"""AI-disclosure consent links (V2 Section 6).

A consent link is an HMAC-signed acknowledgment URL embedded in outbound email
when a brokerage opts into explicit consent. Clicking it records the party's
acknowledgment. The token signs ``{transaction_id}:{party_role}:{email}`` so the
link can't be forged or replayed for another party.
"""

import hmac
import urllib.parse
from hashlib import sha256

from app.config import settings


def _secret() -> str:
    return settings.CONSENT_SECRET or settings.SECRET_KEY


def make_token(transaction_id: str, party_role: str, email: str) -> str:
    payload = f"{transaction_id}:{party_role}:{email.lower()}"
    return hmac.new(_secret().encode(), payload.encode(), sha256).hexdigest()


def verify_token(transaction_id: str, party_role: str, email: str, token: str) -> bool:
    expected = make_token(transaction_id, party_role, email)
    return hmac.compare_digest(expected, token or "")


def consent_link(transaction_id: str, party_role: str, email: str) -> str:
    token = make_token(transaction_id, party_role, email)
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    qs = urllib.parse.urlencode({"email": email, "token": token})
    return f"{base}/api/v1/consent/{transaction_id}/{party_role}?{qs}"
