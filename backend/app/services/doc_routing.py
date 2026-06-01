"""Document routing engine (Autonomy task ``doc-routing``).

When a transaction enters a stage, any enabled routing rule whose ``trigger_stage``
matches fires: Sloane resolves the rule's recipient roles to email addresses on the
deal, grabs the source document (the contract PDF for now), and either

  * sends it immediately — only when the brokerage's ``doc-routing`` task is
    autonomous (the same opt-in gate as intro emails), or
  * queues a ``pending_doc_routes`` row and WhatsApp-nudges the deal's agent, who
    approves the send in one click (the confirm-gated default).

Sending a document is a hard-rule confirmation-gated action; the autonomy toggle is
the *only* thing that lets the immediate path run without a human. Idempotent: the
``(transaction_id, rule_id)`` unique index means re-entering a stage won't re-route.
"""

import asyncio
from typing import Any

from app.core import supabase_client as sb
from app.services import email_client, twilio_client

CONTRACTS_BUCKET = "contracts"

# Role key -> (name field, email field) on the transaction record.
_ROLE_FIELDS: dict[str, tuple[str, str]] = {
    "buyer": ("buyer_name", "buyer_email"),
    "seller": ("seller_name", "seller_email"),
    "listing_agent": ("listing_agent_name", "listing_agent_email"),
    "selling_agent": ("selling_agent_name", "selling_agent_email"),
    "lender": ("lender_name", "lender_email"),
    "title": ("title_company", "title_email"),
    "tc": ("tc_name", "tc_email"),
}

# Validation sets shared by the rules API. Stages are the transaction stages used
# across the app (NewTransaction selector, broker.ACTIVE_STAGES, migration 011
# stage_entry triggers) — not deadline labels like "inspection"/"appraisal".
VALID_ROLES: set[str] = set(_ROLE_FIELDS)
VALID_STAGES: set[str] = {"under_contract", "pending", "closed", "cancelled"}
VALID_DOCUMENT_SOURCES: set[str] = {"contract"}


def resolve_recipient_emails(tx: dict[str, Any], roles: list[str]) -> list[str]:
    """Map role keys to email addresses present on the transaction (deduped)."""
    seen: set[str] = set()
    out: list[str] = []
    for role in roles:
        _, email_f = _ROLE_FIELDS.get(role, ("", ""))
        if not email_f:
            continue
        email = (tx.get(email_f) or "").strip()
        low = email.lower()
        if email and low not in seen:
            seen.add(low)
            out.append(email)
    return out


def _document_filename(tx: dict[str, Any], source: str) -> str:
    addr = (tx.get("address") or "document").strip() or "document"
    safe = "".join(c if (c.isalnum() or c in " -_") else "_" for c in addr).strip()
    label = "contract" if source == "contract" else source
    return f"{safe} - {label}.pdf"


def _document_path(tx: dict[str, Any], source: str) -> str | None:
    if source == "contract":
        return (tx.get("contract_pdf_url") or "").strip() or None
    return None


async def _is_autonomous(brokerage_id: str) -> bool:
    try:
        autonomy = await sb.get_task_autonomy(brokerage_id)
    except sb.SupabaseError:
        return False
    return any(
        r.get("task_id") == "doc-routing" and r.get("autonomous") for r in autonomy
    )


async def _nudge_agent(tx: dict[str, Any], route: dict[str, Any], roles: list[str]) -> None:
    """WhatsApp the deal's agent that a routing send is waiting for approval."""
    address = tx.get("address") or "a transaction"
    role_list = ", ".join(roles) if roles else "the selected parties"
    msg = (
        f"📄 {address} entered {route.get('trigger_stage')}.\n"
        f"Sloane has the contract ready to send to {role_list}.\n\n"
        "Approve the send in the Sloane dashboard (Document routing)."
    )
    try:
        contacts = await sb.list_whatsapp_contacts(tx["brokerage_id"])
    except sb.SupabaseError:
        return
    agent_id = tx.get("agent_id")
    recipients = (
        [c for c in contacts if c.get("agent_id") == agent_id] if agent_id else contacts
    )
    for c in recipients:
        phone = c.get("phone_number")
        if not phone:
            continue
        try:
            await asyncio.to_thread(twilio_client.send_whatsapp_message, phone, msg)
        except twilio_client.TwilioNotConfigured:
            break
        except Exception:  # noqa: BLE001 — nudges are best-effort
            pass


