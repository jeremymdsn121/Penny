"""Tenant scoping — the other load-bearing invariant.

The backend uses the Supabase service-role key, which BYPASSES row-level
security, so route-level brokerage scoping is the only thing stopping one
brokerage from reading or mutating another's data. Nested resources must verify
ownership through their parent transaction's brokerage_id. These assert that a
lookup miss (the shape a cross-tenant id produces, since the scoped query
returns nothing) yields 404, never a leak or a successful write.
"""

import pytest
from fastapi import HTTPException

from app.api.v1.routes import email as email_routes
from app.api.v1.routes import transactions as tx_routes

BROK = {"id": "b1", "name": "Test"}


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


async def _assert_404(coro):
    with pytest.raises(HTTPException) as exc:
        await coro
    assert exc.value.status_code == 404


async def test_get_transaction_404_when_not_owned(monkeypatch):
    # get_transaction is brokerage-scoped; a foreign id returns None -> 404.
    monkeypatch.setattr(tx_routes.sb, "get_transaction", _async_return(None))
    await _assert_404(tx_routes.get_one("foreign-tx", brokerage=BROK))


async def test_emd_received_404_when_tx_not_owned(monkeypatch):
    # Past the confirm gate, ownership is still enforced before the write.
    monkeypatch.setattr(tx_routes.sb, "get_transaction", _async_return(None))
    body = tx_routes.EmdReceivedIn(received=True, confirmed=True)
    await _assert_404(tx_routes.set_emd_received("foreign-tx", body, brokerage=BROK))


async def test_emd_received_scopes_update_to_caller_brokerage(monkeypatch):
    # The update must be issued against the CALLER's brokerage id, not any id
    # from the request — that scoping is what RLS-bypass relies on.
    monkeypatch.setattr(tx_routes.sb, "get_transaction", _async_return({"id": "t1"}))
    captured = {}

    async def _update(brokerage_id, tx_id, data):
        captured["brokerage_id"] = brokerage_id
        captured["tx_id"] = tx_id
        return {"id": tx_id, **data}

    monkeypatch.setattr(tx_routes.sb, "update_transaction", _update)
    body = tx_routes.EmdReceivedIn(received=True, confirmed=True)
    await tx_routes.set_emd_received("t1", body, brokerage=BROK)
    assert captured["brokerage_id"] == "b1"
    assert captured["tx_id"] == "t1"


async def test_pending_reply_send_404_for_other_brokerage(monkeypatch):
    # The row exists but belongs to brokerage 'other' — must 404, not send.
    monkeypatch.setattr(
        email_routes.sb,
        "get_pending_email_reply",
        _async_return({"id": "r1", "brokerage_id": "other", "status": "pending"}),
    )
    body = email_routes.SendPendingReplyIn(confirmed=True)
    await _assert_404(
        email_routes.send_pending_reply("r1", body, brokerage=BROK, user={"id": "u1"})
    )


async def test_delivery_events_404_when_tx_not_owned(monkeypatch):
    monkeypatch.setattr(email_routes.sb, "get_transaction", _async_return(None))
    await _assert_404(
        email_routes.list_delivery_events("foreign-tx", brokerage=BROK)
    )


async def test_transaction_emails_404_when_tx_not_owned(monkeypatch):
    monkeypatch.setattr(email_routes.sb, "get_transaction", _async_return(None))
    await _assert_404(email_routes.list_emails("foreign-tx", brokerage=BROK))
