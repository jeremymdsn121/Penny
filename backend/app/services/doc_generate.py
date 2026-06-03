"""Anthropic-backed document drafting.

Penny drafts professional real estate correspondence (status updates, cover
letters, follow-ups) for a transaction, in the brokerage's voice. The
brokerage's *confirmed* knowledge_rules are injected so drafts stay on brand
(this is the payoff of the knowledge base).

Drafting only — this module never sends anything. The caller surfaces the draft
for human review/edit, and sending is a separate, explicitly confirmed step
(PRD hard rule: never skip confirmation for document sending).
"""

import json
import re
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings

MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 1500

# doc_type -> what Penny should produce.
DOC_TYPES: dict[str, str] = {
    "status_update": "a concise status update on where the transaction stands and any next steps",
    "cover_letter": "a cover letter / transmittal to accompany documents being sent to a party",
    "follow_up": "a polite follow-up requesting an outstanding item, signature, or action",
    "congratulations": "a warm congratulations note (e.g. on going under contract or closing)",
    "custom": "a document following the provided instructions",
}


class DocNotConfigured(Exception):
    """Raised when no ANTHROPIC_API_KEY is configured."""


class DocGenerationError(Exception):
    """Raised when the model response can't be parsed into a draft."""


def _client() -> AsyncAnthropic:
    if not settings.ANTHROPIC_API_KEY:
        raise DocNotConfigured("ANTHROPIC_API_KEY is not set")
    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


# Fields worth giving the model as context, label -> transaction key.
_CONTEXT_FIELDS: list[tuple[str, str]] = [
    ("Property address", "address"),
    ("City", "city"),
    ("State", "state"),
    ("Stage", "stage"),
    ("Sale price", "sale_price"),
    ("Financing", "financing"),
    ("Contract date", "contract_date"),
    ("Closing date", "closing_date"),
    ("Buyer", "buyer_name"),
    ("Seller", "seller_name"),
    ("Listing agent", "listing_agent_name"),
    ("Selling agent", "selling_agent_name"),
    ("Lender", "lender_name"),
    ("Title company", "title_company"),
]


def _tx_context(transaction: dict[str, Any]) -> str:
    lines = []
    for label, key in _CONTEXT_FIELDS:
        val = transaction.get(key)
        if val not in (None, ""):
            lines.append(f"- {label}: {val}")
    return "\n".join(lines) if lines else "- (no transaction details on file)"


def _build_system(
    brokerage_name: str, style_rules: list[dict[str, Any]]
) -> str:
    rules = "\n".join(
        f"- {r.get('category')}: {r.get('rule')}" for r in style_rules
    )
    rules_block = rules or "None on file yet — use a clear, warm, professional tone."
    return (
        f"You are Penny, a transaction coordinator drafting correspondence on behalf "
        f"of {brokerage_name}. Write in the brokerage's voice, following their confirmed "
        f"brand/style rules below.\n\n"
        f"Brand & style rules:\n{rules_block}\n\n"
        "Return ONLY a JSON object with exactly these keys: \"subject\" and \"body\".\n"
        "Rules:\n"
        "- The body is plain text, ready to send. Use real line breaks for paragraphs.\n"
        "- Be professional and concise.\n"
        "- NEVER invent facts (names, dates, prices, terms) that aren't provided. If a "
        "necessary detail is missing, insert a clearly-marked placeholder like [CLOSING DATE].\n"
        "- Do not fabricate signatures or contact info beyond what the style rules specify.\n"
        "- Return only the JSON object — no prose, no markdown fences."
    )


def _build_user(
    doc_type: str,
    transaction: dict[str, Any],
    recipient: str | None,
    instructions: str | None,
) -> str:
    purpose = DOC_TYPES.get(doc_type, DOC_TYPES["custom"])
    parts = [
        f"Draft {purpose}.",
        "",
        "Transaction details:",
        _tx_context(transaction),
    ]
    if recipient:
        parts += ["", f"Intended recipient: {recipient}"]
    if instructions:
        parts += ["", f"Specific instructions: {instructions}"]
    return "\n".join(parts)


def _parse(text: str) -> dict[str, str]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # strict=False tolerates literal newlines/tabs inside strings — document
    # bodies are multi-line and models don't always escape them.
    try:
        data = json.loads(text, strict=False)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise DocGenerationError("Model did not return JSON.")
        try:
            data = json.loads(match.group(0), strict=False)
        except json.JSONDecodeError as exc:
            raise DocGenerationError(f"Could not parse model JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DocGenerationError("Model response was not a JSON object.")
    subject = str(data.get("subject", "")).strip()
    body = str(data.get("body", "")).strip()
    if not body:
        raise DocGenerationError("Model returned an empty document body.")
    return {"subject": subject, "body": body}


async def generate_document(
    *,
    transaction: dict[str, Any],
    doc_type: str,
    brokerage_name: str,
    style_rules: list[dict[str, Any]] | None = None,
    recipient: str | None = None,
    instructions: str | None = None,
) -> dict[str, str]:
    """Draft a document for a transaction. Returns ``{"subject", "body"}``.

    Raises DocNotConfigured if the API key is missing, or DocGenerationError if
    the response can't be parsed.
    """
    client = _client()
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_build_system(brokerage_name, style_rules or []),
            messages=[
                {
                    "role": "user",
                    "content": _build_user(doc_type, transaction, recipient, instructions),
                }
            ],
        )
    except Exception as exc:
        raise DocGenerationError(f"Anthropic API error: {exc}") from exc
    raw = "".join(block.text for block in response.content if block.type == "text")
    return _parse(raw)
