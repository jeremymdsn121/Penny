"""Anthropic-backed brand/style rule extraction for the knowledge base.

A brokerage uploads a style reference — a letterhead, a sample letter, an email
template — and Sloane proposes concrete, reusable style rules from it. The rules
land in ``knowledge_rules`` as *unconfirmed* (the admin reviews them) and, once
confirmed, are injected into Sloane's document/email prompts so she stays on
brand.

Input handling by type:
  - PDF / images  → sent to Anthropic as native document/image blocks (vision),
                    the same approach as contract extraction.
  - DOCX          → text (with heading markers) is extracted via python-docx and
                    sent as plain text, since the API can't read .docx natively.

Never fabricates: the model is told to omit anything the document doesn't show.
"""

import io
import json
import re
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings

MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 1500

_IMAGE_TYPES = {
    "image/png": "image/png",
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/webp": "image/webp",
    "image/gif": "image/gif",
}
_DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Suggested rule buckets — the model may use these or sensible alternatives.
_CATEGORIES = [
    "tone",
    "greeting",
    "closing",
    "signature",
    "letterhead",
    "headings",
    "formatting",
    "contact_block",
    "terminology",
]


class StyleNotConfigured(Exception):
    """Raised when no ANTHROPIC_API_KEY is configured."""


class StyleExtractionError(Exception):
    """Raised when the upload can't be read or the model response can't be parsed."""


def infer_kind(content_type: str | None, filename: str | None) -> str | None:
    """Classify an upload as 'pdf' | 'image' | 'docx', or None if unsupported."""
    ct = (content_type or "").lower().split(";")[0].strip()
    name = (filename or "").lower()
    if ct in ("application/pdf", "application/x-pdf") or name.endswith(".pdf"):
        return "pdf"
    if ct in _IMAGE_TYPES or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return "image"
    if ct == _DOCX_TYPE or name.endswith(".docx"):
        return "docx"
    return None


def _client() -> AsyncAnthropic:
    if not settings.ANTHROPIC_API_KEY:
        raise StyleNotConfigured("ANTHROPIC_API_KEY is not set")
    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


def _docx_to_text(file_bytes: bytes) -> str:
    """Extract paragraph text from a .docx, tagging heading/title styles."""
    try:
        from docx import Document
    except ImportError as exc:
        raise StyleExtractionError(
            "python-docx not installed — run `pip install python-docx`"
        ) from exc
    try:
        doc = Document(io.BytesIO(file_bytes))
    except Exception as exc:
        raise StyleExtractionError(f"Could not read .docx file: {exc}") from exc

    lines: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name if para.style else "") or ""
        low = style.lower()
        if low.startswith("heading") or low == "title":
            lines.append(f"[{style}] {text}")
        else:
            lines.append(text)
    extracted = "\n".join(lines).strip()
    if not extracted:
        raise StyleExtractionError("The .docx file has no readable text.")
    return extracted


def _build_system() -> str:
    cats = ", ".join(_CATEGORIES)
    return (
        "You are Sloane, a real estate transaction coordinator assistant. A "
        "brokerage has uploaded a brand/style reference document (e.g. a "
        "letterhead, a sample letter, or an email template). Your job is to "
        "identify concrete, reusable style guidelines the brokerage applies, so "
        "you can match their voice and formatting when you later generate letters "
        "and emails.\n\n"
        f"Group each guideline under a short category. Suggested categories: {cats}. "
        "You may use other categories if they fit better.\n\n"
        "Return ONLY a JSON array of objects with exactly these keys: "
        '"category" and "rule". Example:\n'
        '[{"category": "signature", "rule": "Sign off as \\"The Summit Realty Team\\"."}]\n\n'
        "Strict rules:\n"
        "- Each rule must be a short, actionable guideline grounded in what the "
        "document actually shows. NEVER guess, infer, or fabricate.\n"
        "- If the document shows nothing useful for a category, omit that category.\n"
        "- Capture concrete specifics (exact sign-off wording, color names/hex, "
        "font names, heading capitalization, contact block layout) where visible.\n"
        "- Return only the JSON array — no prose, no markdown fences."
    )


def _user_content(kind: str, file_bytes: bytes, content_type: str | None) -> list[dict]:
    instruction = {
        "type": "text",
        "text": "Propose the brokerage's style rules from this document.",
    }
    if kind == "pdf":
        import base64

        return [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(file_bytes).decode("utf-8"),
                },
            },
            instruction,
        ]
    if kind == "image":
        import base64

        media_type = _IMAGE_TYPES.get(
            (content_type or "").lower().split(";")[0].strip(), "image/png"
        )
        return [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(file_bytes).decode("utf-8"),
                },
            },
            instruction,
        ]
    # docx
    text = _docx_to_text(file_bytes)
    return [
        {"type": "text", "text": f"Document contents:\n\n{text}"},
        instruction,
    ]


def _parse_rules(text: str) -> list[dict[str, str]]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise StyleExtractionError("Model did not return a JSON array.")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise StyleExtractionError(f"Could not parse model JSON: {exc}") from exc

    if not isinstance(data, list):
        raise StyleExtractionError("Model response was not a JSON array.")

    rules: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "")).strip().lower() or "general"
        rule = str(item.get("rule", "")).strip()
        if not rule:
            continue
        key = (category, rule.lower())
        if key in seen:
            continue
        seen.add(key)
        rules.append({"category": category, "rule": rule})
    return rules[:25]  # guard against runaway output


async def extract_style_rules(
    file_bytes: bytes, content_type: str | None, filename: str | None
) -> list[dict[str, str]]:
    """Propose style rules from an uploaded brand/style document.

    Returns a list of ``{"category", "rule"}`` dicts (possibly empty if the
    document yields nothing useful). Raises StyleNotConfigured if the API key is
    missing, or StyleExtractionError if the file or response can't be processed.
    """
    kind = infer_kind(content_type, filename)
    if kind is None:
        raise StyleExtractionError("Unsupported file type — upload a PDF, image, or .docx.")

    client = _client()
    content = _user_content(kind, file_bytes, content_type)
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_build_system(),
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        raise StyleExtractionError(f"Anthropic API error: {exc}") from exc

    raw = "".join(block.text for block in response.content if block.type == "text")
    return _parse_rules(raw)
