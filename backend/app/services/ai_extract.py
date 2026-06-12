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
import logging
import re
from typing import Any

import fitz  # PyMuPDF — rasterise scanned PDFs to sharp page images

from anthropic import (
    APIConnectionError,
    APITimeoutError,
    AsyncAnthropic,
    InternalServerError,
    OverloadedError,
    RateLimitError,
)

from app.config import settings
from app.core import supabase_client as sb

logger = logging.getLogger(__name__)

# Transient Anthropic failures we want to report as "service slow/busy" rather
# than "couldn't read the contract" — they warrant a retry, not a re-upload.
_TRANSIENT_AI_ERRORS = (
    APITimeoutError,
    APIConnectionError,
    RateLimitError,
    OverloadedError,
    InternalServerError,
)


def _usage_dict(usage: Any) -> dict[str, int]:
    """Pull token counts off an Anthropic response.usage object."""
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }

MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 1500

# Per-request timeout + retry budget for extraction calls. Vision over a PDF /
# photo is heavier than a chat turn, so this is more generous than the agent's
# 15s — but it still bounds a stuck call instead of riding the SDK's ~10-min
# default × 2 retries (which could hang an inbound media upload for ~30 minutes).
EXTRACT_TIMEOUT_SECONDS = 60.0
EXTRACT_MAX_RETRIES = 1

# Extraction is a deterministic read, not a creative task — decode at temperature
# 0 so the same contract yields the same fields every time (the API default of
# 1.0 was sampling randomly, which is how a typed price read right one run and
# wrong the next).
EXTRACT_TEMPERATURE = 0.0

# Scanned-PDF handling. A scan has ~no extractable text, so the API's own PDF
# rasterisation can render digits too coarsely (a fuzzy 3 reads as a 2). For
# those we rasterise the pages ourselves at the sharpest size the API keeps
# (~1568px long edge) and send them as images. Text-layer PDFs are untouched.
SCAN_TEXT_CHARS_PER_PAGE = 50   # avg chars/page below this ⇒ treat as a scan
SCAN_RENDER_LONG_EDGE_PX = 1568  # Anthropic's max image dimension before downscale
SCAN_MAX_PAGES = 25              # cap pages rasterised (memory/token guard)

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
    # Earnest money deposit (V2 Section 5) — receipt tracking only.
    "emd_amount", "emd_due_date",
]

_PRICE_FIELDS = {"list_price", "sale_price", "emd_amount"}
_DATE_FIELDS = {"contract_date", "closing_date", "emd_due_date"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AINotConfigured(Exception):
    """Raised when no ANTHROPIC_API_KEY is configured."""


class AIExtractionError(Exception):
    """Raised when the model response can't be parsed into fields."""


class AIServiceUnavailable(AIExtractionError):
    """Raised when the AI service times out / is overloaded / is unreachable.

    A subclass of AIExtractionError so existing ``except AIExtractionError``
    callers keep working; callers that want to tell "service is slow, retry"
    apart from "this file was unreadable" can catch this first.
    """


def _client() -> AsyncAnthropic:
    if not settings.ANTHROPIC_API_KEY:
        raise AINotConfigured("ANTHROPIC_API_KEY is not set")
    return AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=EXTRACT_TIMEOUT_SECONDS,
        max_retries=EXTRACT_MAX_RETRIES,
    )


