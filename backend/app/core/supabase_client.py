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


async def get_confirmed_knowledge_rules(brokerage_id: str) -> list[dict[str, Any]]:
    """Confirmed brokerage style rules, injected into AI system prompts."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/knowledge_rules",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "confirmed": "eq.true",
                "select": "category,rule",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


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
# WhatsApp contacts
# --------------------------------------------------------------------------- #

async def lookup_whatsapp_contact(phone_number: str) -> dict[str, Any] | None:
    """Find a brokerage by a registered realtor phone number."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/whatsapp_contacts",
            params={"phone_number": f"eq.{phone_number}", "select": "*", "limit": "1"},
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if rows else None


async def list_whatsapp_contacts(brokerage_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/whatsapp_contacts",
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


async def upsert_whatsapp_contact(
    brokerage_id: str, phone_number: str, display_name: str | None = None
) -> dict[str, Any]:
    payload = {"brokerage_id": brokerage_id, "phone_number": phone_number}
    if display_name is not None:
        payload["display_name"] = display_name
    headers = _service_headers() | {
        "Prefer": "return=representation,resolution=merge-duplicates",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{REST_BASE}/whatsapp_contacts",
            json=payload,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


async def delete_whatsapp_contact(brokerage_id: str, phone_number: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{REST_BASE}/whatsapp_contacts",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "phone_number": f"eq.{phone_number}",
            },
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
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/knowledge_documents",
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


async def list_knowledge_rules(brokerage_id: str) -> list[dict[str, Any]]:
    """All style rules for review — confirmed and pending, newest first."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{REST_BASE}/knowledge_rules",
            params={
                "brokerage_id": f"eq.{brokerage_id}",
                "select": "id,category,rule,confirmed,document_id,source_document,created_at",
                "order": "created_at.desc",
            },
            headers=_service_headers(),
        )
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _detail(resp))
    return resp.json()


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
