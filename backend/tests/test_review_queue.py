"""Bucketing tests for the broker review queue (V2 Section 2B).

Exercises the one-pass categorization in ``broker.review_queue`` end-to-end with
the Supabase/checklist calls monkeypatched. Notably locks in the
``past_closing_not_closed`` vs ``closing_soon_incomplete`` split so a deal whose
closing date has passed never lands in the "rush to finish" bucket.
"""

import datetime as dt

from app.api.v1.routes import broker


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


async def test_review_queue_categorizes_each_bucket(monkeypatch):
    today = dt.date.today()
    recent = dt.datetime.now(dt.timezone.utc).isoformat()
    far = (today + dt.timedelta(days=60)).isoformat()

    txs = [
        {"id": "t_comp", "stage": "under_contract", "compliance_status": "needs_attention",
         "closing_date": far, "last_activity_at": recent, "agent_id": "a1"},
        {"id": "t_past", "stage": "pending",
         "closing_date": (today - dt.timedelta(days=3)).isoformat(),
         "last_activity_at": recent, "agent_id": "a1"},
        {"id": "t_soon", "stage": "under_contract",
         "closing_date": (today + dt.timedelta(days=3)).isoformat(),
         "last_activity_at": recent, "agent_id": "a1"},
        {"id": "t_dl", "stage": "under_contract", "closing_date": far,
         "last_activity_at": recent, "agent_id": "a1"},
        {"id": "t_emd", "stage": "under_contract", "closing_date": far,
         "last_activity_at": recent, "agent_id": "a1",
         "emd_due_date": (today - dt.timedelta(days=2)).isoformat(), "emd_received": False},
        {"id": "t_stale", "stage": "under_contract", "closing_date": far,
         "last_activity_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat(),
         "agent_id": "a1"},
        # closed deal — must be filtered out of every bucket
        {"id": "t_closed", "stage": "closed", "closing_date": far, "last_activity_at": recent},
    ]
    deadlines = [
        {"transaction_id": "t_dl", "due_date": (today - dt.timedelta(days=1)).isoformat(), "resolved": False},
        # a resolved overdue deadline must be ignored
        {"transaction_id": "t_dl", "due_date": (today - dt.timedelta(days=4)).isoformat(), "resolved": True},
    ]
    pct = {"t_comp": 95, "t_past": 95, "t_soon": 50, "t_dl": 95, "t_emd": 95, "t_stale": 95}

    monkeypatch.setattr(broker.sb, "list_transactions", _async_return(txs))
    monkeypatch.setattr(broker.sb, "list_agents", _async_return([{"id": "a1", "name": "Agent A"}]))
    monkeypatch.setattr(broker.sb, "list_deadlines_in", _async_return(deadlines))
    monkeypatch.setattr(broker.sb, "list_pending_email_replies", _async_return([]))
    monkeypatch.setattr(broker.sb, "list_pending_status_updates", _async_return([]))
    monkeypatch.setattr(broker.compliance_checklist, "pct_for_transactions", _async_return(pct))

    res = await broker.review_queue(brokerage={"id": "b1"})

    assert [r["id"] for r in res["compliance_attention"]] == ["t_comp"]
    assert [r["id"] for r in res["past_closing_not_closed"]] == ["t_past"]
    assert [r["id"] for r in res["closing_soon_incomplete"]] == ["t_soon"]
    assert [r["id"] for r in res["overdue_deadlines"]] == ["t_dl"]
    assert [r["id"] for r in res["emd_overdue"]] == ["t_emd"]
    assert [r["id"] for r in res["stale_transactions"]] == ["t_stale"]
    assert res["total"] == 6

    all_ids = {
        r["id"]
        for bucket in res.values()
        if isinstance(bucket, list)
        for r in bucket
    }
    assert "t_closed" not in all_ids  # closed deals never appear


async def test_review_queue_overdue_deadline_skips_resolved(monkeypatch):
    today = dt.date.today()
    recent = dt.datetime.now(dt.timezone.utc).isoformat()
    far = (today + dt.timedelta(days=60)).isoformat()
    txs = [{"id": "t1", "stage": "under_contract", "closing_date": far,
            "last_activity_at": recent, "agent_id": None}]
    deadlines = [
        {"transaction_id": "t1", "due_date": (today - dt.timedelta(days=2)).isoformat(), "resolved": True},
    ]
    monkeypatch.setattr(broker.sb, "list_transactions", _async_return(txs))
    monkeypatch.setattr(broker.sb, "list_agents", _async_return([]))
    monkeypatch.setattr(broker.sb, "list_deadlines_in", _async_return(deadlines))
    monkeypatch.setattr(broker.sb, "list_pending_email_replies", _async_return([]))
    monkeypatch.setattr(broker.sb, "list_pending_status_updates", _async_return([]))
    monkeypatch.setattr(broker.compliance_checklist, "pct_for_transactions", _async_return({"t1": 95}))

    res = await broker.review_queue(brokerage={"id": "b1"})
    assert res["overdue_deadlines"] == []


# --------------------------------------------------------------------------- #
# Stuck-draft escalation (needs_agent_routing).
# --------------------------------------------------------------------------- #

def test_escalation_flags_unassigned_and_old(monkeypatch):
    now = dt.datetime(2026, 6, 13, 12, 0, tzinfo=dt.timezone.utc)
    tx_by_id = {
        "t_unassigned": {"id": "t_unassigned", "address": "1 A St", "agent_id": None},
        "t_old": {"id": "t_old", "address": "2 B St", "agent_id": "a1"},
        "t_fresh": {"id": "t_fresh", "address": "3 C St", "agent_id": "a1"},
    }
    agents = {"a1": "Agent A"}
    pending = [
        # unassigned but fresh → escalates on "no agent"
        ("A drafted reply", {"transaction_id": "t_unassigned",
                             "created_at": (now - dt.timedelta(hours=1)).isoformat()}),
        # assigned but stale → escalates on time
        ("A status update", {"transaction_id": "t_old",
                             "created_at": (now - dt.timedelta(hours=30)).isoformat()}),
        # assigned and fresh → not escalated
        ("A drafted reply", {"transaction_id": "t_fresh",
                             "created_at": (now - dt.timedelta(hours=2)).isoformat()}),
    ]
    rows = broker.build_routing_escalations(pending, tx_by_id, agents, now)
    ids = {r["id"] for r in rows}
    assert ids == {"t_unassigned", "t_old"}
    by_id = {r["id"]: r["reason"] for r in rows}
    assert "no agent assigned" in by_id["t_unassigned"]
    assert "waiting" in by_id["t_old"]


def test_escalation_ignores_unknown_transaction(monkeypatch):
    now = dt.datetime(2026, 6, 13, 12, 0, tzinfo=dt.timezone.utc)
    pending = [("A drafted reply", {"transaction_id": "gone",
                                    "created_at": (now - dt.timedelta(hours=99)).isoformat()})]
    assert broker.build_routing_escalations(pending, {}, {}, now) == []
