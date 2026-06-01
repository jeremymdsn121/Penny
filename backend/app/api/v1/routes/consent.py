"""AI-disclosure consent + brokerage compliance settings (V2 Section 6).

  - GET /consent/{tx}/{role}     — public; verifies the signed link and records
                                    a party's acknowledgment, returns a thank-you page
  - GET/PUT /compliance-settings — brokerage disclosure/consent settings
  - GET /transactions/{id}/consents — acknowledgment status for a transaction
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.services import consent as consent_svc

router = APIRouter(tags=["consent"])

_SETTINGS_FIELDS = ("ai_disclosure_enabled", "ai_disclosure_text", "request_ai_consent")


def _page(message: str) -> HTMLResponse:
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Sloane</title></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#F9FAFB;margin:0;padding:48px 16px;text-align:center;color:#111827;">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;padding:36px;box-shadow:0 1px 3px rgba(0,0,0,.08);">
    <div style="font-size:24px;font-weight:700;color:#7C3AED;">Sloane</div>
    <p style="margin-top:20px;font-size:15px;line-height:1.6;">{message}</p>
  </div>
</body></html>"""
    return HTMLResponse(content=html)


@router.get("/consent/{transaction_id}/{party_role}", response_class=HTMLResponse)
async def acknowledge(
    transaction_id: str,
    party_role: str,
    request: Request,
    email: str = "",
    token: str = "",
) -> HTMLResponse:
    """Public: record a party's AI-disclosure acknowledgment from a signed link."""
    if not email or not consent_svc.verify_token(transaction_id, party_role, email, token):
        return _page("This acknowledgment link is invalid.")

    tx = await sb.get_transaction_by_id(transaction_id)
    if tx is None:
        return _page("We couldn't find the related transaction.")

    # Skip if this party already acknowledged.
    existing = await sb.list_party_consents(transaction_id)
    already = any(
        c.get("party_role") == party_role
        and (c.get("email") or "").lower() == email.lower()
        and c.get("consented_at")
        for c in existing
    )
    if not already:
        await sb.record_party_consent(
            {
                "transaction_id": transaction_id,
                "party_role": party_role,
                "email": email,
                "consented_at": datetime.now(timezone.utc).isoformat(),
                "ip_address": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "consent_method": "email_link",
            }
        )
    return _page("Thank you — your acknowledgment has been recorded.")


class ComplianceSettingsIn(BaseModel):
    ai_disclosure_enabled: bool | None = None
    ai_disclosure_text: str | None = None
    request_ai_consent: bool | None = None


@router.get("/compliance-settings")
async def get_settings(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    return {k: brokerage.get(k) for k in _SETTINGS_FIELDS}


@router.put("/compliance-settings")
async def update_settings(
    body: ComplianceSettingsIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update")
    updated = await sb.update_brokerage(brokerage["id"], data)
    return {k: updated.get(k) for k in _SETTINGS_FIELDS}


@router.get("/transactions/{transaction_id}/consents")
async def list_consents(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return await sb.list_party_consents(transaction_id)
