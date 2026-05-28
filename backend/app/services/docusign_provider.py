"""DocuSign e-signature seam (V2 Section 8).

The single place a real DocuSign integration will plug in. Sending documents for
signature requires a DocuSign developer account + integration key (OAuth 2.0
Authorization Code grant) and, for production, DocuSign partner review — all of
which are credential/business prerequisites outside engineering scope (see
BLOCKERS.md).

So for now this reports "not connected" and sends nothing. When credentials are
secured and the flow is testable, only the bodies below change (OAuth connect +
token storage, envelope creation, Connect webhook for status) — callers stay the
same. Deliberately not built blind — see the deferred-integration note in memory.
"""

from typing import Any


def status(brokerage: dict[str, Any]) -> dict[str, Any]:
    """Whether DocuSign is connected for this brokerage."""
    return {"connected": False, "provider": "docusign"}


def is_connected(brokerage: dict[str, Any]) -> bool:
    return status(brokerage)["connected"]


async def send_envelope(
    brokerage: dict[str, Any],
    *,
    document_url: str,
    signers: list[dict[str, str]],
    email_subject: str,
    message: str,
) -> dict[str, Any]:
    """Create and send a DocuSign envelope. No-op until DocuSign is connected.

    Returns ``{sent, envelope_id, reason}``.
    """
    return {
        "sent": False,
        "envelope_id": None,
        "reason": (
            "DocuSign isn't connected. Sending documents for signature needs a "
            "DocuSign developer account + integration key (and partner review for "
            "production). This is a credential/business prerequisite — see BLOCKERS.md."
        ),
    }
