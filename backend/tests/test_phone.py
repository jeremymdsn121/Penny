"""Tests for the WhatsApp/SMS helper functions (phone normalization, media
classification, pending-reply intent)."""

import pytest

from app.api.v1.routes import whatsapp as wa


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("4054139444", "+14054139444"),       # 10 digits -> assume US
        ("+4054139444", "+14054139444"),       # stray + on a 10-digit US number
        ("(405) 413-9444", "+14054139444"),    # formatting stripped
        ("14054139444", "+14054139444"),        # 11 digits with country code
        ("+14054139444", "+14054139444"),        # already E.164
        ("whatsapp:+14054139444", "+14054139444"),  # scheme stripped
        ("+447911123456", "+447911123456"),     # international preserved
    ],
)
def test_normalise_phone(raw, expected):
    assert wa._normalise_phone(raw) == expected


def test_strip_scheme():
    assert wa._strip_scheme("whatsapp:+15551234567") == "+15551234567"
    assert wa._strip_scheme("+15551234567") == "+15551234567"


def test_is_contract_media():
    assert wa._is_contract_media("application/pdf")
    assert wa._is_contract_media("image/jpeg")
    assert wa._is_contract_media("image/heic")
    assert not wa._is_contract_media("audio/ogg")
    assert not wa._is_contract_media("text/plain")


def test_classify_pending_reply():
    assert wa._classify_pending_reply("Yes") == "confirm"
    assert wa._classify_pending_reply("create it") == "confirm"
    assert wa._classify_pending_reply("no") == "cancel"
    assert wa._classify_pending_reply("never mind") == "cancel"
    assert wa._classify_pending_reply("The price should be 500k") == "correction"
