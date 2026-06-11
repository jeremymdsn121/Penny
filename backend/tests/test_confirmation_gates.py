"""Confirmation gates — the load-bearing safety invariant.

Hard rule (CLAUDE.md): every outward action that sends, books, decides, or
publishes must require an explicit ``confirmed=true`` and have no bypass flag.
These assert each gated endpoint refuses to act without it. They call the route
functions directly (no network) — the gate is checked before any side effect, so
no stubs are needed except where an ownership/autonomy lookup runs first.
"""

import pytest
from fastapi import HTTPException

from app.api.v1.routes import appointments as appt_routes
from app.api.v1.routes import deadlines as deadline_routes
from app.api.v1.routes import doc_routing as dr_routes
from app.api.v1.routes import email as email_routes
from app.api.v1.routes import listings as listing_routes
from app.api.v1.routes import transactions as tx_routes

BROK = {"id": "b1", "name": "Test"}


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


async def _assert_gate(coro):
    with pytest.raises(HTTPException) as exc:
        await coro
    assert exc.value.status_code == 400
    assert "onfirm" in exc.value.detail  # "Confirmation required …"


async def test_emd_received_requires_confirmation():
    body = tx_routes.EmdReceivedIn(received=True, confirmed=False)
    await _assert_gate(tx_routes.set_emd_received("t1", body, brokerage=BROK))


async def test_compliance_decision_requires_confirmation():
    body = tx_routes.ComplianceDecisionIn(status="approved", confirmed=False)
    await _assert_gate(tx_routes.compliance_decision("t1", body, brokerage=BROK))


async def test_docusign_send_requires_confirmation():
    body = tx_routes.DocuSignSendIn(signers=[], confirmed=False)
    await _assert_gate(tx_routes.docusign_send("t1", body, brokerage=BROK))


async def test_send_document_requires_confirmation():
    body = tx_routes.SendDocumentIn(
        to_emails=["a@b.com"], subject="s", body="b", confirmed=False
    )
    await _assert_gate(tx_routes.send_document("t1", body, brokerage=BROK))


async def test_doc_routing_send_requires_confirmation():
    body = dr_routes.SendIn(confirmed=False)
    await _assert_gate(
        dr_routes.send_pending("r1", body, brokerage=BROK, user={"id": "u1"})
    )


async def test_pending_reply_send_requires_confirmation():
    body = email_routes.SendPendingReplyIn(confirmed=False)
    await _assert_gate(
        email_routes.send_pending_reply("r1", body, brokerage=BROK, user={"id": "u1"})
    )


async def test_listing_push_requires_confirmation():
    body = listing_routes.ListingPush(confirmed=False)
    await _assert_gate(listing_routes.push("l1", body, brokerage=BROK))


async def test_deadline_notify_parties_requires_confirmation():
    body = deadline_routes.NotifyPartiesIn(confirmed=False)
    await _assert_gate(
        deadline_routes.notify_parties("d1", body, brokerage=BROK)
    )


async def test_appointment_book_requires_confirmation(monkeypatch):
    # book() resolves ownership and checks autonomy before the gate, so stub a
    # valid, non-autonomous deal — then confirmed=False must still 400.
    monkeypatch.setattr(appt_routes.sb, "get_transaction", _async_return({"id": "t1"}))
    monkeypatch.setattr(appt_routes.sb, "get_task_autonomy", _async_return([]))
    body = appt_routes.BookIn(
        transaction_id="t1", scheduled_at="2026-06-10T14:00:00-05:00", confirmed=False
    )
    await _assert_gate(appt_routes.book(body, brokerage=BROK))


async def test_appointment_book_allowed_when_scheduling_autonomous(monkeypatch):
    # The one documented exception: an autonomous 'scheduling' task lets booking
    # proceed without an explicit confirm. Prove the gate yields, then stop at the
    # next external step so we don't make real calls.
    monkeypatch.setattr(appt_routes.sb, "get_transaction", _async_return({"id": "t1", "state": "TX"}))
    monkeypatch.setattr(
        appt_routes.sb, "get_task_autonomy",
        _async_return([{"task_id": "scheduling", "autonomous": True}]),
    )

    async def _boom(*a, **k):
        raise AssertionError("reached calendar create — past the gate, as intended")

    monkeypatch.setattr(appt_routes, "_resolve_account", _async_return(None))
    monkeypatch.setattr(appt_routes.calendar_provider, "create_event", _boom)
    body = appt_routes.BookIn(
        transaction_id="t1", scheduled_at="2026-06-10T14:00:00-05:00", confirmed=False
    )
    with pytest.raises(AssertionError):
        await appt_routes.book(body, brokerage=BROK)
