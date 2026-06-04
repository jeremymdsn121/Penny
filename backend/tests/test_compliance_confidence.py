"""Tests for HL5 — AI compliance confidence + the feedback log."""

import pytest
from fastapi import HTTPException

from app.api.v1.routes import transactions as tx_routes
from app.services import compliance as c


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


def test_normalize_confidence():
    assert c.normalize_confidence("high") == "high"
    assert c.normalize_confidence("MEDIUM") == "medium"
    assert c.normalize_confidence(" Low ") == "low"
    # anything missing or unrecognized is conservatively treated as low
    assert c.normalize_confidence(None) == "low"
    assert c.normalize_confidence("") == "low"
    assert c.normalize_confidence("very sure") == "low"


async def test_review_threads_confidence_into_findings(monkeypatch):
    state, rules = c.get_ruleset("TX")
    rid = rules[0]["id"]
    # The model reports a 'missing' item with low confidence + a satisfied one.
    monkeypatch.setattr(
        c,
        "ai_review_contract",
        _async_return(
            [
                {"rule_id": rid, "status": "missing", "confidence": "low", "note": "n/a"},
                {"rule_id": rules[1]["id"], "status": "satisfied", "confidence": "high"},
            ]
        ),
    )
    tx = {"state": "TX", "address": "1 A St", "buyer_name": "B", "seller_name": "S",
          "sale_price": 100, "contract_date": "2026-01-01", "closing_date": "2026-02-01",
          "contract_pdf_url": "x.pdf"}
    result = await c.review_transaction(tx, pdf_bytes=b"%PDF-fake")

    finding = next(f for f in result["findings"] if f.get("rule_id") == rid)
    assert finding["confidence"] == "low"
    item = next(i for i in result["checklist"] if i["id"] == rid)
    assert item["ai_confidence"] == "low"
    assert item["ai_status"] == "missing"


async def test_compliance_feedback_rejects_bad_verdict(monkeypatch):
    monkeypatch.setattr(tx_routes.sb, "get_transaction", _async_return({"id": "t1"}))
    body = tx_routes.ComplianceFeedbackIn(rule_id="R1", human_verdict="maybe")
    with pytest.raises(HTTPException) as exc:
        await tx_routes.compliance_feedback("t1", body, brokerage={"id": "b1"})
    assert exc.value.status_code == 400


async def test_compliance_feedback_records_verdict(monkeypatch):
    monkeypatch.setattr(tx_routes.sb, "get_transaction", _async_return({"id": "t1"}))
    captured = {}

    async def _insert(row):
        captured.update(row)
        return {**row, "id": "fb1"}

    monkeypatch.setattr(tx_routes.sb, "insert_compliance_feedback", _insert)
    body = tx_routes.ComplianceFeedbackIn(
        rule_id="R1", human_verdict="Incorrect", ai_status="missing", ai_confidence="low"
    )
    res = await tx_routes.compliance_feedback("t1", body, brokerage={"id": "b1"})
    assert res["id"] == "fb1"
    assert captured["human_verdict"] == "incorrect"  # normalized lower-case
    assert captured["brokerage_id"] == "b1"
    assert captured["transaction_id"] == "t1"


async def test_compliance_feedback_404_when_tx_missing(monkeypatch):
    monkeypatch.setattr(tx_routes.sb, "get_transaction", _async_return(None))
    body = tx_routes.ComplianceFeedbackIn(rule_id="R1", human_verdict="correct")
    with pytest.raises(HTTPException) as exc:
        await tx_routes.compliance_feedback("t1", body, brokerage={"id": "b1"})
    assert exc.value.status_code == 404
