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
from app.services import email_client

# Priority bands — lower number surfaces first.
P_EMD_OVERDUE = 1
P_TASK_OVERDUE = 1
P_COMPLIANCE_ATTENTION = 1
P_DEADLINE_IMMINENT = 2  # unresolved, due in <= 2 days
P_TASK_DUE_TODAY = 2
P_CHECKLIST_GAP_NEAR_CLOSING = 2  # required item missing + closing <= 14d
P_TASK_DUE_THIS_WEEK = 3
P_DEADLINE_THIS_WEEK = 3
P_INTRO_NEEDED = 3  # under contract, group not yet introduced
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
    """Classify a workflow-task label into a phrasing bucket (order matters)."""
    lower = (label or "").lower()
    if "inspection" in lower and "objection" not in lower:
        return "inspection"
    if "walkthrough" in lower or "final walk" in lower:
        return "walkthrough"
    if "appraisal" in lower:
        return "appraisal"
    if "lender" in lower or "loan" in lower or "financing" in lower:
        return "financing"
    if "intro" in lower or "introduction" in lower:
        return "intro"
    if "earnest" in lower or "emd" in lower:
        return "emd"
    if "title" in lower or "settlement" in lower or "closing" in lower:
        return "title"
    if "hoa" in lower:
        return "hoa"
    if "disclosure" in lower:
        return "disclosure"
    return None


# Noun phrase for a recognised task, dropped into "<subject> is due …" headlines.
_TASK_SUBJECTS: dict[str, list[str]] = {
    "inspection": [
        "the home inspection",
        "getting the inspection scheduled",
        "the buyer's inspection",
        "booking the inspection",
    ],
    "walkthrough": [
        "the final walkthrough",
        "scheduling the final walkthrough",
        "the buyer's final walk-through",
    ],
    "appraisal": [
        "the appraisal",
        "getting the appraisal ordered",
        "the lender's appraisal",
    ],
    "financing": [
        "the financing check-in",
        "the loan status",
        "following up with the lender",
        "the financing update",
    ],
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
    "title": [
        "the title company follow-up",
        "looping in title",
        "the title coordination",
        "the closing-side title check-in",
    ],
    "hoa": [
        "the HOA documents",
        "tracking down the HOA docs",
        "the HOA paperwork",
    ],
    "disclosure": [
        "the seller's disclosure",
        "the disclosure follow-up",
        "the property disclosure",
    ],
}

_TASK_OFFERS: dict[str, list[str]] = {
    "inspection": [
        "propose inspection times for the buyer",
        "find open inspection times to send the buyer",
        "line up inspection slots for the buyer",
        "pull a few inspection times to propose",
    ],
    "walkthrough": [
        "propose times for the final walkthrough",
        "find final walkthrough times to send",
        "line up the final walk-through",
    ],
    "appraisal": [
        "draft an email to the lender about appraisal scheduling",
        "email the lender to get the appraisal moving",
        "nudge the lender on the appraisal",
    ],
    "financing": [
        "draft an email to the lender",
        "check in with the lender by email",
        "draft a financing follow-up to the lender",
    ],
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
    "title": [
        "draft an email to title",
        "email the title company for you",
        "reach out to title to keep things moving",
    ],
    "hoa": [
        "draft an email to the listing agent for HOA docs",
        "email the listing agent to request the HOA documents",
        "ask the listing agent for the HOA paperwork",
    ],
    "disclosure": [
        "draft an email to the listing agent for the disclosure",
        "email the listing agent about the disclosure",
        "request the disclosure from the listing agent",
    ],
}


def _task_prompt(kind: str | None, label: str, address: str) -> str:
    """The imperative message sent to Penny on click — fixed per kind (stability
    matters here; only the displayed wording varies)."""
    return {
        "inspection": f"Propose inspection times for {address}",
        "walkthrough": f"Propose final walkthrough times for {address}",
        "appraisal": f"Draft an email to the lender about appraisal scheduling for {address}",
        "financing": f"Draft an email to the lender on {address}",
        "intro": f"Preview the intro email for {address}",
        "emd": f"What's the EMD status on {address}?",
        "title": f"Draft an email to the title company on {address}",
        "hoa": f"Draft an email to the listing agent on {address} requesting HOA documents",
        "disclosure": f"Draft an email to the listing agent on {address} about the disclosure",
    }.get(kind or "", f'What should I do about "{label}" on {address}?')

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

    ``offer`` is first-person prose for display, varied per ``seed`` (deal id)
    across the recognised task kinds; ``prompt`` is the fixed imperative message
    sent to Penny when the user clicks to act on it.
    """
    kind = _task_kind(label)
    offers = _TASK_OFFERS.get(kind) if kind else None
    offer = _pick(offers, seed, kind) if offers else "draft an email or schedule a time — tell me which"
    return offer, _task_prompt(kind, label, address)


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
        subjects = _TASK_SUBJECTS.get(kind) if kind else None
        subject = _cap(_pick(subjects, tx_id, kind)) if subjects else f"'{label}'"
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

    # 6. Intro email not yet sent — a deal under contract whose group hasn't been
    # introduced. This is how a human TC opens contract-to-close, so surface it
    # once the deal is active and there's a group worth introducing (>= 2 parties
    # with emails). intro_email_appropriate also screens out closed/cancelled and
    # already-sent deals.
    ok, _reason = email_client.intro_email_appropriate(tx)
    if ok and len(email_client.gather_intro_parties(tx)) >= 2:
        add(
            P_INTRO_NEEDED,
            _pick(
                [
                    f"The parties on {address} haven't been introduced yet",
                    f"No intro email has gone out on {address} yet",
                    f"{address} is under contract but the group hasn't met me yet",
                ],
                tx_id,
                "intro_needed",
            ),
            "send the intro email so everyone has each other's details (you confirm first)",
            f"Send the intro email for {address}",
        )

    # 7. Missing party emails on active deals
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
