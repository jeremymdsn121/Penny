"""The unattended cron scan must never be open and must isolate per-tenant
failures (one brokerage erroring can't abort the rest)."""

import pytest
from fastapi import HTTPException

from app.api.v1.routes import cron as cron_routes


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


async def test_cron_disabled_when_secret_unset(monkeypatch):
    monkeypatch.setattr(cron_routes.settings, "CRON_SECRET", None)
    with pytest.raises(HTTPException) as exc:
        await cron_routes.run_scans(x_cron_secret="anything")
    assert exc.value.status_code == 503


async def test_cron_rejects_wrong_secret(monkeypatch):
    monkeypatch.setattr(cron_routes.settings, "CRON_SECRET", "right")
    with pytest.raises(HTTPException) as exc:
        await cron_routes.run_scans(x_cron_secret="wrong")
    assert exc.value.status_code == 403


async def test_cron_rejects_empty_secret(monkeypatch):
    monkeypatch.setattr(cron_routes.settings, "CRON_SECRET", "right")
    with pytest.raises(HTTPException) as exc:
        await cron_routes.run_scans(x_cron_secret="")
    assert exc.value.status_code == 403


async def test_cron_isolates_per_brokerage_failure(monkeypatch):
    monkeypatch.setattr(cron_routes.settings, "CRON_SECRET", "right")
    monkeypatch.setattr(
        cron_routes.sb, "list_brokerages",
        _async_return([{"id": "b1"}, {"id": "b2"}]),
    )

    async def _reminders(bid):
        if bid == "b1":
            raise RuntimeError("b1 boom")
        return {"processed": 3}

    monkeypatch.setattr(cron_routes.deadline_reminders, "run_reminders", _reminders)
    monkeypatch.setattr(
        cron_routes.email_scheduler, "run_for_brokerage",
        _async_return({"resurfaced": 1, "reminded": 0}),
    )

    result = await cron_routes.run_scans(x_cron_secret="right")
    assert result["ok"] is True
    assert result["brokerages"] == 2
    # b2's reminders still processed despite b1 raising.
    assert result["reminders_processed"] == 3
    assert result["replies_resurfaced"] == 2  # both brokerages' reply scans ran
    assert any(e["brokerage_id"] == "b1" for e in result["errors"])
