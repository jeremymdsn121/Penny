"""Tests for the CSV export builders (the SkySlope/Dotloop round-trip path).

The deal export must re-import into Penny cleanly — that's the whole point of
using the import headers — so the strongest test runs an export back through the
importer and checks the data survives.
"""

import csv
import io

from app.services import csv_import as ci


def test_export_uses_import_headers_plus_context():
    csv_text = ci.export_transactions_csv([], {})
    header = next(csv.reader(io.StringIO(csv_text)))
    # Every importable column is present, in template order, before the extras.
    assert header[: len(ci.TEMPLATE_COLUMNS)] == ci.TEMPLATE_COLUMNS
    assert "compliance_status" in header and "checklist_pct" in header


def test_export_round_trips_back_into_the_importer():
    txs = [
        {
            "id": "t1", "address": "123 Main St", "city": "Austin", "state": "TX",
            "buyer_name": "Jane Buyer", "seller_name": "John Seller",
            "sale_price": 445000, "closing_date": "2026-07-15",
            "stage": "under_contract", "emd_received": True,
            "compliance_status": "approved",
        }
    ]
    csv_text = ci.export_transactions_csv(txs, {"t1": 80})

    preview = ci.build_preview(csv_text.encode("utf-8"), existing_addresses=set())
    assert preview["summary"]["ready"] == 1
    row = preview["rows"][0]
    assert row["importable"] is True
    assert row["data"]["address"] == "123 Main St"
    assert row["data"]["sale_price"] == 445000.0
    assert row["data"]["stage"] == "under_contract"
    # Read-only context columns aren't import fields — they're harmlessly ignored.
    assert "compliance_status" in preview["unmapped_columns"]


def test_export_renders_bool_and_none_safely():
    txs = [{"id": "t1", "address": "9 Elm", "emd_received": False, "closed_at": None}]
    csv_text = ci.export_transactions_csv(txs)
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert rows[0]["emd_received"] == ""        # False → blank
    assert rows[0]["closed_at"] == ""           # None → blank
    assert rows[0]["address"] == "9 Elm"


def test_document_manifest_only_lists_present_docs():
    txs = [
        {"address": "1 A St", "contract_pdf_url": "https://x/c.pdf",
         "emd_receipt_document_url": "https://x/r.pdf"},
        {"address": "2 B St", "contract_pdf_url": "", "emd_receipt_document_url": None},
    ]
    rows = ci.document_manifest_rows(txs)
    assert len(rows) == 2  # only the two present docs on the first deal
    assert {r["document"] for r in rows} == {"Contract", "EMD receipt"}
    assert all(r["address"] == "1 A St" for r in rows)

    csv_text = ci.export_documents_csv(rows)
    assert "Contract" in csv_text and "https://x/c.pdf" in csv_text


def test_activity_export_columns():
    rows = [{"address": "1 A St", "at": "2026-06-13T10:00:00+00:00",
             "kind": "stage_change", "title": "Moved to pending",
             "detail": None, "actor": "You", "via": "web"}]
    csv_text = ci.export_activity_csv(rows)
    header = next(csv.reader(io.StringIO(csv_text)))
    assert header == ["address", "at", "kind", "title", "detail", "actor", "via"]
    assert "Moved to pending" in csv_text
