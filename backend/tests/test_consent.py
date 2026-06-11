"""HMAC consent-link tests for app.services.consent (V2 Section 6).

Secret-agnostic: we assert the round-trip and tamper-resistance rather than a
fixed digest, so the tests hold regardless of which secret is configured.
"""

from app.services import consent


def test_token_roundtrip_and_email_case_insensitive():
    token = consent.make_token("tx1", "buyer", "Buyer@Example.com")
    # email is lower-cased inside the payload, so a differently-cased email verifies.
    assert consent.verify_token("tx1", "buyer", "buyer@example.com", token)


def test_token_rejects_mismatches():
    token = consent.make_token("tx1", "buyer", "buyer@example.com")
    assert not consent.verify_token("tx1", "seller", "buyer@example.com", token)  # role
    assert not consent.verify_token("tx2", "buyer", "buyer@example.com", token)  # transaction
    assert not consent.verify_token("tx1", "buyer", "other@example.com", token)  # email
    assert not consent.verify_token("tx1", "buyer", "buyer@example.com", token + "x")  # tampered
    assert not consent.verify_token("tx1", "buyer", "buyer@example.com", "")  # empty


def test_consent_link_shape():
    link = consent.consent_link("tx1", "buyer", "buyer@example.com")
    assert "/api/v1/consent/tx1/buyer?" in link
    assert "token=" in link
    assert "email=" in link
