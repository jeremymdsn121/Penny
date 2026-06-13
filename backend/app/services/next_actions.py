"""Next-action synthesis — the single source of truth behind Penny's
"what should I do?" answers and the home-page briefing.

Cross-references pending workflow tasks, missing required checklist items, EMD
status, upcoming deadlines, and missing party contacts across a brokerage's
active deals into a prioritized list of concrete next moves. This module is
pure data: it returns action dicts and the caller decides how to present them —
``penny_agent`` reads them aloud in chat; the ``/briefing/next-actions`` route
renders them as clickable cards.

Each action dict carries:
  - ``priority``       : int, lower = surfaces first
  - ``transaction_id`` : the deal it belongs to
  - ``address``        : human label for the deal
  - ``headline``       : what's wrong / due (UI display)
  - ``offer``          : what Penny can do about it, first person (UI display)
  - ``prompt``         : the message to send Penny when the user clicks "do it"

Self-contained — depends only on stdlib + the Supabase client, so it can be
imported from both the agent and the route layer without a circular import.
"""

import asyncio
import hashlib
from datetime import date
from typing import Any

from app.core import supabase_client as sb

# Priority bands — lower number surfaces first.
P_EMD_OVERDUE = 1
P_TASK_OVERDUE = 1
P_COMPLIANCE_ATTENTION = 1
P_DEADLINE_IMMINENT = 2  # unresolved, due in <= 2 days
P_TASK_DUE_TODAY = 2
P_CHECKLIST_GAP_NEAR_CLOSING = 2  # required item missing + closing <= 14d
P_TASK_DUE_THIS_WEEK = 3
P_DEADLINE_THIS_WEEK = 3
P_MISSING_PARTY_EMAIL = 4

ACTIVE_STAGES = ("under_contract", "pending")


def _fmt_date(value: Any) -> str:
    if not value:
        return "not set"
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%b %d, %Y")
    except ValueError:
        return str(value)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _short_address(tx: dict[str, Any]) -> str:
    addr = (tx.get("address") or "").split(",")[0].strip()
    return addr or "this deal"


# --- Phrasing variety ------------------------------------------------------ #
# Recurring tasks otherwise read identically on every deal ("Send intro email to
# all parties" everywhere). These give a deal-stable but varied phrasing —
# _pick is seeded by transaction id, so wording differs across deals and doesn't
# flicker between refreshes of the same one. Prompts (sent to Penny) stay fixed.

def _pick(options: list[str], *seed_parts: object) -> str:
    if not options:
        return ""
    seed = "|".join(str(p) for p in seed_parts)
    idx = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(options)
    return options[idx]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _task_kind(label: str) -> str | None:
    lower = (label or "").lower()
    if "intro" in lower or "introduction" in lower:
        return "intro"
    if "earnest" in lower or "emd" in lower:
        return "emd"
    return None


# Noun phrase for a recognised task, dropped into "<subject> is due …" headlines.
_TASK_SUBJECTS: dict[str, list[str]] = {
    "intro": [
        "the intro email to all parties",
        "the intro that introduces everyone on the deal",
        "the kickoff intro email",
        "introductions for everyone on the file",
    ],
    "emd": [
        "the earnest money receipt",
        "confirming the earnest money landed",
        "the EMD receipt",
        "the earnest money confirmation",
    ],
}

_TASK_OFFERS: dict[str, list[str]] = {
    "intro": [
        "preview the intro email so you can send it",
        "pull up the intro email to introduce everyone",
        "get the intro ready for your review",
        "draft the all-parties intro for you to send",
    ],
    "emd": [
        "check EMD status, or draft an email to title for the receipt",
        "look up where earnest money stands and chase the receipt",
        "pull the EMD status and nudge title if it's still out",
    ],
}

# The EMD-overdue card (separate from a workflow task).
_EMD_OVERDUE_HEADLINES = [
    "EMD is {days} overdue on {address}",
    "Still waiting on the earnest money receipt for {address} — {days} past due",
    "Earnest money receipt is {days} overdue on {address}",
    "{address} hasn't logged its EMD receipt yet — {days} overdue",
]
_EMD_OVERDUE_OFFERS = [
    "draft an email to title asking for the receipt",
    "email the title company to chase the receipt",
    "nudge title for the earnest money receipt",
]


