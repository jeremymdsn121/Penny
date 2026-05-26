"""Thin async wrappers over the Supabase Auth (GoTrue) and PostgREST APIs.

We talk to Supabase over HTTP with httpx rather than the supabase-py SDK to keep
the dependency surface small and predictable. The service-role key is used only
here, server-side, and bypasses row-level security; the anon key is used for
user-scoped auth calls (sign in, get user, sign out).
"""

from typing import Any

import httpx

from app.config import settings

AUTH_BASE = f"{settings.SUPABASE_URL}/auth/v1"
REST_BASE = f"{settings.SUPABASE_URL}/rest/v1"
_TIMEOUT = httpx.Timeout(20.0)


class SupabaseError(Exception):
    """Raised when a Supabase call returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


def _detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except Exception:
        return resp.text or resp.reason_phrase
    if isinstance(data, dict):
        for key in ("msg", "error_description", "message", "error", "hint"):
            if data.get(key):
                return str(data[key])
    return resp.text


def _service_headers() -> dict[str, str]:
    return {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def _anon_headers(token: str | None = None) -> dict[str, str]:
    return {
        "apikey": settings.SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token or settings.SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }


# --------------------------------------------------------------------------- #
# Auth (GoTrue)
# --------------------------------------------------------------------------- #

async def admin_create_user(
    email: str,
    password: str,
    *,
    email_confirm: bool = True,
    app_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "email": email,
        "password": password,
        "email_confirm": email_confirm,
    }
    if app_metadata:
        payload["app_metadata"] = app_metadata
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{AUTH_BASE}/admin/users", json=payload, headers=_service_headers()
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def update_app_metadata(user_id: str, app_metadata: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.put(
            f"{AUTH_BASE}/admin/users/{user_id}",
            json={"app_metadata": app_metadata},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def admin_delete_user(user_id: str, *, suppress: bool = False) -> None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.delete(
                f"{AUTH_BASE}/admin/users/{user_id}", headers=_service_headers()
            )
        if resp.status_code >= 400:
            raise SupabaseError(resp.status_code, _detail(resp))
    except SupabaseError:
        if not suppress:
            raise


async def sign_in(email: str, password: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{AUTH_BASE}/token",
            params={"grant_type": "password"},
            json={"email": email, "password": password},
            headers=_anon_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_user(token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{AUTH_BASE}/user", headers=_anon_headers(token))
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def sign_out(token: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{AUTH_BASE}/logout", headers=_anon_headers(token))
    # 204 = success; 401 = token already invalid, which is fine for logout.
    if resp.status_code >= 400 and resp.status_code != 401:
        raise SupabaseError(resp.status_code, _detail(resp))


# --------------------------------------------------------------------------- #
# Data (PostgREST) — service-role, bypasses RLS
# --------------------------------------------------------------------------- #

async def insert_brokerage(data: dict[str, Any]) -> dict[str, Any]:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{REST_BASE}/brokerages", json=data, headers=headers)
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) else rows


async def get_brokerage(brokerage_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/brokerages",
            params={"id": f"eq.{brokerage_id}", "select": "*", "limit": "1"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None
