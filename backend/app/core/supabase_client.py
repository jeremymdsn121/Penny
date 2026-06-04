"""Thin async wrappers over the Supabase Auth (GoTrue) and PostgREST APIs.

We talk to Supabase over HTTP with httpx rather than the supabase-py SDK to keep
the dependency surface small and predictable. The service-role key is used only
here, server-side, and bypasses row-level security; the anon key is used for
user-scoped auth calls (sign in, get user, sign out).
"""

from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

AUTH_BASE = f"{settings.SUPABASE_URL}/auth/v1"
REST_BASE = f"{settings.SUPABASE_URL}/rest/v1"
STORAGE_BASE = f"{settings.SUPABASE_URL}/storage/v1"
_TIMEOUT = httpx.Timeout(30.0)


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


async def update_brokerage(brokerage_id: str, data: dict[str, Any]) -> dict[str, Any]:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/brokerages",
            params={"id": f"eq.{brokerage_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def get_task_autonomy(brokerage_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/task_autonomy",
            params={"brokerage_id": f"eq.{brokerage_id}", "select": "task_id,autonomous"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


# --------------------------------------------------------------------------- #
# Agents — brokerage-scoped roster (used for per-agent style profiles & channels)
# --------------------------------------------------------------------------- #

async def list_agents(brokerage_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/agents",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "select": "*",
                "order": "created_at.asc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_agent(brokerage_id: str, agent_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/agents",
            params={
                "id": f"eq.{agent_id}",
                "brokerage_id": f"eq.{brokerage_id}",
                "select": "*",
                "limit": "1",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def insert_agent(data: dict[str, Any]) -> dict[str, Any]:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{REST_BASE}/agents", json=data, headers=headers)
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def log_ai_usage(
    brokerage_id: str | None,
    feature: str,
    model: str,
    usage: dict[str, int],
) -> None:
    """Best-effort: record one AI call's token usage (ai_usage, migration 020).

    For per-brokerage unit-economics tracking. Never raises — a logging failure
    must not break the user-facing call, and the table may not exist yet on an
    environment where 020 hasn't been applied.
    """
    row = {
        "brokerage_id": brokerage_id,
        "feature": feature,
        "model": model,
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            await client.post(f"{REST_BASE}/ai_usage", json=row, headers=_service_headers())
    except Exception:
        pass


async def update_agent(
    brokerage_id: str, agent_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/agents",
            params={"id": f"eq.{agent_id}", "brokerage_id": f"eq.{brokerage_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def delete_agent(brokerage_id: str, agent_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/agents",
            params={"id": f"eq.{agent_id}", "brokerage_id": f"eq.{brokerage_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


async def insert_transaction(data: dict[str, Any]) -> dict[str, Any]:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{REST_BASE}/transactions", json=data, headers=headers)
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def list_transactions(brokerage_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/transactions",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "select": "*",
                "order": "created_at.desc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_transaction(brokerage_id: str, transaction_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/transactions",
            params={
                "id": f"eq.{transaction_id}",
                "brokerage_id": f"eq.{brokerage_id}",
                "select": "*",
                "limit": "1",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def update_transaction(
    brokerage_id: str, transaction_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/transactions",
            params={"id": f"eq.{transaction_id}", "brokerage_id": f"eq.{brokerage_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def delete_transaction(brokerage_id: str, transaction_id: str) -> None:
    """Delete a transaction (brokerage-scoped). Child rows (deadlines, tasks,
    emails, etc.) cascade via their FKs."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/transactions",
            params={"id": f"eq.{transaction_id}", "brokerage_id": f"eq.{brokerage_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


async def _confirmed_rules(
    brokerage_id: str, agent_filter: str
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/knowledge_rules",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "confirmed": "eq.true",
                "agent_id": agent_filter,
                "select": "category,rule",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_confirmed_knowledge_rules(
    brokerage_id: str, agent_id: str | None = None
) -> list[dict[str, Any]]:
    """Confirmed style rules for AI prompts.

    Brokerage-wide rules (agent_id IS NULL) are always included. When an
    ``agent_id`` is supplied, that agent's confirmed rules are layered on top and
    take precedence over a brokerage rule sharing the same category — so an
    agent's "sign off as Best" overrides the brokerage's "Warm regards".
    """
    brokerage_rules = await _confirmed_rules(brokerage_id, "is.null")
    if not agent_id:
        return brokerage_rules

    agent_rules = await _confirmed_rules(brokerage_id, f"eq.{agent_id}")
    agent_categories = {
        (r.get("category") or "").strip().lower() for r in agent_rules
    }
    merged = list(agent_rules)
    merged += [
        r
        for r in brokerage_rules
        if (r.get("category") or "").strip().lower() not in agent_categories
    ]
    return merged


async def search_transactions(
    brokerage_id: str, address_query: str
) -> list[dict[str, Any]]:
    """Return transactions whose address contains the query string (case-insensitive)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/transactions",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "address": f"ilike.*{address_query}*",
                "select": "*",
                "order": "created_at.desc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


# --------------------------------------------------------------------------- #
# Messaging channels (agent_channels) — WhatsApp + SMS. One row per channel; a
# number can be registered on both. The *_whatsapp_contact wrappers below keep
# the existing WhatsApp call sites working against the unified table.
# --------------------------------------------------------------------------- #

async def lookup_channel(phone_number: str, channel: str) -> dict[str, Any] | None:
    """Find the brokerage/agent a phone number is registered to on a channel."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/agent_channels",
            params={
                "phone_number": f"eq.{phone_number}",
                "channel": f"eq.{channel}",
                "select": "*",
                "limit": "1",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def list_channels(
    brokerage_id: str, channel: str | None = None
) -> list[dict[str, Any]]:
    params = {
        "brokerage_id": f"eq.{brokerage_id}",
        "select": "*",
        "order": "created_at.asc",
    }
    if channel:
        params["channel"] = f"eq.{channel}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/agent_channels", params=params, headers=_service_headers()
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def upsert_channel(
    brokerage_id: str,
    channel: str,
    phone_number: str,
    display_name: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "brokerage_id": brokerage_id,
        "channel": channel,
        "phone_number": phone_number,
    }
    if display_name is not None:
        payload["display_name"] = display_name
    if agent_id is not None:
        payload["agent_id"] = agent_id
    headers = _service_headers() | {
        "Prefer": "return=representation,resolution=merge-duplicates",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/agent_channels",
            params={"on_conflict": "brokerage_id,phone_number,channel"},
            json=payload,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def delete_channel(brokerage_id: str, channel: str, phone_number: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/agent_channels",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "channel": f"eq.{channel}",
                "phone_number": f"eq.{phone_number}",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


# Backward-compatible WhatsApp wrappers (existing call sites).
async def lookup_whatsapp_contact(phone_number: str) -> dict[str, Any] | None:
    return await lookup_channel(phone_number, "whatsapp")


async def list_whatsapp_contacts(brokerage_id: str) -> list[dict[str, Any]]:
    return await list_channels(brokerage_id, "whatsapp")


async def upsert_whatsapp_contact(
    brokerage_id: str, phone_number: str, display_name: str | None = None
) -> dict[str, Any]:
    return await upsert_channel(brokerage_id, "whatsapp", phone_number, display_name)


async def delete_whatsapp_contact(brokerage_id: str, phone_number: str) -> None:
    await delete_channel(brokerage_id, "whatsapp", phone_number)


# --------------------------------------------------------------------------- #
# Pending WhatsApp transactions — V2 Section 1A
# One row per contact (UNIQUE brokerage_id + phone_number); upsert replaces.
# --------------------------------------------------------------------------- #

async def get_pending_whatsapp_transaction(
    brokerage_id: str, phone_number: str
) -> dict[str, Any] | None:
    """Return the non-expired pending extraction for this contact, or None."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/pending_whatsapp_transactions",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "phone_number": f"eq.{phone_number}",
                "expires_at": f"gt.{_now_iso()}",
                "select": "*",
                "limit": "1",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def upsert_pending_whatsapp_transaction(data: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace a pending extraction for a contact (upsert on brokerage_id+phone_number)."""
    headers = _service_headers() | {
        "Prefer": "return=representation,resolution=merge-duplicates",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/pending_whatsapp_transactions",
            params={"on_conflict": "brokerage_id,phone_number"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def update_pending_whatsapp_transaction(
    record_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/pending_whatsapp_transactions",
            params={"id": f"eq.{record_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def delete_pending_whatsapp_transaction(record_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/pending_whatsapp_transactions",
            params={"id": f"eq.{record_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


# --------------------------------------------------------------------------- #
# WhatsApp messages (conversation history)
# --------------------------------------------------------------------------- #

async def save_whatsapp_message(
    brokerage_id: str,
    phone_number: str,
    direction: str,
    body: str,
    *,
    media_url: str | None = None,
    content_type: str = "text",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "brokerage_id": brokerage_id,
        "phone_number": phone_number,
        "direction": direction,
        "body": body,
        "content_type": content_type,
    }
    if media_url:
        payload["media_url"] = media_url
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/whatsapp_messages", json=payload, headers=headers
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def get_whatsapp_messages(
    brokerage_id: str, phone_number: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Return the most recent messages for a thread, oldest-first."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/whatsapp_messages",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "phone_number": f"eq.{phone_number}",
                "select": "direction,body,content_type,created_at",
                "order": "created_at.desc",
                "limit": str(limit),
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return list(reversed(rows))  # oldest-first for Claude messages array


async def replace_task_autonomy(
    brokerage_id: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Delete the brokerage's existing toggles, then insert the supplied set."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        del_resp = await client.delete(
            f"{REST_BASE}/task_autonomy",
            params={"brokerage_id": f"eq.{brokerage_id}"},
            headers=_service_headers(),
        )
        if del_resp.status_code >= 400:
            raise SupabaseError(del_resp.status_code, _detail(del_resp))
        if not rows:
            return []
        payload = [{"brokerage_id": brokerage_id, **r} for r in rows]
        ins_resp = await client.post(
            f"{REST_BASE}/task_autonomy",
            json=payload,
            headers=_service_headers() | {"Prefer": "return=representation"},
        )
    if ins_resp.status_code >= 400:
        raise SupabaseError(ins_resp.status_code, _detail(ins_resp))
    return ins_resp.json()


# --------------------------------------------------------------------------- #
# Knowledge base — documents + extracted style rules
# --------------------------------------------------------------------------- #

async def insert_knowledge_document(data: dict[str, Any]) -> dict[str, Any]:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/knowledge_documents", json=data, headers=headers
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def list_knowledge_documents(brokerage_id: str) -> list[dict[str, Any]]:
    """Brokerage-wide style documents (agent-uploaded ones are excluded)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/knowledge_documents",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "agent_id": "is.null",
                "select": "*",
                "order": "created_at.desc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def list_knowledge_documents_for_agent(
    brokerage_id: str, agent_id: str
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/knowledge_documents",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "agent_id": f"eq.{agent_id}",
                "select": "*",
                "order": "created_at.desc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def delete_agent_style_profile(brokerage_id: str, agent_id: str) -> None:
    """Remove all of an agent's style rules and document rows (admin action)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for table in ("knowledge_rules", "knowledge_documents"):
            resp = await client.delete(
                f"{REST_BASE}/{table}",
                params={
                    "brokerage_id": f"eq.{brokerage_id}",
                    "agent_id": f"eq.{agent_id}",
                },
                headers=_service_headers(),
            )
            if resp.status_code >= 400:
                raise SupabaseError(resp.status_code, _detail(resp))


async def get_knowledge_document(
    brokerage_id: str, document_id: str
) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/knowledge_documents",
            params={
                "id": f"eq.{document_id}",
                "brokerage_id": f"eq.{brokerage_id}",
                "select": "*",
                "limit": "1",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def update_knowledge_document(
    brokerage_id: str, document_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/knowledge_documents",
            params={"id": f"eq.{document_id}", "brokerage_id": f"eq.{brokerage_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def delete_knowledge_document(brokerage_id: str, document_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/knowledge_documents",
            params={"id": f"eq.{document_id}", "brokerage_id": f"eq.{brokerage_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


async def insert_knowledge_rules(
    brokerage_id: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Bulk-insert proposed style rules (each defaults to confirmed=false)."""
    if not rows:
        return []
    payload = [{"brokerage_id": brokerage_id, **r} for r in rows]
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/knowledge_rules", json=payload, headers=headers
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


_RULE_SELECT = "id,category,rule,confirmed,document_id,source_document,agent_id,created_at"


async def list_knowledge_rules(brokerage_id: str) -> list[dict[str, Any]]:
    """Brokerage-wide style rules for review — confirmed and pending, newest first.

    Agent-specific rules (agent_id set) are excluded; they're reviewed on the
    agent's own "My Style" page via list_knowledge_rules_for_agent.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/knowledge_rules",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "agent_id": "is.null",
                "select": _RULE_SELECT,
                "order": "created_at.desc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def list_knowledge_rules_for_agent(
    brokerage_id: str, agent_id: str
) -> list[dict[str, Any]]:
    """Style rules scoped to a single agent — confirmed and pending, newest first."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/knowledge_rules",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "agent_id": f"eq.{agent_id}",
                "select": _RULE_SELECT,
                "order": "created_at.desc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def count_agent_style_rules(brokerage_id: str) -> dict[str, int]:
    """Return {agent_id: confirmed_rule_count} so admins can see who has a profile."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/knowledge_rules",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "agent_id": "not.is.null",
                "confirmed": "eq.true",
                "select": "agent_id",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    counts: dict[str, int] = {}
    for row in resp.json():
        aid = row.get("agent_id")
        if aid:
            counts[aid] = counts.get(aid, 0) + 1
    return counts


async def update_knowledge_rule(
    brokerage_id: str, rule_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/knowledge_rules",
            params={"id": f"eq.{rule_id}", "brokerage_id": f"eq.{brokerage_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def delete_knowledge_rule(brokerage_id: str, rule_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/knowledge_rules",
            params={"id": f"eq.{rule_id}", "brokerage_id": f"eq.{brokerage_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


# --------------------------------------------------------------------------- #
# Deadlines — scoped through the parent transaction (no brokerage_id column).
# The caller is responsible for verifying the transaction belongs to the
# brokerage before mutating; these helpers are scope-agnostic.
# --------------------------------------------------------------------------- #

async def list_deadlines_for_transaction(transaction_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/deadlines",
            params={
                "transaction_id": f"eq.{transaction_id}",
                "select": "*",
                "order": "due_date.asc.nullslast",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def list_deadlines_in(transaction_ids: list[str]) -> list[dict[str, Any]]:
    """Deadlines for many transactions in one call (used by the reminder scan)."""
    if not transaction_ids:
        return []
    ids = ",".join(transaction_ids)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/deadlines",
            params={
                "transaction_id": f"in.({ids})",
                "select": "*",
                "order": "due_date.asc.nullslast",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_deadline(deadline_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/deadlines",
            params={"id": f"eq.{deadline_id}", "select": "*", "limit": "1"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def insert_deadline(data: dict[str, Any]) -> dict[str, Any]:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{REST_BASE}/deadlines", json=data, headers=headers)
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def update_deadline(
    deadline_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/deadlines",
            params={"id": f"eq.{deadline_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def delete_deadline(deadline_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/deadlines",
            params={"id": f"eq.{deadline_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


# --------------------------------------------------------------------------- #
# Listings (MLS prep) — brokerage-scoped directly, like transactions.
# --------------------------------------------------------------------------- #

async def insert_listing(data: dict[str, Any]) -> dict[str, Any]:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{REST_BASE}/listings", json=data, headers=headers)
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def list_listings(brokerage_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/listings",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "select": "*",
                "order": "created_at.desc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_listing(brokerage_id: str, listing_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/listings",
            params={
                "id": f"eq.{listing_id}",
                "brokerage_id": f"eq.{brokerage_id}",
                "select": "*",
                "limit": "1",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def update_listing(
    brokerage_id: str, listing_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/listings",
            params={"id": f"eq.{listing_id}", "brokerage_id": f"eq.{brokerage_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def delete_listing(brokerage_id: str, listing_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/listings",
            params={"id": f"eq.{listing_id}", "brokerage_id": f"eq.{brokerage_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


# --------------------------------------------------------------------------- #
# Appointments — scoped through the parent transaction (like deadlines). The
# caller verifies the transaction belongs to the brokerage before mutating.
# --------------------------------------------------------------------------- #

async def list_appointments_for_transaction(transaction_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/appointments",
            params={
                "transaction_id": f"eq.{transaction_id}",
                "select": "*",
                "order": "scheduled_at.asc.nullslast",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def list_appointments_in(transaction_ids: list[str]) -> list[dict[str, Any]]:
    """Appointments across many transactions (used for conflict checks)."""
    if not transaction_ids:
        return []
    ids = ",".join(transaction_ids)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/appointments",
            params={"transaction_id": f"in.({ids})", "select": "*"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_appointment(appointment_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/appointments",
            params={"id": f"eq.{appointment_id}", "select": "*", "limit": "1"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def insert_appointment(data: dict[str, Any]) -> dict[str, Any]:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{REST_BASE}/appointments", json=data, headers=headers)
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def update_appointment(
    appointment_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/appointments",
            params={"id": f"eq.{appointment_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def delete_appointment(appointment_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/appointments",
            params={"id": f"eq.{appointment_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


# --------------------------------------------------------------------------- #
# Compliance checklist — templates (system + brokerage) and per-transaction items
# --------------------------------------------------------------------------- #

async def list_compliance_templates(brokerage_id: str) -> list[dict[str, Any]]:
    """System-default templates + this brokerage's custom templates."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/compliance_templates",
            params={
                "or": f"(brokerage_id.is.null,brokerage_id.eq.{brokerage_id})",
                "select": "*",
                "order": "is_system_default.desc,created_at.asc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_compliance_template(
    brokerage_id: str, template_id: str
) -> dict[str, Any] | None:
    """A template by id — system default or owned by this brokerage."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/compliance_templates",
            params={
                "id": f"eq.{template_id}",
                "or": f"(brokerage_id.is.null,brokerage_id.eq.{brokerage_id})",
                "select": "*",
                "limit": "1",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def find_compliance_template(
    brokerage_id: str, transaction_type: str, state: str | None
) -> dict[str, Any] | None:
    """Best template for a transaction: brokerage custom > system default,
    preferring a state match when present."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/compliance_templates",
            params={
                "transaction_type": f"eq.{transaction_type}",
                "or": f"(brokerage_id.is.null,brokerage_id.eq.{brokerage_id})",
                "select": "*",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    if not rows:
        return None
    st = (state or "").upper()

    def rank(t: dict[str, Any]) -> tuple[int, int]:
        owned = 1 if t.get("brokerage_id") else 0
        state_match = 1 if st and (t.get("state") or "").upper() == st else 0
        return (owned, state_match)

    return max(rows, key=rank)


async def get_template_items(template_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/compliance_template_items",
            params={
                "template_id": f"eq.{template_id}",
                "select": "*",
                "order": "sort_order.asc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def insert_compliance_template(data: dict[str, Any]) -> dict[str, Any]:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/compliance_templates", json=data, headers=headers
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def update_compliance_template(
    brokerage_id: str, template_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/compliance_templates",
            params={"id": f"eq.{template_id}", "brokerage_id": f"eq.{brokerage_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def insert_template_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/compliance_template_items", json=rows, headers=headers
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def delete_template_items(template_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/compliance_template_items",
            params={"template_id": f"eq.{template_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


async def list_checklist_items(transaction_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/transaction_checklist_items",
            params={
                "transaction_id": f"eq.{transaction_id}",
                "select": "*",
                "order": "sort_order.asc,created_at.asc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def insert_checklist_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/transaction_checklist_items", json=rows, headers=headers
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_checklist_item(item_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/transaction_checklist_items",
            params={"id": f"eq.{item_id}", "select": "*", "limit": "1"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def update_checklist_item(
    item_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/transaction_checklist_items",
            params={"id": f"eq.{item_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def delete_checklist_item(item_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/transaction_checklist_items",
            params={"id": f"eq.{item_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


async def checklist_items_in(transaction_ids: list[str]) -> list[dict[str, Any]]:
    """Required-item statuses across many transactions (for list/queue % calc)."""
    if not transaction_ids:
        return []
    ids = ",".join(transaction_ids)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/transaction_checklist_items",
            params={
                "transaction_id": f"in.({ids})",
                "required": "eq.true",
                "select": "transaction_id,status",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


# --------------------------------------------------------------------------- #
# Party consents — AI-disclosure acknowledgments (V2 Section 6)
# --------------------------------------------------------------------------- #

async def list_party_consents(transaction_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/party_consents",
            params={"transaction_id": f"eq.{transaction_id}", "select": "*"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def record_party_consent(data: dict[str, Any]) -> dict[str, Any]:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/party_consents", json=data, headers=headers
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


# --------------------------------------------------------------------------- #
# Transaction emails — outbound + inbound reply threading (V2 Section 4)
# --------------------------------------------------------------------------- #

async def get_transaction_by_id(transaction_id: str) -> dict[str, Any] | None:
    """Look up a transaction by id alone (no brokerage scope) — webhook use only."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/transactions",
            params={"id": f"eq.{transaction_id}", "select": "*", "limit": "1"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def insert_transaction_email(data: dict[str, Any]) -> dict[str, Any]:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/transaction_emails", json=data, headers=headers
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def insert_compliance_feedback(data: dict[str, Any]) -> dict[str, Any]:
    """Record a broker's correct/incorrect verdict on an AI compliance finding
    (BLOCKERS Hard Limit 5 — audit log only, never auto-tunes the model)."""
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/compliance_feedback", json=data, headers=headers
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def list_compliance_feedback(
    brokerage_id: str, transaction_id: str | None = None
) -> list[dict[str, Any]]:
    params = {
        "brokerage_id": f"eq.{brokerage_id}",
        "select": "*",
        "order": "created_at.desc",
    }
    if transaction_id:
        params["transaction_id"] = f"eq.{transaction_id}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/compliance_feedback", params=params, headers=_service_headers()
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def list_transaction_emails(transaction_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/transaction_emails",
            params={
                "transaction_id": f"eq.{transaction_id}",
                "select": "*",
                "order": "received_at.asc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def mark_transaction_emails_read(
    transaction_id: str, user_id: str | None
) -> None:
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/transaction_emails",
            params={
                "transaction_id": f"eq.{transaction_id}",
                "direction": "eq.inbound",
                "read": "eq.false",
            },
            json={"read": True, "read_at": _now_iso(), "read_by": user_id},
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


# --------------------------------------------------------------------------- #
# Workflow task templates + per-transaction tasks (V2 Section 3)
# --------------------------------------------------------------------------- #

async def find_workflow_template(
    brokerage_id: str, transaction_type: str, state: str | None
) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/workflow_templates",
            params={
                "transaction_type": f"eq.{transaction_type}",
                "or": f"(brokerage_id.is.null,brokerage_id.eq.{brokerage_id})",
                "select": "*",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    if not rows:
        return None
    st = (state or "").upper()

    def rank(t: dict[str, Any]) -> tuple[int, int]:
        return (1 if t.get("brokerage_id") else 0,
                1 if st and (t.get("state") or "").upper() == st else 0)

    return max(rows, key=rank)


async def get_workflow_steps(template_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/workflow_steps",
            params={
                "template_id": f"eq.{template_id}",
                "select": "*",
                "order": "sort_order.asc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def list_transaction_tasks(transaction_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/transaction_tasks",
            params={
                "transaction_id": f"eq.{transaction_id}",
                "select": "*",
                "order": "due_date.asc.nullslast,created_at.asc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def insert_transaction_tasks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/transaction_tasks", json=rows, headers=headers
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_transaction_task(task_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/transaction_tasks",
            params={"id": f"eq.{task_id}", "select": "*", "limit": "1"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def update_transaction_task(
    task_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    headers = _service_headers() | {"Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/transaction_tasks",
            params={"id": f"eq.{task_id}"},
            json=data,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def delete_transaction_task(task_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/transaction_tasks",
            params={"id": f"eq.{task_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


async def transaction_tasks_in(transaction_ids: list[str]) -> list[dict[str, Any]]:
    """Pending tasks across many transactions (for overdue badges)."""
    if not transaction_ids:
        return []
    ids = ",".join(transaction_ids)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/transaction_tasks",
            params={
                "transaction_id": f"in.({ids})",
                "status": "eq.pending",
                "select": "transaction_id,due_date,status",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #

async def ensure_bucket(name: str, *, public: bool = False) -> None:
    """Create a storage bucket if it doesn't already exist (idempotent)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{STORAGE_BASE}/bucket",
            json={"id": name, "name": name, "public": public},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        detail = _detail(resp)
        if resp.status_code == 409 or "already exists" in detail.lower():
            return
        raise SupabaseError(resp.status_code, detail)


async def upload_object(bucket: str, path: str, content: bytes, content_type: str) -> str:
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{STORAGE_BASE}/object/{bucket}/{path}", content=content, headers=headers
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return path


async def download_object(bucket: str, path: str) -> bytes:
    """Fetch an object's raw bytes (service-role, bypasses RLS)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{STORAGE_BASE}/object/{bucket}/{path}", headers=_service_headers()
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.content


async def delete_object(bucket: str, path: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{STORAGE_BASE}/object/{bucket}/{path}", headers=_service_headers()
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


async def create_signed_url(bucket: str, path: str, expires_in: int = 3600) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{STORAGE_BASE}/object/sign/{bucket}/{path}",
            json={"expiresIn": expires_in},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    body = resp.json()
    signed = body.get("signedURL") or body.get("signedUrl")
    if signed and signed.startswith("/"):
        return f"{STORAGE_BASE}{signed}"
    return signed


# --------------------------------------------------------------------------- #
# Document routing (Autonomy task `doc-routing`)
# --------------------------------------------------------------------------- #


async def list_doc_routing_rules(
    brokerage_id: str, *, enabled_only: bool = False
) -> list[dict[str, Any]]:
    params = {"brokerage_id": f"eq.{brokerage_id}", "select": "*", "order": "created_at.asc"}
    if enabled_only:
        params["enabled"] = "eq.true"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/doc_routing_rules", params=params, headers=_service_headers()
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_doc_routing_rule(rule_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/doc_routing_rules",
            params={"id": f"eq.{rule_id}", "select": "*", "limit": "1"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def insert_doc_routing_rule(data: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/doc_routing_rules",
            json=data,
            headers=_service_headers() | {"Prefer": "return=representation"},
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else {}


async def update_doc_routing_rule(rule_id: str, data: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/doc_routing_rules",
            params={"id": f"eq.{rule_id}"},
            json=data,
            headers=_service_headers() | {"Prefer": "return=representation"},
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else {}


async def delete_doc_routing_rule(rule_id: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/doc_routing_rules",
            params={"id": f"eq.{rule_id}"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))


async def list_pending_doc_routes(
    brokerage_id: str, *, status_filter: str | None = "pending"
) -> list[dict[str, Any]]:
    params = {
        "brokerage_id": f"eq.{brokerage_id}",
        "select": "*",
        "order": "created_at.desc",
    }
    if status_filter:
        params["status"] = f"eq.{status_filter}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/pending_doc_routes", params=params, headers=_service_headers()
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_pending_doc_route(route_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/pending_doc_routes",
            params={"id": f"eq.{route_id}", "select": "*", "limit": "1"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def list_pending_doc_routes_for_transaction(
    transaction_id: str,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/pending_doc_routes",
            params={"transaction_id": f"eq.{transaction_id}", "select": "*"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def insert_pending_doc_route(data: dict[str, Any]) -> dict[str, Any] | None:
    """Insert a queued/sent route row. Returns None on a unique-constraint
    conflict (the route already exists for this transaction+rule), which makes
    the routing engine idempotent across repeated stage entries."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/pending_doc_routes",
            json=data,
            headers=_service_headers() | {"Prefer": "return=representation"},
        )
    if resp.status_code == 409:
        return None
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def update_pending_doc_route(route_id: str, data: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/pending_doc_routes",
            params={"id": f"eq.{route_id}"},
            json=data,
            headers=_service_headers() | {"Prefer": "return=representation"},
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else {}


# --------------------------------------------------------------------------- #
# Agent lookup by email — used to recognise an inbound email reply as coming
# from one of the brokerage's own agents (vs. an outside party).
# --------------------------------------------------------------------------- #

async def get_agent_by_email(
    brokerage_id: str, email: str
) -> dict[str, Any] | None:
    """Return the brokerage's agent whose email matches (case-insensitive), or None."""
    clean = (email or "").strip()
    if not clean:
        return None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/agents",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "email": f"ilike.{clean}",
                "select": "*",
                "limit": "1",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


# --------------------------------------------------------------------------- #
# Pending email replies — the outside-party suggested-reply approval queue
# (migration 018). Mirrors pending_doc_routes: Penny drafts, the agent
# confirm-sends. Sends to outside parties are never automatic.
# --------------------------------------------------------------------------- #

async def insert_pending_email_reply(data: dict[str, Any]) -> dict[str, Any] | None:
    """Queue a suggested reply. Returns None on a unique-constraint conflict
    (a pending suggestion already exists for this inbound message), keeping the
    inbound handler idempotent across retried Inbound Parse deliveries."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/pending_email_replies",
            json=data,
            headers=_service_headers() | {"Prefer": "return=representation"},
        )
    if resp.status_code == 409:
        return None
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def list_pending_email_replies(
    brokerage_id: str, *, status_filter: str | None = "pending"
) -> list[dict[str, Any]]:
    params = {
        "brokerage_id": f"eq.{brokerage_id}",
        "select": "*",
        "order": "created_at.desc",
    }
    if status_filter:
        params["status"] = f"eq.{status_filter}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/pending_email_replies",
            params=params,
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def get_pending_email_reply(reply_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/pending_email_replies",
            params={"id": f"eq.{reply_id}", "select": "*", "limit": "1"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def list_pending_email_replies_for_transaction(
    transaction_id: str,
) -> list[dict[str, Any]]:
    """All open suggested replies for a deal (awaiting, scheduled, or held)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/pending_email_replies",
            params={
                "transaction_id": f"eq.{transaction_id}",
                "status": "in.(pending,scheduled,awaiting_event,held)",
                "select": "*",
                "order": "created_at.desc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


async def update_pending_email_reply(
    reply_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(
            f"{REST_BASE}/pending_email_replies",
            params={"id": f"eq.{reply_id}"},
            json=data,
            headers=_service_headers() | {"Prefer": "return=representation"},
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else {}


async def list_email_replies_by_statuses(
    brokerage_id: str, statuses: list[str]
) -> list[dict[str, Any]]:
    """Armed/held suggested replies for the scheduled-reply scan."""
    joined = ",".join(statuses)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/pending_email_replies",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "status": f"in.({joined})",
                "select": "*",
                "order": "created_at.asc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()