def action_for_task_label(label: str, address: str, seed: str = "") -> tuple[str, str]:
    """Map a workflow-task label to (offer, prompt).

    ``offer`` is first-person prose for display (varied per ``seed`` for
    recognised task kinds); ``prompt`` is the imperative message sent to Penny
    when the user clicks to act on it.
    """
    lower = (label or "").lower()
    if "inspection" in lower and "objection" not in lower:
        return (
            "propose inspection times for the buyer",
            f"Propose inspection times for {address}",
        )
    if "walkthrough" in lower or "final walk" in lower:
        return (
            "propose times for the final walkthrough",
            f"Propose final walkthrough times for {address}",
        )
    if "appraisal" in lower:
        return (
            "draft an email to the lender about appraisal scheduling",
            f"Draft an email to the lender about appraisal scheduling for {address}",
        )
    if "lender" in lower or "loan" in lower or "financing" in lower:
        return (
            "draft an email to the lender",
            f"Draft an email to the lender on {address}",
        )
    if "intro" in lower or "introduction" in lower:
        return (
            _pick(_TASK_OFFERS["intro"], seed, "intro"),
            f"Preview the intro email for {address}",
        )
    if "earnest" in lower or "emd" in lower:
        return (
            _pick(_TASK_OFFERS["emd"], seed, "emd"),
            f"What's the EMD status on {address}?",
        )
    if "title" in lower or "settlement" in lower or "closing" in lower:
        return (
            "draft an email to title",
            f"Draft an email to the title company on {address}",
        )
    if "hoa" in lower:
        return (
            "draft an email to the listing agent for HOA docs",
            f"Draft an email to the listing agent on {address} requesting HOA documents",
        )
    if "disclosure" in lower:
        return (
            "draft an email to the listing agent for the disclosure",
            f"Draft an email to the listing agent on {address} about the disclosure",
        )
    return (
        "draft an email or schedule a time — tell me which",
        f'What should I do about "{label}" on {address}?',
    )


