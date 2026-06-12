"""Contract extraction bounds its Anthropic call and names transient failures.

A slow/overloaded Anthropic must surface as AIServiceUnavailable ("service slow,
retry") rather than hanging or looking like an unreadable contract — while a
genuine non-transient failure still raises plain AIExtractionError.
"""

import httpx
import pytest
from anthropic import APITimeoutError, OverloadedError

from app.services import ai_extract


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


class _Messages:
    def __init__(self, exc):
        self._exc = exc

    async def create(self, **kwargs):
        raise self._exc


class _Client:
    def __init__(self, exc):
        self.messages = _Messages(exc)


def _patch_client(monkeypatch, exc):
    monkeypatch.setattr(ai_extract, "_client", lambda: _Client(exc))


async def test_pdf_transient_error_is_service_unavailable(monkeypatch):
    _patch_client(monkeypatch, OverloadedError("ov", response=httpx.Response(529, request=_req()), body=None))
    with pytest.raises(ai_extract.AIServiceUnavailable):
        await ai_extract.extract_contract_fields(b"%PDF-1.4 fake")


async def test_image_timeout_is_service_unavailable(monkeypatch):
    _patch_client(monkeypatch, APITimeoutError(_req()))
    with pytest.raises(ai_extract.AIServiceUnavailable):
        await ai_extract.extract_contract_fields_from_image(b"\xff\xd8\xff", "jpeg")


async def test_pdf_other_error_is_plain_extraction_error(monkeypatch):
    # A non-transient failure must NOT be reported as a retryable service issue.
    _patch_client(monkeypatch, ValueError("malformed response"))
    with pytest.raises(ai_extract.AIExtractionError) as ei:
        await ai_extract.extract_contract_fields(b"%PDF-1.4 fake")
    assert not isinstance(ei.value, ai_extract.AIServiceUnavailable)
