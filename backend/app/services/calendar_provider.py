"""Calendar provider seam (PRD task ``scheduling``) — Google Calendar.

The single place the live Google calendar integration plugs in. Two levels:

  * **Brokerage** calendar — token on ``brokerages.google_calendar_token``.
  * **Per-agent** calendar — token on ``agents.google_calendar_token`` (024).

A deal routes to its agent's calendar when connected, else the brokerage's, else
nothing (slot math still works off working hours + local appointments). Resolution
is :func:`resolve_account`; everything downstream operates on the returned account.

OAuth is the Authorization Code grant. The connect/callback routes live in
``routes/calendar.py``; this module owns the Google HTTP calls (raw ``httpx`` to
match ``supabase_client``), token refresh, and free/busy + event sync. State is
HMAC-signed (same secret chain as ``services/consent.py``) so the public callback
can trust the brokerage/agent it carries.

Everything degrades gracefully: with no creds or no token, reads return empty and
writes return ``None``/``False`` — a calendar problem never breaks scheduling.
"""

from __future__ import annotations

import hmac
import time
import urllib.parse
from datetime import datetime
from hashlib import sha256
from typing import Any

import httpx

from app.config import settings
from app.core import supabase_client as sb

# --- Google endpoints + scopes -------------------------------------------- #
_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_CAL_BASE = "https://www.googleapis.com/calendar/v3"
SCOPES = (
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/calendar.freebusy"
)
_TIMEOUT = httpx.Timeout(20.0)
_SKEW_SECONDS = 60  # refresh a little before the token actually expires


def oauth_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


# --- Signed OAuth state ---------------------------------------------------- #
# Connect links get handed to agents over email/chat, so the signed state must
# eventually expire — an unexpiring state is a permanent capability to overwrite
# the brokerage's calendar connection for anyone who ever sees the link. Seven
# days is generous for "click this when you get a minute" while still bounding
# the exposure.
STATE_TTL_SECONDS = 7 * 24 * 3600


def _secret() -> str:
    return settings.CONSENT_SECRET or settings.SECRET_KEY


def make_state(brokerage_id: str, agent_id: str = "") -> str:
    """Sign ``brokerage_id:agent_id:issued_at`` so the public callback can trust it."""
    issued = int(time.time())
    payload = f"{brokerage_id}:{agent_id}:{issued}"
    sig = hmac.new(_secret().encode(), payload.encode(), sha256).hexdigest()
    return f"{payload}:{sig}"