def _pdf_is_scanned(pdf_bytes: bytes) -> bool:
    """True when a PDF has little/no extractable text — i.e. it's a scan/photo.

    A real text-layer contract yields hundreds of characters per page; a scanned
    image yields ~0. On any failure we return False so the caller falls back to
    the native-document path (current behaviour).
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return False
    try:
        pages = doc.page_count or 1
        chars = sum(len(page.get_text("text").strip()) for page in doc)
    except Exception:
        return False
    finally:
        doc.close()
    return chars < SCAN_TEXT_CHARS_PER_PAGE * pages


def _render_pdf_pages_to_pngs(pdf_bytes: bytes) -> list[bytes]:
    """Rasterise PDF pages to PNG bytes, sized so the long edge is ~1568px.

    1568px is the largest dimension Anthropic keeps before it downscales, so this
    hands the model the sharpest legal image — the difference between reading a
    scanned "3" correctly and misreading it as a "2".
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images: list[bytes] = []
    try:
        for i, page in enumerate(doc):
            if i >= SCAN_MAX_PAGES:
                break
            long_edge_pt = max(page.rect.width, page.rect.height) or 612.0
            zoom = max(1.0, min(SCAN_RENDER_LONG_EDGE_PX / long_edge_pt, 4.0))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            images.append(pix.tobytes("png"))
    finally:
        doc.close()
    return images


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
        "- This contract may be a SCAN or photo. Read every number (prices, dates, amounts) one "
        "digit at a time, exactly as printed. Do NOT infer a digit from context or round — a "
        "misread leading digit (e.g. 3 vs 2) changes the price by $100,000. If a digit is truly "
        "illegible, prefer null over a guess.\n"
        "- A purchase contract contains SEVERAL dollar amounts and SEVERAL dates. Match each "
        "value to its field by the label next to it in the document, not by where it appears. "
        "Read the relevant line carefully and copy the figure exactly — do not round or transpose digits.\n"
        "- Dates must be ISO format YYYY-MM-DD.\n"
        "- Prices must be plain numbers with no currency symbol or commas (e.g. 450000).\n"
        "- sale_price is the TOTAL PURCHASE PRICE / total sales price the buyer pays for the "
        "property (the headline contract price). Do NOT confuse it with any other dollar amount "
        "in the contract: loan/financing amount, down payment, earnest money deposit, option fee, "
        "closing-cost credits, seller concessions, or the original list price. Take it from the "
        "purchase-price line specifically.\n"
        "- contract_date is the date the contract was fully signed / executed (the effective or "
        "acceptance date). closing_date is the settlement / closing date. Do not swap them, and do "
        "not use other dates (inspection, financing, or appraisal deadlines) for either.\n"
        "- emd_amount is the earnest money deposit amount; emd_due_date is the date the "
        "earnest money must be delivered (often 'within N days of acceptance' — compute it "
        "from the contract date only if the contract states the day count explicitly).\n"
        "- Emails and phones exactly as written.\n"
        "- Names of parties, trusts, and entities: capture the COMPLETE legal name exactly "
        "as written (e.g. a trust's full name) — never abbreviate or truncate it.\n"
        "- Representation: 'listing_agent' represents the seller; 'selling_agent' represents "
        "the buyer. If the contract explicitly states a party is unrepresented, representing "
        "themselves, or acting as their own agent, set that side's agent name to the party's "
        "own name followed by ' (self-represented)' and use that party's own email/phone for "
        "that agent (seller self-represents -> listing_agent; buyer self-represents -> "
        "selling_agent).\n"
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


async def extract_contract_fields_from_image(
    image_bytes: bytes,
    media_type: str,
    knowledge_rules: list[dict[str, Any]] | None = None,
    brokerage_id: str | None = None,
) -> dict[str, Any]:
    """Extract contract fields from a JPEG or PNG image using vision.

    ``media_type`` should be ``'jpeg'`` or ``'png'`` — the bare type, not the
    full MIME type.  The image is passed as a base64-encoded image block; the
    model reads the photo with vision rather than OCR pre-processing.
    """
    client = _client()
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    anthropic_media_type = f"image/{media_type}"
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=EXTRACT_TEMPERATURE,
            system=_build_system(knowledge_rules or []),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": anthropic_media_type,
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extract the contract fields from this contract image.",
                        },
                    ],
                }
            ],
        )
    except _TRANSIENT_AI_ERRORS as exc:
        raise AIServiceUnavailable(f"Anthropic unavailable: {exc}") from exc
    except Exception as exc:
        raise AIExtractionError(f"Anthropic API error: {exc}") from exc
    await sb.log_ai_usage(brokerage_id, "extract_image", MODEL, _usage_dict(response.usage))
    raw = "".join(block.text for block in response.content if block.type == "text")
    data = _parse_json(raw)
    return {key: _clean(key, data.get(key)) for key in CONTRACT_FIELDS}


