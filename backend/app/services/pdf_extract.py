"""Contract PDF text extraction with page scoring (PRD §8.3).

Contracts can be long; the signal (parties, prices, dates, contacts) usually
lives on a handful of pages. We score every page, keep the highest-signal ones
up to a character budget, then hand that text to the model — keeping prompts
small and focused.
"""

import re

import fitz  # PyMuPDF

# Scoring weights (PRD §8.3).
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_DOLLAR_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
_KEYWORDS = (
    "buyer", "seller", "purchase price", "earnest", "closing", "option",
    "contingency", "financing", "lender", "title", "inspection", "escrow",
    "property", "address", "agent", "broker", "commission", "disclosure",
)

MAX_PAGES = 15
MAX_CHARS = 45_000


def score_page(text: str) -> int:
    if not text.strip():
        return 0
    low = text.lower()
    score = 0
    score += 15 * len(_EMAIL_RE.findall(text))
    score += 5 * len(_DOLLAR_RE.findall(text))
    score += 8 * len(_DATE_RE.findall(text))
    score += 4 * sum(low.count(k) for k in _KEYWORDS)
    return score


def extract_pdf_text(pdf_bytes: bytes, max_chars: int = MAX_CHARS) -> str:
    """Return the highest-signal pages concatenated, in original page order."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text()
            pages.append({"num": i + 1, "text": text, "score": score_page(text)})
    finally:
        doc.close()

    pages.sort(key=lambda p: p["score"], reverse=True)

    selected: list[dict] = []
    chars = 0
    for p in pages[:MAX_PAGES]:
        if chars + len(p["text"]) > max_chars:
            continue
        selected.append(p)
        chars += len(p["text"])

    selected.sort(key=lambda p: p["num"])
    return "\n\n".join(f"[Page {p['num']}]\n{p['text']}" for p in selected)


def pdf_page_count(pdf_bytes: bytes) -> int:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return doc.page_count
    finally:
        doc.close()