def parse_state(state: str) -> tuple[str, str] | None:
    """Return ``(brokerage_id, agent_id)`` if the state is valid and fresh, else None."""
    parts = (state or "").split(":")
    if len(parts) != 4:
        return None
    brokerage_id, agent_id, issued_raw, sig = parts
    expected = hmac.new(
        _secret().encode(), f"{brokerage_id}:{agent_id}:{issued_raw}".encode(), sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        issued = int(issued_raw)
    except ValueError:
        return None
    if not (0 <= time.time() - issued <= STATE_TTL_SECONDS):
        return None
    return brokerage_id, agent_id


# --- OAuth flow ------------------------------------------------------------ #
def build_auth_url(state: str, redirect_uri: str) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID or "",
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",  # we want a refresh token
        "prompt": "consent",  # force refresh-token issuance on reconnect
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _token_from_response(data: dict[str, Any], *, prior: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalise a Google token response into our stored shape. A refresh
    response omits ``refresh_token``; carry the prior one forward."""
    token = {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token")
        or (prior or {}).get("refresh_token"),
        "expiry": time.time() + float(data.get("expires_in", 3600)),
        "scope": data.get("scope", SCOPES),
        "token_type": data.get("token_type", "Bearer"),
    }
    return token


async def exchange_code(code: str, redirect_uri: str) -> dict[str, Any] | None:
    """Exchange an authorization code for a token dict. None on failure."""
    if not oauth_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        if resp.status_code >= 400:
            print(f"[calendar] token exchange failed: {resp.status_code} {resp.text}")
            return None
        return _token_from_response(resp.json())
    except Exception as exc:  # noqa: BLE001
        print(f"[calendar] token exchange error: {exc!r}")
        return None


async def _refresh(token: dict[str, Any]) -> dict[str, Any] | None:
    refresh_token = (token or {}).get("refresh_token")
    if not refresh_token or not oauth_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _TOKEN_ENDPOINT,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if resp.status_code >= 400:
            print(f"[calendar] refresh failed: {resp.status_code} {resp.text}")
            return None
        return _token_from_response(resp.json(), prior=token)
    except Exception as exc:  # noqa: BLE001
        print(f"[calendar] refresh error: {exc!r}")
        return None


# --- Account resolution ---------------------------------------------------- #
def _google_token(holder: dict[str, Any] | None) -> dict[str, Any] | None:
    """The google token on a brokerage/agent row, if it looks connected."""
    if not holder:
        return None
    token = holder.get("google_calendar_token")
    if isinstance(token, dict) and token.get("access_token"):
        return token
    return None


def resolve_account(
    brokerage: dict[str, Any], agent: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Pick the calendar a deal should use: the agent's if connected, else the
    brokerage's, else None."""
    agent_token = _google_token(agent)
    if agent and agent_token:
        return {
            "owner": "agent",
            "brokerage_id": brokerage["id"],
            "agent_id": agent["id"],
            "provider": "google",
            "token": agent_token,
        }
    brok_token = _google_token(brokerage)
    if brok_token:
        return {
            "owner": "brokerage",
            "brokerage_id": brokerage["id"],
            "agent_id": None,
            "provider": "google",
            "token": brok_token,
        }
    return None


async def _persist_token(account: dict[str, Any], token: dict[str, Any]) -> None:
    try:
        if account["owner"] == "agent":
            await sb.update_agent(
                account["brokerage_id"], account["agent_id"],
                {"google_calendar_token": token},
            )
        else:
            await sb.update_brokerage(
                account["brokerage_id"], {"google_calendar_token": token}
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[calendar] could not persist refreshed token: {exc!r}")


async def _access_token(account: dict[str, Any]) -> str | None:
    """A live access token for this account, refreshing + persisting if expired."""
    token = account.get("token") or {}
    if token.get("expiry", 0) - _SKEW_SECONDS > time.time():
        return token.get("access_token")
    refreshed = await _refresh(token)
    if refreshed:
        account["token"] = refreshed
        await _persist_token(account, refreshed)
        return refreshed.get("access_token")
    # Refresh failed (revoked / no refresh token) — try the existing token; if
    # it's dead the API call below will just fail and degrade gracefully.
    return token.get("access_token")


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


# --- Calendar operations --------------------------------------------------- #
async def get_busy_checked(
    account: dict[str, Any] | None, start: datetime, end: datetime
) -> tuple[list[tuple[datetime, datetime]], bool]:
    """Busy intervals from the account's primary calendar, plus an ``ok`` flag.

    ``ok`` is False only when a *connected* calendar couldn't be read (dead token,
    HTTP error, timeout) — callers should then avoid implying the user is free.
    No connected account returns ``([], True)``: nothing to read is not an error.
    """
    if not account:
        return [], True
    access = await _access_token(account)
    if not access:
        return [], False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_CAL_BASE}/freeBusy",
                headers=_auth_headers(access),
                json={
                    "timeMin": start.isoformat(),
                    "timeMax": end.isoformat(),
                    "items": [{"id": "primary"}],
                },
            )
        if resp.status_code >= 400:
            print(f"[calendar] freeBusy failed: {resp.status_code} {resp.text}")
            return [], False
        cal = (resp.json().get("calendars") or {}).get("primary") or {}
        out: list[tuple[datetime, datetime]] = []
        for b in cal.get("busy", []):
            try:
                bs = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
                be = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            out.append((bs, be))
        return out, True
    except Exception as exc:  # noqa: BLE001
        print(f"[calendar] freeBusy error: {exc!r}")
        return [], False


async def get_busy(
    account: dict[str, Any] | None, start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """Busy intervals only (back-compat). ``[]`` on no account or any error."""
    busy, _ = await get_busy_checked(account, start, end)
    return busy


async def list_events(
    account: dict[str, Any] | None, start: datetime, end: datetime
) -> tuple[list[dict[str, Any]], bool]:
    """Actual events (with titles) on the primary calendar in ``[start, end)``.

    Each event: ``{summary, all_day, start, end}`` (start/end are raw ISO strings —
    a dateTime for timed events, a date for all-day). ``ok`` mirrors
    :func:`get_busy_checked`. Used for "what's on my schedule", where free/busy
    intervals (no titles) aren't enough.
    """
    if not account:
        return [], True
    access = await _access_token(account)
    if not access:
        return [], False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_CAL_BASE}/calendars/primary/events",
                headers=_auth_headers(access),
                params={
                    "timeMin": start.isoformat(),
                    "timeMax": end.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "50",
                },
            )
        if resp.status_code >= 400:
            print(f"[calendar] events.list failed: {resp.status_code} {resp.text}")
            return [], False
        out: list[dict[str, Any]] = []
        for it in resp.json().get("items", []):
            if it.get("status") == "cancelled":
                continue
            s = it.get("start") or {}
            e = it.get("end") or {}
            all_day = "date" in s and "dateTime" not in s
            start_raw = s.get("dateTime") or s.get("date")
            if not start_raw:
                continue
            out.append(
                {
                    "summary": it.get("summary") or "(busy)",
                    "all_day": all_day,
                    "start": start_raw,
                    "end": e.get("dateTime") or e.get("date"),
                }
            )
        return out, True
    except Exception as exc:  # noqa: BLE001
        print(f"[calendar] events.list error: {exc!r}")
        return [], False


