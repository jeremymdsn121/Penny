"""Tests for the pure helpers in app.services.doc_routing (Autonomy doc-routing)."""

from app.services import doc_routing as dr


def test_resolve_recipient_emails_dedupes_case_insensitively():
    tx = {
        "title_email": "Title@Escrow.com",
        "lender_email": "lender@bank.com",
        "buyer_email": "title@escrow.com",  # same address as title, different case
        "seller_email": "",  # empty -> skipped
    }
    out = dr.resolve_recipient_emails(tx, ["title", "lender", "buyer", "seller", "tc"])
    # title kept first; lender kept; buyer is a case-insensitive dup -> dropped;
    # seller empty -> dropped; tc has no email field value -> dropped.
    assert out == ["Title@Escrow.com", "lender@bank.com"]


def test_resolve_recipient_emails_ignores_unknown_roles():
    assert dr.resolve_recipient_emails({"buyer_email": "b@x.com"}, ["bogus", "buyer"]) == [
        "b@x.com"
    ]


def test_document_filename_sanitizes_address():
    name = dr._document_filename({"address": "123 Main St, #4/A"}, "contract")
    assert name.endswith(" - contract.pdf")
    for bad in (",", "/", "#"):
        assert bad not in name


def test_document_path_is_contract_only():
    assert dr._document_path({"contract_pdf_url": "x.pdf"}, "contract") == "x.pdf"
    assert dr._document_path({"contract_pdf_url": ""}, "contract") is None
    assert dr._document_path({"contract_pdf_url": "x.pdf"}, "other") is None


def test_validation_constants_are_the_real_stages_not_deadline_labels():
    assert dr.VALID_STAGES == {"under_contract", "pending", "closed", "cancelled"}
    assert dr.VALID_DOCUMENT_SOURCES == {"contract"}
    assert {"title", "lender", "buyer", "seller", "tc"} <= dr.VALID_ROLES
