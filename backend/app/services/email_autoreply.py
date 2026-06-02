"""Email as a two-way channel (Phase 1).

Section 4 originally logged inbound replies and nudged the agent, but never
replied — Sloane was draft-only on email. Realtors answer in the medium a
message arrives in, so this lets email act as an input channel, with two
deliberately-scoped, brokerage-opt-in behaviors (both default ON, migration 018):

- ``email_agent_autoreply_enabled`` — when one of the brokerage's OWN agents
  emails Sloane about a deal, run her normal agent loop and reply by email. The
  agent is the brokerage's own person, so this is low risk and the closest email
  equivalent of the WhatsApp/web chat channels.
- ``email_outside_draft_enabled`` — when an OUTSIDE party emails, Sloane never
  auto-sends. She drafts a suggested reply into ``pending_email_replies`` for the
  agent to review and confirm-send. The human gate on outside comms is preserved.

Everything here is best-effort: the inbound webhook must still return 200 so
SendGrid stops retrying, so callers wrap this and never let it raise.
"""

import asyncio
import html as _html
import re
from typing import Any

from app.config import settings
from app.core import supabase_client as sb
from app.services import doc_generate, email_client, sloane_agent

# Senders we never auto-respond to (delivery bots, no-reply mailboxes, lists).
_AUTOMATED_LOCALPART_RE = re.compile(
    r"(^|[._-])(mailer-daemon|postmaster|no-?reply|do-?not-?reply|bounce|notifications?)",
    re.IGNORECASE,
)


def _is_automated(raw_form: dict[str, str], sender_email: str, sloane_from: str) -> bool:
    """True if the inbound message looks machine-generated (so we stay silent).

    Guards against reply loops and noise: our own outbound address, no-reply/
    mailer-daemon senders, and anything carrying auto-responder / bulk headers.
    """
    addr = (sender_email or "").strip().lower()
    if not addr:
        return True
    if sloane_from and addr == sloane_from.strip().lower():
        return True
    local = addr.split("@", 1)[0]
    if _AUTOMATED_LOCALPART_RE.search(local):
        return True
    headers = (raw_form.get("headers") or "").lower()
    if "auto-submitted:" in headers and "auto-submitted: no" not in headers:
        return True
    if re.search(r"precedence:\s*(bulk|list|auto_reply|junk)", headers):
        return True
    return False


def _html_wrap(text: str) -> str:
    """Render a plain-text reply body as a simple, safe HTML email body."""
    escaped = _html.escape(text)
    return (
        '<html><body><div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        "white-space:pre-wrap;color:#111827;font-size:15px;line-height:1.6;\">"
        f"{escaped}</div></body></html>"
    )


def _reply_subject(subject: str | None) -> str:
    s = (subject or "").strip()
    if not s:
        return "Re: your message"
    return s if s[:3].lower() == "re:" else f"Re: {s}"


def _history_from_emails(
    emails: list[dict[str, Any]], exclude_id: str | None
) -> list[dict[str, Any]]:
    """Map logged transaction emails to the agent loop's history shape."""
    history: list[dict[str, Any]] = []
    for e in emails:
        if exclude_id and e.get("id") == exclude_id:
            continue
        body = (e.get("body_text") or "").strip()
        if not body:
            continue
        history.append({"direction": e.get("direction", "inbound"), "body": body})
    return history[-20:]


