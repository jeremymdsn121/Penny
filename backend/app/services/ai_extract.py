"""Anthropic-backed contract field extraction (PRD §6, §8.3, §11).

The model is told to return strict JSON for a fixed set of keys and to use null
for anything it can't find — never guess. We inject the brokerage's confirmed
knowledge rules into the system prompt so Penny stays on-brand.

PDF strategy: we send the raw PDF bytes directly to the Anthropic API as a
native document (vision-capable), which handles text-layer PDFs, fillable
AcroForms, flattened forms, and scanned images equally well — no fragile
text-extraction pre-processing needed.
"""

import base64
import json
import re
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings

MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 1500

# Keys map 1:1 to columns on the transactions table.
CONTRACT_FIELDS: list[str] = [
    "address", "city", "state", "zip",
    "buyer_name",
    "seller_name",
    "sale_price", "financing",
    "contract_date", "closing_date",
    "listing_agent_name", "listing_agent_email",
    "selling_agent_name", "selling_agent_email",
    "lender_name",
    "title_company",
    "mls_number",
]

_PRICE_FIELDS = {"list_price", "sale_price"}
_DATE_FIELDS = {"contract_date", "closing_date"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AINotConfigured(Exception):
    """Raised when no ANTHROPIC_API_KEY is configured."""


class AIExtractionError(Exception):
    """Raised when the model response can't be parsed into fields."""


def _client() -> AsyncAnthropic:
    if not settings.ANTHROPIC_API_KEY:
        raise AINotConfigured("ANTHROPIC_API_KEY is not set")
    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


def _build_system(knowledge_rules: list[dict[str, Any]]) -> str:
    rules = "\n".join(f"- {r.get('category')}: {r.get('rule')}" for r in knowledge_rules)
    rules_block = rules or "None on file yet."
    keys = ", ".join(CONTRACT_FIELDS)
    return (
        "You are Penny, a real estate transaction coordinator assistant. "
        "You extract structured data from real estate purchase contracts.\n\n"
        f"Brokerage style rules:\n{rules_block}\n\n"
        f"Extract these fields and return ONLY a JSON object with exactly these keys: {keys}.\n"
        "Strict rules:\n"
        "- If a field is not clearly present in the text, use null. NEVER guess, infer, or fabricate.\n"
        "- Dates must be ISO format YYYY-MM-DD.\n"
        "- Prices must be plain numbers with no currency symbol or commas (e.g. 450000).\n"
        "- Emails and phones exactly as written.\n"
        "- Return only the JSON object, no prose, no markdown fences."
    )


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    # Strip ```json ... ``` fences if the model added them.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the first {...} block.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise AIExtractionError("Model did not return JSON")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise AIExtractionError(f"Could not parse model JSON: {exc}")


def _clean(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "" or value.lower() in {"null", "n/a", "none", "unknown"}:
            return None
    if key in _PRICE_FIELDS and value is not None:
        digits = re.sub(r"[^\d.]", "", str(value))
        if not digits:
            return None
        try:
            return float(digits)
        except ValueError:
            return None
    if key in _DATE_FIELDS and value is not None:
        return str(value) if _DATE_RE.match(str(value)) else None
    return value


async def extract_contract_fields(
    pdf_bytes: bytes, knowledge_rules: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Extract structured fields from a contract PDF.

    The PDF is sent directly to the Anthropic API as a base64-encoded document
    so the model can read it with vision — handling text-layer, AcroForm,
    flattened, and scanned PDFs without any pre-processing.
    """
    client = _client()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_build_system(knowledge_rules or []),
            messages=[
                {
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
                        {
                            "type": "text",
                            "text": "Extract the contract fields from this document.",
                        },
                    ],
                }
            ],
        )
    except Exception as exc:
        raise AIExtractionError(f"Anthropic API error: {exc}") from exc
    raw = "".join(block.text for block in response.content if block.type == "text")
    data = _parse_json(raw)
    return {key: _clean(key, data.get(key)) for key in CONTRACT_FIELDS}
