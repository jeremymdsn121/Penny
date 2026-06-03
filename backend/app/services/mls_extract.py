"""Anthropic-backed MLS listing extraction (PRD task ``mls-entry``).

Given a listing packet (listing agreement, property data sheet, etc.) as a PDF,
extract MLS-ready listing fields for the agent to review before entering them
into the MLS. Same approach as ``ai_extract``: the PDF is sent to the model as a
native document and the model returns strict JSON with null for anything it
can't find — never guessing.
"""

import base64
import json
import re
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings

MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 2000

# Keys map 1:1 to columns on the listings table.
MLS_FIELDS: list[str] = [
    "address", "city", "state", "zip",
    "property_type",
    "list_price",
    "bedrooms", "bathrooms",
    "square_footage", "lot_size_sqft",
    "year_built", "stories", "garage_spaces",
    "hoa_fee", "hoa_frequency",
    "annual_taxes",
    "parcel_number",
    "public_remarks",
    "features",
    "school_district",
    "listing_agent_name", "listing_agent_email",
    "seller_name",
]

_INT_FIELDS = {"bedrooms", "square_footage", "year_built"}
_NUM_FIELDS = {"list_price", "bathrooms", "lot_size_sqft", "stories",
               "garage_spaces", "hoa_fee", "annual_taxes"}
_LIST_FIELDS = {"features"}


class MLSNotConfigured(Exception):
    """Raised when no ANTHROPIC_API_KEY is configured."""


class MLSExtractionError(Exception):
    """Raised when the model response can't be parsed into fields."""


def _client() -> AsyncAnthropic:
    if not settings.ANTHROPIC_API_KEY:
        raise MLSNotConfigured("ANTHROPIC_API_KEY is not set")
    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


def _build_system() -> str:
    keys = ", ".join(MLS_FIELDS)
    return (
        "You are Penny, a real estate transaction coordinator assistant. You extract "
        "MLS listing data from a listing packet (listing agreement, property data "
        "sheet, seller disclosures) so an agent can enter the listing into the MLS.\n\n"
        f"Extract these fields and return ONLY a JSON object with exactly these keys: {keys}.\n"
        "Strict rules:\n"
        "- If a field is not clearly present, use null. NEVER guess, infer, or fabricate.\n"
        "- Numbers must be plain (no $, commas, or units): list_price 450000, bathrooms 2.5, "
        "square_footage 1800, lot_size_sqft 8000, hoa_fee 150, annual_taxes 6200.\n"
        "- property_type must be one of: single_family, condo, townhouse, multi_family, land, other.\n"
        "- features must be a JSON array of short strings (e.g. [\"hardwood floors\", \"pool\"]) or null.\n"
        "- public_remarks is the marketing description if present, else null.\n"
        "- hoa_frequency is the HOA fee cadence if present (e.g. monthly, quarterly, annual).\n"
        "- Return only the JSON object, no prose, no markdown fences."
    )


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise MLSExtractionError("Model did not return JSON")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise MLSExtractionError(f"Could not parse model JSON: {exc}")


def _clean(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in _LIST_FIELDS:
        if isinstance(value, list):
            items = [str(v).strip() for v in value if str(v).strip()]
            return items or None
        if isinstance(value, str) and value.strip():
            return [p.strip() for p in value.split(",") if p.strip()] or None
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "" or value.lower() in {"null", "n/a", "none", "unknown"}:
            return None
    if key in _INT_FIELDS and value is not None:
        digits = re.sub(r"[^\d]", "", str(value))
        return int(digits) if digits else None
    if key in _NUM_FIELDS and value is not None:
        digits = re.sub(r"[^\d.]", "", str(value))
        try:
            return float(digits) if digits else None
        except ValueError:
            return None
    return value


async def extract_listing_fields(pdf_bytes: bytes) -> dict[str, Any]:
    """Extract MLS listing fields from a listing-packet PDF."""
    client = _client()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_build_system(),
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": "Extract the MLS listing fields from this packet."},
                ],
            }],
        )
    except Exception as exc:
        raise MLSExtractionError(f"Anthropic API error: {exc}") from exc
    raw = "".join(block.text for block in response.content if block.type == "text")
    data = _parse_json(raw)
    return {key: _clean(key, data.get(key)) for key in MLS_FIELDS}