async def interpret_pending_reply(
    current_fields: dict[str, Any], message: str
) -> tuple[dict[str, Any], str]:
    """Interpret an agent's reply during the pending-confirmation flow.

    The agent has been shown an extracted-contract summary and replied with
    something that isn't a plain YES/NO. They might be supplying a corrected
    value ("price is 450k"), questioning one ("are you sure that's the price?"),
    flagging one as wrong without giving the value ("the price is incorrect"),
    or saying something unclear.

    Returns ``(updates, reply)``:
      - ``updates``: cleaned field corrections to apply (empty if none stated).
      - ``reply``: a conversational message to send when no concrete correction
        was given (empty string when ``updates`` is populated — the caller then
        renders the refreshed summary instead).
    """
    client = _client()
    keys = ", ".join(CONTRACT_FIELDS)
    prompt = (
        "You are Penny, a real estate transaction coordinator. You extracted a "
        "contract and showed the agent this summary of fields. They've replied — "
        "work out what they mean and respond.\n\n"
        f"Current extracted fields (JSON):\n{json.dumps(current_fields, indent=2)}\n\n"
        f'The agent\'s reply: "{message}"\n\n'
        'Return ONLY a JSON object: {"updates": {...}, "reply": "..."}\n'
        "Rules:\n"
        f"- Field keys you may set in \"updates\": {keys}.\n"
        "- Put a field in \"updates\" ONLY if the agent stated a NEW concrete value "
        "for it. Dates as YYYY-MM-DD; prices as plain numbers (no $ or commas). "
        "Never invent or guess a value — if they didn't give one, use {}.\n"
        "- \"reply\": a short, warm, plain-text message (no markdown).\n"
        "    * If \"updates\" is non-empty, set \"reply\" to \"\" (the app shows the "
        "updated summary itself).\n"
        "    * If the agent disputes or questions a field WITHOUT giving the new "
        "value (e.g. \"are you sure that's the price?\", \"the price is wrong\"), "
        "acknowledge it, state the CURRENT value you have for that field, and ask "
        "them for the correct value. Do NOT repeat the whole summary.\n"
        "    * If it's unclear, briefly ask what they'd like to change, or note they "
        "can reply YES if everything looks right.\n"
    )
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=500,
            temperature=EXTRACT_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
        )
    except _TRANSIENT_AI_ERRORS as exc:
        raise AIServiceUnavailable(f"Anthropic unavailable: {exc}") from exc
    except Exception as exc:
        raise AIExtractionError(f"Anthropic API error: {exc}") from exc

    raw = "".join(block.text for block in response.content if block.type == "text")
    try:
        parsed = _parse_json(raw)
    except AIExtractionError:
        return {}, ""

    # Keep only fields that cleaned to a real value. A correction that fails to
    # parse (e.g. a date the model didn't return as YYYY-MM-DD) must NOT be
    # written back as None — that would erase the value the agent is correcting.
    raw_updates = parsed.get("updates") if isinstance(parsed.get("updates"), dict) else {}
    cleaned = {k: _clean(k, v) for k, v in raw_updates.items() if k in CONTRACT_FIELDS}
    updates = {k: v for k, v in cleaned.items() if v is not None}

    reply = parsed.get("reply")
    reply = reply.strip() if isinstance(reply, str) else ""
    return updates, reply


async def extract_contract_fields(
    pdf_bytes: bytes,
    knowledge_rules: list[dict[str, Any]] | None = None,
    brokerage_id: str | None = None,
) -> dict[str, Any]:
    """Extract structured fields from a contract PDF.

    A text-layer PDF is sent directly to the Anthropic API as a base64-encoded
    document (vision-capable, handles AcroForm / flattened forms). A SCANNED PDF
    (no text layer) is instead rasterised to high-resolution page images here, so
    the model reads crisp digits rather than the API's coarser PDF rendering —
    which fixes single-digit OCR misreads (e.g. a price of 315000 read as 215000).
    """
    client = _client()
    usage_label = "extract_pdf"

    content: list[dict[str, Any]] | None = None
    if _pdf_is_scanned(pdf_bytes):
        try:
            page_images = _render_pdf_pages_to_pngs(pdf_bytes)
        except Exception as exc:  # noqa: BLE001 — fall back to the document path
            logger.warning("Scanned-PDF rasterisation failed, using document path: %r", exc)
            page_images = []
        if page_images:
            usage_label = "extract_pdf_scanned"
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.standard_b64encode(img).decode("utf-8"),
                    },
                }
                for img in page_images
            ]
            content.append({
                "type": "text",
                "text": (
                    "These images are the pages, in order, of one SCANNED real estate "
                    "purchase contract. Read the digits carefully and extract the contract fields."
                ),
            })

    if content is None:  # text-layer PDF (or rasterisation unavailable)
        content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(pdf_bytes).decode("utf-8"),
                },
            },
            {"type": "text", "text": "Extract the contract fields from this document."},
        ]

    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=EXTRACT_TEMPERATURE,
            system=_build_system(knowledge_rules or []),
            messages=[{"role": "user", "content": content}],
        )
    except _TRANSIENT_AI_ERRORS as exc:
        raise AIServiceUnavailable(f"Anthropic unavailable: {exc}") from exc
    except Exception as exc:
        raise AIExtractionError(f"Anthropic API error: {exc}") from exc
    await sb.log_ai_usage(brokerage_id, usage_label, MODEL, _usage_dict(response.usage))
    raw = "".join(block.text for block in response.content if block.type == "text")
    data = _parse_json(raw)
    return {key: _clean(key, data.get(key)) for key in CONTRACT_FIELDS}