async def collect_for_transaction(tx: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every actionable item on one transaction."""
    actions: list[dict[str, Any]] = []
    tx_id = tx.get("id")
    address = _short_address(tx)
    today = date.today()

    def add(priority: int, headline: str, offer: str, prompt: str) -> None:
        actions.append({
            "priority": priority,
            "transaction_id": tx_id,
            "address": address,
            "headline": headline,
            "offer": offer,
            "prompt": prompt,
        })

    # 1. Compliance flagged
    if tx.get("compliance_status") == "needs_attention":
        add(
            P_COMPLIANCE_ATTENTION,
            f"Compliance is flagged on {address}",
            "run a compliance review so you can sign off",
            f"Run a compliance review on {address}",
        )

    # 2. EMD overdue
    emd_due = _parse_date(tx.get("emd_due_date"))
    if emd_due and not tx.get("emd_received") and emd_due < today:
        days_over = (today - emd_due).days
        days_str = f"{days_over} day{'s' if days_over != 1 else ''}"
        if tx.get("title_email"):
            offer = _pick(_EMD_OVERDUE_OFFERS, tx_id, "emd_overdue_offer")
            prompt = f"Draft an email to the title company on {address} requesting the earnest money receipt"
        else:
            offer = "check EMD status — there's no title email on file to chase it"
            prompt = f"What's the EMD status on {address}?"
        headline = _pick(_EMD_OVERDUE_HEADLINES, tx_id, "emd_overdue").format(
            days=days_str, address=address
        )
        add(P_EMD_OVERDUE, headline, offer, prompt)

    # 3. Pending workflow tasks, bucketed by urgency
    try:
        tasks = await sb.list_transaction_tasks(tx_id)
    except Exception:  # noqa: BLE001 — synthesis is best-effort
        tasks = []
    for t in tasks:
        if t.get("status") != "pending":
            continue
        d = _parse_date(t.get("due_date"))
        if d is None:
            continue  # undated tasks stay out of the synthesis
        label = t.get("label") or "a task"
        offer, prompt = action_for_task_label(label, address, seed=str(tx_id or ""))
        # Vary the subject for recognised kinds so the headline doesn't echo the
        # same static label everywhere; fall back to the quoted label otherwise.
        kind = _task_kind(label)
        subject = _cap(_pick(_TASK_SUBJECTS[kind], tx_id, kind)) if kind else f"'{label}'"
        days_to = (d - today).days
        if days_to < 0:
            add(
                P_TASK_OVERDUE,
                f"{subject} is overdue on {address} (was due {_fmt_date(t.get('due_date'))})",
                offer,
                prompt,
            )
        elif days_to == 0:
            add(P_TASK_DUE_TODAY, f"{subject} is due today on {address}", offer, prompt)
        elif days_to <= 7:
            add(
                P_TASK_DUE_THIS_WEEK,
                f"{subject} is due in {days_to} day{'s' if days_to != 1 else ''} on {address}",
                offer,
                prompt,
            )

    # 4. Upcoming deadlines (next 7 days, unresolved)
    try:
        deadlines = await sb.list_deadlines_in([tx_id])
    except Exception:  # noqa: BLE001
        deadlines = []
    for dl in deadlines:
        if dl.get("resolved"):
            continue
        due_d = _parse_date(dl.get("due_date"))
        if due_d is None:
            continue
        days_to = (due_d - today).days
        if days_to < 0 or days_to > 7:
            continue
        label = dl.get("label") or "A deadline"
        prompt = f"Notify the responsible parties for the {label} deadline on {address}"
        if days_to <= 2:
            when = "today" if days_to == 0 else ("tomorrow" if days_to == 1 else f"in {days_to} days")
            add(
                P_DEADLINE_IMMINENT,
                f"{label} deadline is {when} on {address}",
                "notify the responsible parties (you confirm before it sends)",
                prompt,
            )
        else:
            add(
                P_DEADLINE_THIS_WEEK,
                f"{label} deadline is in {days_to} days on {address}",
                "notify the responsible parties when you're ready",
                prompt,
            )

    # 5. Missing required checklist items, weighted by closing proximity
    closing_d = _parse_date(tx.get("closing_date"))
    if closing_d is not None and 0 <= (closing_d - today).days <= 14:
        try:
            items = await sb.list_checklist_items(tx_id)
        except Exception:  # noqa: BLE001
            items = []
        missing = [
            i for i in items
            if i.get("required")
            and i.get("status") not in ("complete", "waived", "not_applicable")
        ]
        if missing:
            d2c = (closing_d - today).days
            add(
                P_CHECKLIST_GAP_NEAR_CLOSING,
                (
                    f"{len(missing)} required file item{'s' if len(missing) != 1 else ''} "
                    f"still missing on {address}, closing in {d2c} day{'s' if d2c != 1 else ''}"
                ),
                "show what's missing and who to chase",
                f"What's missing on {address}?",
            )

    # 6. Missing party emails on active deals
    if (tx.get("stage") or "under_contract") in ACTIVE_STAGES:
        for field, role in (("lender_email", "lender"), ("title_email", "title company")):
            if not tx.get(field):
                add(
                    P_MISSING_PARTY_EMAIL,
                    f"No {role} email on file for {address}",
                    f"once you add the {role}'s email I can reach them directly",
                    f"How do I add the {role} email for {address}?",
                )

    return actions


async def collect_for_brokerage(brokerage_id: str) -> list[dict[str, Any]]:
    """Synthesize actions across every active deal in the brokerage."""
    txs = await sb.list_transactions(brokerage_id)
    active = [t for t in txs if (t.get("stage") or "under_contract") in ACTIVE_STAGES]
    if not active:
        return []
    per_deal = await asyncio.gather(*(collect_for_transaction(t) for t in active))
    return [a for deal in per_deal for a in deal]


def top_actions(
    actions: list[dict[str, Any]], limit: int = 3
) -> tuple[list[dict[str, Any]], int]:
    """Sort by priority and return (top ``limit``, count of the remainder)."""
    ordered = sorted(actions, key=lambda a: a["priority"])
    top = ordered[:limit]
    return top, max(0, len(ordered) - len(top))
