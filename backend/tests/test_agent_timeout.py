"""run_penny_agent never hangs and names the cause.

A slow or erroring Anthropic call must yield a fast, cause-specific reply
instead of a multi-minute stall (a real incident: one inbound hung ~22 minutes
on a slow Claude call because nothing bounded the run). These exercise the
overall deadline plus each provider-error branch.
"""

import asyncio

import httpx
from anthropic import APITimeoutError, OverloadedError, RateLimitError

from app.services import penny_agent


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _resp(status: int) -> httpx.Response:
    return httpx.Response(status, request=_req())


class _Messages:
    def __init__(self, exc=None, sleep=0.0):
        self._exc = exc
        self._sleep = sleep

    async def create(self, **kwargs):
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._exc:
            raise self._exc
        raise AssertionError("messages.create should not have succeeded in this test")


class _Client:
    def __init__(self, exc=None, sleep=0.0):
        self.messages = _Messages(exc, sleep)


async def _async_return(value):
    return value


def _patch(monkeypatch, client):
    monkeypatch.setattr(penny_agent.settings, "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(penny_agent, "AsyncAnthropic", lambda **kw: client)
    monkeypatch.setattr(penny_agent.sb, "get_task_autonomy", lambda *a, **k: _async_return([]))
    monkeypatch.setattr(penny_agent.sb, "log_ai_usage", lambda *a, **k: _async_return(None))


async def _run(monkeypatch, client) -> str:
    _patch(monkeypatch, client)
    return await penny_agent.run_penny_agent(
        brokerage_id="b1",
        brokerage_name="Test",
        contact_display_name="Jeremy",
        history=[],
        current_message="what's overdue?",
    )


async def test_overall_deadline_returns_fast_slow_message(monkeypatch):
    # A call that outlives the deadline is cut off and reported as "slow", fast.
    monkeypatch.setattr(penny_agent, "AGENT_DEADLINE_SECONDS", 0.05)
    reply = await asyncio.wait_for(_run(monkeypatch, _Client(sleep=5.0)), timeout=2.0)
    assert "slow" in reply.lower()


async def test_request_timeout_names_cause(monkeypatch):
    reply = await _run(monkeypatch, _Client(exc=APITimeoutError(_req())))
    assert "slow" in reply.lower()


async def test_rate_limit_names_cause(monkeypatch):
    reply = await _run(
        monkeypatch, _Client(exc=RateLimitError("rl", response=_resp(429), body=None))
    )
    assert "rate" in reply.lower()


async def test_overloaded_names_cause(monkeypatch):
    reply = await _run(
        monkeypatch, _Client(exc=OverloadedError("ov", response=_resp(529), body=None))
    )
    assert "overloaded" in reply.lower()
