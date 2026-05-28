"""WhatsApp media download and contract-extraction formatting (V2 Section 1A).

Handles:
  - Authenticated download of Twilio media URLs
  - HEIC/HEIF → JPEG conversion via pillow-heif
  - WhatsApp summary message formatting for extracted contract fields
"""

import io
from datetime import datetime
from typing import Any

import httpx

from app.config import settings

MAX_WHATSAPP_PDF_BYTES = 15 * 1024 * 1024  # 15 MB

_DISPLAY_FIELDS: list[tuple[str, str]] = [
    ("buyer_name",         "Buyer"),
    ("seller_name",        "Seller"),
    ("sale_price",         "Price"),
    ("closing_date",       "Closing"),
    ("contract_date",      "Contract date"),
    ("listing_agent_name", "Listing agent"),
    ("selling_agent_name", "Buyer's agent"),
    ("lender_name",        "Lender"),
    ("title_company",      "Title company"),
    ("mls_number",         "MLS #"),
]

_IMPORTANT_FIELDS = {"buyer_name", "seller_name", "sale_price", "closing_date"}


async def download_twilio_media(url: str) -> bytes:
    """Download a Twilio media URL using Basic Auth. Raises on HTTP errors."""
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        raise RuntimeError("Twilio credentials not configured")
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        resp = await client.get(
            url,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            follow_redirects=True,
        )
    resp.raise_for_status()
    return resp.content


def convert_heic_to_jpeg(data: bytes) -> bytes:
    """Convert HEIC/HEIF bytes to JPEG. Requires pillow-heif installed."""
    try:
        import pillow_heif
        from PIL import Image

        pillow_heif.register_heif_opener()
        img = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except ImportError as exc:
        raise RuntimeError(
            "HEIC support requires pillow-heif: pip install pillow-heif"
        ) from exc


def _fmt(key: str, value: Any) -> str:
    """Human-readable value for a single extracted field."""
    if value is None:
        return ""
    if key == "sale_price":
        try:
            return f"${float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)
    if key in ("closing_date", "contract_date") and isinstance(value, str):
        try:
            dt = datetime.strptime(value, "%Y-%m-%d")
            return f"{dt.strftime('%B')} {dt.day}, {dt.year}"
        except ValueError:
            return value
    return str(value)


def format_extraction_summary(
    fields: dict[str, Any],
    not_found: list[str],
    duplicate_tx: dict[str, Any] | None = None,
) -> str:
    """Build the WhatsApp reply summarising an extracted contract."""
    lines: list[str] = ["📋 I found a contract. Here's what I extracted:\n"]

    # Property address as one line
    parts = [
        fields.get("address") or "",
        fields.get("city") or "",
        (fields.get("state") or "") + (" " + (fields.get("zip") or "")).strip(),
    ]
    property_line = ", ".join(p for p in parts if p.strip())
    if property_line:
        lines.append(f"Property: {property_line}")

    # Remaining display fields
    for key, label in _DISPLAY_FIELDS:
        value = fields.get(key)
        if value is not None and str(value).strip():
            lines.append(f"{label}: {_fmt(key, value)}")

    # Missing important fields
    missing_important = [k for k in not_found if k in _IMPORTANT_FIELDS]
    if missing_important:
        labels = ", ".join(
            dict(_DISPLAY_FIELDS).get(k, k.replace("_", " ")) for k in missing_important
        )
        lines.append(f"\n⚠️ I couldn't find: {labels}")

    # Duplicate warning
    if duplicate_tx:
        addr = duplicate_tx.get("address") or "this address"
        stage = (duplicate_tx.get("stage") or "active").replace("_", " ")
        closing = duplicate_tx.get("closing_date") or ""
        closing_str = f", closing {closing}" if closing else ""
        lines.append(
            f"\n⚠️ I already have an active transaction for {addr} "
            f"({stage}{closing_str}). Create a new one anyway?"
        )

    lines.append("\nReply YES to create this transaction, or tell me any corrections first.")
    return "\n".join(lines)
