"""Tests for the deterministic parts of app.services.compliance: ruleset
selection and the structural (record-only) checks. The AI contract pass needs a
live key and is exercised manually."""

import datetime as dt

from app.services import compliance as c


def test_get_ruleset_covered_state_is_case_insensitive():
    state, rules = c.get_ruleset("tx")
    assert state == "TX"
    assert isinstance(rules, list) and rules


def test_get_ruleset_falls_back_to_default():
    assert c.get_ruleset("ZZ")[0] == "DEFAULT"
    assert c.get_ruleset(None)[0] == "DEFAULT"
    assert c.get_ruleset("")[0] == "DEFAULT"


def test_review_ruleset_always_includes_execution_audit():
    # The execution-completeness audit (signatures/initials/dates/addenda) must
    # run in EVERY state — the state-specific rulesets historically omitted it.
    exec_ids = {r["id"] for r in c.EXECUTION_RULES}
    assert exec_ids  # sanity
    for state in [None, "DEFAULT", "ZZ", *c.DETAILED_RULESET_STATES]:
        _, rules = c.review_ruleset(state)
        ids = {r["id"] for r in rules}
        assert exec_ids <= ids, f"{state} review is missing execution rules"
        assert any(r["category"] == "Execution" for r in rules)


def test_review_ruleset_does_not_duplicate_rule_ids():
    for state in [None, "TX", "FL", "CA", "NY", "SC"]:
        _, rules = c.review_ruleset(state)
        ids = [r["id"] for r in rules]
        assert len(ids) == len(set(ids)), f"{state} has duplicate rule ids"


def test_structural_checks_flag_missing_core_fields():
    findings = c.run_structural_checks({})
    msgs = [f["message"] for f in findings]
    assert any("address" in m.lower() for m in msgs)
    assert any("Buyer name is missing" in m for m in msgs)
    assert any("Seller name is missing" in m for m in msgs)
    assert all(f["source"] == "structural" for f in findings)


def test_structural_checks_catch_closing_before_contract():
    today = dt.date.today()
    tx = {
        "address": "1 A St",
        "state": "TX",
        "buyer_name": "B",
        "seller_name": "S",
        "sale_price": 100,
        "contract_date": (today + dt.timedelta(days=10)).isoformat(),
        "closing_date": (today + dt.timedelta(days=1)).isoformat(),  # before contract
        "contract_pdf_url": "x.pdf",
        "stage": "under_contract",
    }
    msgs = [f["message"] for f in c.run_structural_checks(tx)]
    assert any("Closing date is before the contract date" in m for m in msgs)


def test_structural_checks_clean_transaction_has_no_findings():
    today = dt.date.today()
    tx = {
        "address": "1 A St",
        "state": "TX",
        "buyer_name": "B",
        "seller_name": "S",
        "sale_price": 100,
        "contract_date": today.isoformat(),
        "closing_date": (today + dt.timedelta(days=30)).isoformat(),
        "contract_pdf_url": "x.pdf",
        "stage": "under_contract",
    }
    assert c.run_structural_checks(tx) == []