async def maybe_autorespond(
    *,
    tx: dict[str, Any],
    brokerage: dict[str, Any],
    inbound_email_id: str | None,
    sender_name: str | None,
    sender_email: str | None,
    subject: str | None,
    body_text: str,
    raw_form: dict[str, str],
) -> str:
    """Reply to an internal agent, or draft a suggestion for an outside party.

    Returns one of:
      'agent_replied'   — Sloane emailed an internal agent back.
      'outside_drafted' — a suggested reply was queued for agent approval.
      'skipped'         — nothing auto-sent (disabled, automated sender, no key,
                          or an error). The caller should still nudge normally.
    """
    sloane_from = email_client.from_email() or ""
    if _is_automated(raw_form, sender_email or "", sloane_from):
        return "skipped"
    if not settings.ANTHROPIC_API_KEY:
        # Without a model we can neither reply nor draft sensibly.
        return "skipped"

    brokerage_id = tx["brokerage_id"]
    brokerage_name = brokerage.get("name", "your brokerage")

    # Is the sender one of the brokerage's own agents?
    try:
        internal_agent = await sb.get_agent_by_email(brokerage_id, sender_email or "")
    except sb.SupabaseError:
        internal_agent = None

    # ── Internal agent → reply in-thread with the normal agent loop ────────── #
    if internal_agent and brokerage.get("email_agent_autoreply_enabled"):
        try:
            emails = await sb.list_transaction_emails(tx["id"])
        except sb.SupabaseError:
            emails = []
        history = _history_from_emails(emails, inbound_email_id)
        try:
            reply = await sloane_agent.run_sloane_agent(
                brokerage_id=brokerage_id,
                brokerage_name=brokerage_name,
                contact_display_name=(internal_agent.get("name") or sender_name),
                history=history,
                current_message=body_text,
                agent_id=internal_agent.get("id"),
                channel="email",
            )
        except Exception:  # noqa: BLE001 — never break the webhook
            return "skipped"
        reply = (reply or "").strip()
        if not reply:
            return "skipped"
        html_body = _html_wrap(reply)
        sent = await asyncio.to_thread(
            email_client.send_email,
            to_emails=[sender_email],
            subject=_reply_subject(subject),
            html=html_body,
            plain=reply,
            reply_to=email_client.reply_to_address(tx["id"]),
            disclosure=email_client.disclosure_text(brokerage),
        )
        if not sent:
            return "skipped"
        try:
            await sb.insert_transaction_email(
                {
                    "transaction_id": tx["id"],
                    "direction": "outbound",
                    "sender_email": email_client.from_email(),
                    "recipient_emails": [sender_email],
                    "subject": _reply_subject(subject),
                    "body_text": reply,
                    "body_html": html_body,
                    "read": True,
                }
            )
        except sb.SupabaseError:
            pass  # logging is best-effort
        return "agent_replied"

    # ── Outside party → draft a suggested reply for the agent to approve ───── #
    if (not internal_agent) and brokerage.get("email_outside_draft_enabled"):
        try:
            rules = await sb.get_confirmed_knowledge_rules(
                brokerage_id, tx.get("agent_id")
            )
        except sb.SupabaseError:
            rules = []
        who = sender_name or sender_email or "the other party"
        instructions = (
            f"An outside party ({who}) replied to us by email about this "
            "transaction. Draft a reply to their message below in the brokerage's "
            "voice. Be helpful and professional, but do NOT invent facts, make "
            "commitments, or quote terms that aren't in the record — where the "
            "agent needs to decide or supply something, leave a clearly bracketed "
            f"[placeholder]. Their message:\n\n{body_text}"
        )
        try:
            draft = await doc_generate.generate_document(
                transaction=tx,
                doc_type="custom",
                brokerage_name=brokerage_name,
                style_rules=rules,
                recipient=who,
                instructions=instructions,
            )
        except (doc_generate.DocNotConfigured, doc_generate.DocGenerationError):
            return "skipped"
        except Exception:  # noqa: BLE001
            return "skipped"
        try:
            await sb.insert_pending_email_reply(
                {
                    "brokerage_id": brokerage_id,
                    "transaction_id": tx["id"],
                    "inbound_email_id": inbound_email_id,
                    "to_email": sender_email,
                    "to_name": sender_name,
                    "subject": draft.get("subject") or _reply_subject(subject),
                    "draft_body": draft.get("body") or "",
                }
            )
        except sb.SupabaseError:
            return "skipped"
        return "outside_drafted"

    return "skipped"
