"""Extraction decodes deterministically (temperature 0).

Guards the accuracy fix: the API default of 1.0 sampled randomly, so a typed
contract could read right one run and wrong the next. These assert each
extraction call pins temperature to 0.
"""

from app.services import ai_extract


class _Block:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _Usage:
    input_tokens = 1
    output_tokens = 1


class _Resp:
    def __init__(self, text: str):
        self.content = [_Block(text)]
        self.usage = _Usage()


class _Messages:
    def __init__(self, store: dict):
        self._store = store

    async def create(self, **kwargs):
        self._store.update(kwargs)
        return _Resp('{"sale_price": "450000"}')


class _Client:
    def __init__(self, store: dict):
        self.messages = _Messages(store)


def _patch(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(ai_extract, "_client", lambda: _Client(captured))

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(ai_extract.sb, "log_ai_usage", _noop)
    return captured


async def test_pdf_extraction_uses_temperature_zero(monkeypatch):
    captured = _patch(monkeypatch)
    await ai_extract.extract_contract_fields(b"%PDF-1.4 fake")
    assert captured.get("temperature") == 0.0


async def test_image_extraction_uses_temperature_zero(monkeypatch):
    captured = _patch(monkeypatch)
    await ai_extract.extract_contract_fields_from_image(b"\xff\xd8\xff", "jpeg")
    assert captured.get("temperature") == 0.0
