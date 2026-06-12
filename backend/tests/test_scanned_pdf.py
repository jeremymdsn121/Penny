"""Scanned PDFs are rasterised to sharp images before extraction.

A scanned contract (no text layer) read its price wrong by one digit
(315000 -> 215000) because the API rendered the scan too coarsely. We now
detect a scan and send high-res page images. Text-layer PDFs keep the native
document path.
"""

import fitz

from app.services import ai_extract


def _text_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Real Estate Purchase Contract. Purchase Price $315,000.\n" * 20)
    return doc.tobytes()


def _scanned_pdf() -> bytes:
    # A page with graphics but no text layer — stands in for a scan.
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(40, 40, 560, 760), color=(0, 0, 0), width=2)
    return doc.tobytes()


def test_text_layer_pdf_is_not_scanned():
    assert ai_extract._pdf_is_scanned(_text_pdf()) is False


def test_no_text_pdf_is_scanned():
    assert ai_extract._pdf_is_scanned(_scanned_pdf()) is True


def test_bad_bytes_fall_back_to_not_scanned():
    # Unparseable input must not raise — caller falls back to the document path.
    assert ai_extract._pdf_is_scanned(b"not a pdf") is False


def test_render_produces_png_pages():
    pngs = ai_extract._render_pdf_pages_to_pngs(_scanned_pdf())
    assert len(pngs) == 1
    assert pngs[0][:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic number


# --- end-to-end content routing -------------------------------------------- #

class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Usage:
    input_tokens = 1
    output_tokens = 1


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()


class _Messages:
    def __init__(self, store):
        self._store = store

    async def create(self, **kwargs):
        self._store.update(kwargs)
        return _Resp('{"sale_price": "315000"}')


class _Client:
    def __init__(self, store):
        self.messages = _Messages(store)


def _patch(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(ai_extract, "_client", lambda: _Client(captured))

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(ai_extract.sb, "log_ai_usage", _noop)
    return captured


def _content_block_types(captured: dict) -> list[str]:
    return [b["type"] for b in captured["messages"][0]["content"]]


async def test_scanned_pdf_sends_image_blocks(monkeypatch):
    captured = _patch(monkeypatch)
    await ai_extract.extract_contract_fields(_scanned_pdf())
    types = _content_block_types(captured)
    assert "image" in types
    assert "document" not in types


async def test_text_pdf_sends_document_block(monkeypatch):
    captured = _patch(monkeypatch)
    await ai_extract.extract_contract_fields(_text_pdf())
    types = _content_block_types(captured)
    assert "document" in types
    assert "image" not in types
