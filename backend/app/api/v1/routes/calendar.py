"""Calendar OAuth connect/callback (PRD task ``scheduling``).

Google Calendar connection at two levels: the brokerage's shared calendar, and
each agent's own. Agents have no web login, so per-agent connection is
admin-initiated — the admin gets a connect URL (optionally to hand to the agent),
who signs into their own Google. The signed ``state`` carries the brokerage (and
agent) the token belongs to, so the public callback can store it without a JWT.

The heavy lifting (Google HTTP, token refresh, event sync) lives in
``services/calendar_provider.py``; this module is just the OAuth dance + the
small connect/disconnect/status surface the frontend drives.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.config import settings
from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.services import calendar_provider as cal

router = APIRouter(prefix="/calendar", tags=["calendar"])


def _redirect_uri() -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/calendar/google/callback"


def _frontend_return(params: str) -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/settings/calendar?{params}"


@router.get("/status")
async def calendar_status(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Brokerage calendar + per-agent connection state."""
    agents = await sb.list_agents(brokerage["id"])
    return {
        "oauth_configured": cal.oauth_configured(),
        "brokerage": cal.status(brokerage),
        "agents": [cal.agent_status(a) for a in agents],
    }


@router.get("/google/connect")
async def google_connect(
    agent_id: str | None = Query(default=None),
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, str]:
    """Return the Google consent URL for the brokerage (or a specific agent).

    The frontend redirects the admin to ``auth_url`` to connect, or surfaces it as
    a copyable link to hand to the agent so they sign into their own Google.
    """
    if not cal.oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google calendar is not configured on the server.",
        )
    if agent_id:
        agent = await sb.get_agent(brokerage["id"], agent_id)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    state = cal.make_state(brokerage["id"], agent_id or "")
    return {"auth_url": cal.build_auth_url(state, _redirect_uri())}


@router.get("/google/callback")
async def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """Google redirects here after consent (public — no JWT). Store the token on
    the brokerage or agent the signed state names, then bounce to the frontend."""
    if error:
        return RedirectResponse(_frontend_return(f"calendar_error={error}"))
    parsed = cal.parse_state(state or "")
    if not parsed or not code:
        return RedirectResponse(_frontend_return("calendar_error=invalid_state"))
    brokerage_id, agent_id = parsed

    token = await cal.exchange_code(code, _redirect_uri())
    if not token:
        return RedirectResponse(_frontend_return("calendar_error=exchange_failed"))

    data = {"google_calendar_token": token, "calendar_provider": "google"}
    try:
        if agent_id:
            await sb.update_agent(brokerage_id, agent_id, data)
        else:
            await sb.update_brokerage(brokerage_id, data)
    except sb.SupabaseError as exc:
        print(f"[calendar] could not store token: {exc!r}")
        return RedirectResponse(_frontend_return("calendar_error=store_failed"))

    return RedirectResponse(_frontend_return("connected=google"))


@router.post("/disconnect")
async def disconnect(
    agent_id: str | None = Query(default=None),
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, bool]:
    """Clear the Google token + provider on the brokerage or a specific agent."""
    data = {"google_calendar_token": None, "calendar_provider": None}
    if agent_id:
        agent = await sb.get_agent(brokerage["id"], agent_id)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        await sb.update_agent(brokerage["id"], agent_id, data)
    else:
        await sb.update_brokerage(brokerage["id"], data)
    return {"disconnected": True}