async def _send_route(
    tx: dict[str, Any], document_url: str | None, source: str, emails: list[str]
) -> bool:
    """Download the source document and email it to the recipients. Best-effort."""
    if not emails or not document_url:
        return False
    try:
        content = await sb.download_object(CONTRACTS_BUCKET, document_url)
    except sb.SupabaseError:
        return False
    address = tx.get("address") or "your transaction"
    subject = f"Documents for {address}"
    body = (
        f"Please find the contract for {address} attached. "
        "Reply to this email with any questions."
    )
    html = f"<p>{body}</p>"
    sent = await asyncio.to_thread(
        email_client.send_email,
        to_emails=emails,
        subject=subject,
        html=html,
        plain=body,
        reply_to=email_client.reply_to_address(tx.get("id")),
        attachments=[
            {
                "content": content,
                "filename": _document_filename(tx, source),
                "type": "application/pdf",
            }
        ],
    )
    if sent and tx.get("id"):
        try:
            await sb.insert_transaction_email(
                {
                    "transaction_id": tx["id"],
                    "direction": "outbound",
                    "recipient_emails": emails,
                    "subject": subject,
                    "body_text": body,
                }
            )
        except Exception:  # noqa: BLE001
            pass
    return sent


async def run_stage_routing(tx: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    """Fire matching routing rules for a transaction entering ``stage``.

    Returns the rows created in ``pending_doc_routes`` (queued or sent). Idempotent
    and best-effort — never raises into the caller's request path.
    """
    brokerage_id = tx.get("brokerage_id")
    if not brokerage_id or not stage:
        return []
    try:
        rules = await sb.list_doc_routing_rules(brokerage_id, enabled_only=True)
    except sb.SupabaseError:
        return []
    matching = [r for r in rules if r.get("trigger_stage") == stage]
    if not matching:
        return []

    autonomous = await _is_autonomous(brokerage_id)
    created: list[dict[str, Any]] = []
    for rule in matching:
        roles = rule.get("recipient_roles") or []
        source = rule.get("document_source") or "contract"
        emails = resolve_recipient_emails(tx, roles)
        document_url = _document_path(tx, source)

        row = {
            "brokerage_id": brokerage_id,
            "transaction_id": tx["id"],
            "rule_id": rule["id"],
            "trigger_stage": stage,
            "document_source": source,
            "document_url": document_url,
            "recipient_roles": roles,
            "recipient_emails": emails,
            "status": "pending",
        }

        if autonomous and emails and document_url:
            sent = await _send_route(tx, document_url, source, emails)
            row["status"] = "sent" if sent else "pending"

        inserted = await sb.insert_pending_doc_route(row)
        if inserted is None:
            continue  # already routed for this (transaction, rule)
        created.append(inserted)

        # Not sent (autonomy off, or send failed / nothing to send): tell the agent.
        if inserted.get("status") != "sent":
            await _nudge_agent(tx, inserted, roles)

    return created


async def send_pending_route(
    route: dict[str, Any], tx: dict[str, Any]
) -> tuple[bool, str | None]:
    """Send a queued route after human confirmation. Returns (sent, reason)."""
    emails = route.get("recipient_emails") or resolve_recipient_emails(
        tx, route.get("recipient_roles") or []
    )
    if not emails:
        return False, "no recipient email addresses on file for the selected parties"
    document_url = route.get("document_url") or _document_path(
        tx, route.get("document_source") or "contract"
    )
    if not document_url:
        return False, "no document on file to send"
    sent = await _send_route(
        tx, document_url, route.get("document_source") or "contract", emails
    )
    return (sent, None if sent else "SendGrid not configured or the send failed")
