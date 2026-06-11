"""Per-deal activity audit trail.

A thin, best-effort recorder for the actions that previously left no history
(stage changes, compliance decisions, EMD receipt, autonomous/confirmed sends).
``record`` never raises into the caller: an audit write failing — including the
table not existing before migration 026 is applied — must not break the action
being audited. The timeline endpoint (routes/email.py? no — routes/transactions)
merges these rows with the already-timestamped logs (emails, delivery events,
appointments) into one feed.
"""

import logging
from typing import Any

from app.core import supabase_client as sb

logger = logging.getLogger(__name__)


async def record(
    *,
    brokerage_id: str | None,
    transaction_id: str | None,
    kind: str,
    title: str,
    detail: str | None = None,
    actor: str = "Penny",
    via: str = "system",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append one timeline event. Best-effort — swallows all failures."""
    if not brokerage_id or not transaction_id:
        return
    try:
        await sb.insert_transaction_event(
            {
                "brokerage_id": brokerage_id,
                "transaction_id": transaction_id,
                "kind": kind,
                "title": title,
                "detail": detail,
                "actor": actor,
                "via": via,
                "metadata": metadata or {},
            }
        )
    except Exception as exc:  # noqa: BLE001 — auditing never blocks the action
        logger.warning("activity.record(%s) failed for tx %s: %s", kind, transaction_id, exc)


def _fmt_dt(iso: str | None) -> str | None:
    """Reformat a stored ISO timestamp to a readable wall-clock string, keeping
    the stored offset as-is (no timezone conversion — display only)."""
    if not iso:
        return None
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y at %I:%M %p").replace(" 0", " ")
    except ValueError:
        return str(iso)


def _entry(at: str | None, kind: str, title: str, detail: str | None,
           actor: str, via: str) -> dict[str, Any] | None:
    """One normalised timeline row, or None when it has no timestamp to sort by."""
    if not at:
        return None
    return {"at": at, "kind": kind, "title": title, "detail": detail,
            "actor": actor, "via": via}


def build_timeline(
    *,
    events: list[dict[str, Any]],
    emails: list[dict[str, Any]],
    delivery: list[dict[str, Any]],
    appointments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge the audit trail with the already-timestamped logs into one feed,
    newest first. The audit table covers actions with no prior history (stage
    changes, decisions, EMD, autonomous sends); emails / delivery events /
    appointments are pulled straight from their own tables so the timeline is
    complete without double-recording them into the audit table."""
    rows: list[dict[str, Any]] = []

    for e in events:
        rows.append(_entry(
            e.get("created_at"), e.get("kind") or "event",
            e.get("title") or "", e.get("detail"),
            e.get("actor") or "Penny", e.get("via") or "system",
        ))

    for m in emails:
        outbound = m.get("direction") == "outbound"
        who = m.get("sender_name") or m.get("sender_email") or "someone"
        if outbound:
            to = ", ".join(m.get("recipient_emails") or []) or "the parties"
            title, detail, actor = f"Email sent to {to}", m.get("subject"), "Penny"
        else:
            title, detail, actor = f"Reply received from {who}", m.get("subject"), who
        rows.append(_entry(
            m.get("received_at"), "email_out" if outbound else "email_in",
            title, detail, actor, "email",
        ))

    for d in delivery:
        ev = d.get("event")
        verb = "marked spam" if ev == "spamreport" else "bounced" if ev == "bounce" else "was dropped"
        rows.append(_entry(
            d.get("created_at"), "delivery_problem",
            f"Email to {d.get('email')} {verb}", d.get("reason"),
            "System", "email",
        ))

    for a in appointments:
        when = _fmt_dt(a.get("scheduled_at"))
        rows.append(_entry(
            a.get("created_at") or a.get("scheduled_at"), "appointment",
            f"{(a.get('type') or 'appointment').replace('_', ' ').title()} scheduled",
            f"for {when}" if when else None, "Penny", "system",
        ))

    # Newest first; missing-timestamp rows already filtered by _entry.
    return sorted((r for r in rows if r), key=lambda r: r["at"], reverse=True)