def _event_body(
    summary: str, start: datetime, end: datetime, attendees: list[str]
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    clean = [{"email": a} for a in attendees if a and a.strip()]
    if clean:
        body["attendees"] = clean
    return body


async def create_event(
    account: dict[str, Any] | None,
    *,
    summary: str,
    start: datetime,
    end: datetime,
    attendees: list[str],
) -> str | None:
    """Create an event on the account's primary calendar; return its id."""
    if not account:
        return None
    access = await _access_token(account)
    if not access:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_CAL_BASE}/calendars/primary/events",
                headers=_auth_headers(access),
                params={"sendUpdates": "all"},
                json=_event_body(summary, start, end, attendees),
            )
        if resp.status_code >= 400:
            print(f"[calendar] create_event failed: {resp.status_code} {resp.text}")
            return None
        return resp.json().get("id")
    except Exception as exc:  # noqa: BLE001
        print(f"[calendar] create_event error: {exc!r}")
        return None


async def update_event(
    account: dict[str, Any] | None,
    event_id: str,
    *,
    summary: str,
    start: datetime,
    end: datetime,
    attendees: list[str],
) -> bool:
    """Patch an existing event (reschedule). False if no account/event."""
    if not account or not event_id:
        return False
    access = await _access_token(account)
    if not access:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.patch(
                f"{_CAL_BASE}/calendars/primary/events/{event_id}",
                headers=_auth_headers(access),
                params={"sendUpdates": "all"},
                json=_event_body(summary, start, end, attendees),
            )
        if resp.status_code >= 400:
            print(f"[calendar] update_event failed: {resp.status_code} {resp.text}")
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[calendar] update_event error: {exc!r}")
        return False


async def delete_event(account: dict[str, Any] | None, event_id: str) -> bool:
    """Delete an event (cancel). False if no account/event."""
    if not account or not event_id:
        return False
    access = await _access_token(account)
    if not access:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.delete(
                f"{_CAL_BASE}/calendars/primary/events/{event_id}",
                headers=_auth_headers(access),
                params={"sendUpdates": "all"},
            )
        # 410 Gone = already deleted; treat as success.
        if resp.status_code >= 400 and resp.status_code != 410:
            print(f"[calendar] delete_event failed: {resp.status_code} {resp.text}")
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[calendar] delete_event error: {exc!r}")
        return False


# --- Status reporting ------------------------------------------------------ #
def status(brokerage: dict[str, Any]) -> dict[str, Any]:
    """Brokerage-level calendar status (used in the propose response)."""
    token = _google_token(brokerage)
    return {
        "provider": brokerage.get("calendar_provider"),
        "connected": bool(token),
        "sync_enabled": bool(token) and oauth_configured(),
    }


def agent_status(agent: dict[str, Any]) -> dict[str, Any]:
    token = _google_token(agent)
    return {
        "id": agent.get("id"),
        "name": agent.get("name"),
        "email": agent.get("email"),
        "provider": agent.get("calendar_provider"),
        "connected": bool(token),
        # Per-agent working-hours override (NULL = inherit the brokerage's).
        "work_start": agent.get("work_start"),
        "work_end": agent.get("work_end"),
        "buffer_minutes": agent.get("buffer_minutes"),
    }


def account_status(account: dict[str, Any] | None) -> dict[str, Any]:
    """Status of the calendar a specific deal would actually use."""
    if not account:
        return {"connected": False, "owner": None, "provider": None}
    return {
        "connected": True,
        "owner": account["owner"],
        "provider": account.get("provider"),
    }


def is_connected(brokerage: dict[str, Any]) -> bool:
    return status(brokerage)["connected"] and status(brokerage)["sync_enabled"]
