"""The web-chat AI cost ceiling: over budget -> graceful breather (no agent
run); under budget or cap disabled -> the agent runs normally."""

from app.api.v1.routes import chat as chat_routes

BROK = {"id": "b1", "name": "Test"}
USER = {"id": "u1", "user_metadata": {}}


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


async def test_over_cap_returns_breather_without_running_agent(monkeypatch):
    monkeypatch.setattr(chat_routes.settings, "AI_DAILY_TOKEN_CAP_PER_BROKERAGE", 1_000)
    monkeypatch.setattr(chat_routes.sb, "ai_tokens_used_today", _async_return(5_000))

    async def _boom(*a, **k):
        raise AssertionError("agent ran despite being over the cap")

    monkeypatch.setattr(chat_routes.penny_agent, "run_penny_agent", _boom)
    out = await chat_routes.chat(
        chat_routes.ChatIn(message="hi"), brokerage=BROK, user=USER
    )
    assert "breather" in out.reply.lower()


async def test_under_cap_runs_agent(monkeypatch):
    monkeypatch.setattr(chat_routes.settings, "AI_DAILY_TOKEN_CAP_PER_BROKERAGE", 1_000_000)
    monkeypatch.setattr(chat_routes.sb, "ai_tokens_used_today", _async_return(10_000))
    monkeypatch.setattr(chat_routes.penny_agent, "run_penny_agent", _async_return("real reply"))
    out = await chat_routes.chat(
        chat_routes.ChatIn(message="hi"), brokerage=BROK, user=USER
    )
    assert out.reply == "real reply"


async def test_cap_zero_disables_check(monkeypatch):
    monkeypatch.setattr(chat_routes.settings, "AI_DAILY_TOKEN_CAP_PER_BROKERAGE", 0)

    async def _boom(*a, **k):
        raise AssertionError("usage was queried despite the cap being disabled")

    monkeypatch.setattr(chat_routes.sb, "ai_tokens_used_today", _boom)
    monkeypatch.setattr(chat_routes.penny_agent, "run_penny_agent", _async_return("ok"))
    out = await chat_routes.chat(
        chat_routes.ChatIn(message="hi"), brokerage=BROK, user=USER
    )
    assert out.reply == "ok"
