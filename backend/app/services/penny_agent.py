"""Penny WhatsApp agent — Claude with tool-use for conversational transaction management.

Flow:
  1. Build a system prompt with the realtor's brokerage context and today's date.
  2. Replay recent conversation history so Claude has memory across turns.
  3. Run an agentic loop: call Claude → execute any tool calls → call Claude again
     until a plain-text stop_reason="end_turn" response is returned.
  4. Return the final text reply (concise, suitable for WhatsApp).

Tools available to Claude:
  - list_transactions       : show all active deals
  - get_transaction_details : look up a specific deal by address keyword
  - update_transaction_stage: change a deal's stage
  - add_transaction_note    : append a timestamped note to a deal
"""

import asyncio
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings
from app.core import supabase_client as sb
from app.services import (
    calendar_provider,
    compliance,
    doc_generate,
    email_client,
    next_actions,
    rentcast,
    scheduling,
    workflow,
)

MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 1024

# Set per-request so document-drafting tools can layer the requesting agent's
# personal style rules on top of the brokerage's (V2 Section 1B).
_current_agent_id: ContextVar[str | None] = ContextVar("penny_current_agent_id", default=None)

# Set on the email channel: the transaction the inbound reply thread is about, so
# the suggested-reply tools (approve / schedule / edit / dismiss) know which deal
# they operate on without the agent having to name it.
_current_transaction_id: ContextVar[str | None] = ContextVar(
    "penny_current_transaction_id", default=None
)

# --------------------------------------------------------------------------- #
# Tool definitions
# --------------------------------------------------------------------------- #

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_transactions",
        "description": (
            "List all transactions for this brokerage. Returns address, stage, "
            "closing date, buyer name, and seller name for each deal. "
            "Use this when the agent asks for a summary or overview of their pipeline."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_transaction_details",
        "description": (
            "Get full details of a specific transaction by searching the address. "
            "Use a partial address like 'Oak Street' or '123 Main'. "
            "Returns all fields including dates, parties, and notes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to search for.",
                }
            },
            "required": ["address_query"],
        },
    },
    {
        "name": "update_transaction_stage",
        "description": (
            "Update the stage of a transaction. "
            "Valid stages: under_contract, pending, closed, cancelled."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the address to identify the transaction.",
                },
                "stage": {
                    "type": "string",
                    "enum": ["under_contract", "pending", "closed", "cancelled"],
                    "description": "The new stage.",
                },
            },
            "required": ["address_query", "stage"],
        },
    },
    {
        "name": "add_transaction_note",
        "description": "Append a timestamped note to a transaction's notes field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the address to identify the transaction.",
                },
                "note": {
                    "type": "string",
                    "description": "The note text to append.",
                },
            },
            "required": ["address_query", "note"],
        },
    },
    {
        "name": "preview_intro_email",
        "description": (
            "Preview (do NOT send) the introduction email for a transaction. "
            "Returns the recipient list and the draft so you can show the agent "
            "exactly what will go out. Always call this before send_intro_email "
            "so the agent can confirm. Read-only — sends nothing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                }
            },
            "required": ["address_query"],
        },
    },
    {
        "name": "send_intro_email",
        "description": (
            "Send the introduction email to every party on a transaction (buyer, "
            "seller, agents, lender, title) who has an email on file. This actually "
            "sends email, so it requires confirmed=true — set that only after the "
            "agent has explicitly confirmed, or when intro emails are autonomous for "
            "this brokerage. The deal is marked so the intro is never sent twice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true to send. Set only after the agent confirms, "
                        "or when intro emails are autonomous for this brokerage."
                    ),
                },
            },
            "required": ["address_query", "confirmed"],
        },
    },
    {
        "name": "draft_document",
        "description": (
            "Draft a document (letter or email) for a transaction in the brokerage's "
            "voice — a status update, cover letter, follow-up, or congratulations note. "
            "Returns the draft for the agent to review. Read-only: it does NOT send "
            "anything. To actually send it, the agent uses the web app."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                },
                "doc_type": {
                    "type": "string",
                    "enum": [
                        "status_update",
                        "cover_letter",
                        "follow_up",
                        "congratulations",
                        "custom",
                    ],
                    "description": "The kind of document to draft.",
                },
                "recipient": {
                    "type": "string",
                    "description": "Who it's addressed to (optional, e.g. 'the buyer', 'the lender').",
                },
                "instructions": {
                    "type": "string",
                    "description": "Specific points to include (optional; expected for doc_type 'custom').",
                },
            },
            "required": ["address_query", "doc_type"],
        },
    },
    {
        "name": "list_deadlines",
        "description": (
            "List the tracked deadlines for a transaction — label, due date, "
            "status, and which reminders have already gone out. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                }
            },
            "required": ["address_query"],
        },
    },
    {
        "name": "add_deadline",
        "description": (
            "Add a deadline to a transaction (e.g. inspection, financing, "
            "appraisal, closing). Penny will remind the agent at the 5-day, "
            "2-day, and day-of marks. Optionally list which parties are "
            "responsible so they can be notified."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                },
                "label": {
                    "type": "string",
                    "description": "What the deadline is, e.g. 'Inspection contingency'.",
                },
                "due_date": {
                    "type": "string",
                    "description": "The due date in YYYY-MM-DD format.",
                },
                "responsible_parties": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "buyer",
                            "seller",
                            "listing_agent",
                            "selling_agent",
                            "lender",
                            "title",
                            "tc",
                        ],
                    },
                    "description": "Optional party role keys responsible for this deadline.",
                },
            },
            "required": ["address_query", "label", "due_date"],
        },
    },
    {
        "name": "review_compliance",
        "description": (
            "Run a compliance review on a transaction and surface the findings — "
            "missing disclosures, date problems, and state-checklist items to verify. "
            "Read-only: this NEVER approves compliance. A human must review and sign "
            "off in the web app; you only surface what to check."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                }
            },
            "required": ["address_query"],
        },
    },
    {
        "name": "get_comparable_sales",
        "description": (
            "Look up comparable sales and an estimated value for a property by its "
            "full address. Use this when the agent asks for comps, a CMA, or what a "
            "property is worth. Works for any address — it doesn't need to be a "
            "transaction on file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Full property address, e.g. '123 Oak St, Austin, TX 78701'.",
                }
            },
            "required": ["address"],
        },
    },
    {
        "name": "propose_showing_times",
        "description": (
            "Propose open appointment times for a transaction based on the "
            "brokerage's working hours and buffer, avoiding existing appointments. "
            "Use this when the agent wants to schedule a showing or inspection. "
            "Read-only — it suggests times but books nothing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                },
                "days": {
                    "type": "integer",
                    "description": "How many days ahead to search (default 5).",
                },
            },
            "required": ["address_query"],
        },
    },
    {
        "name": "book_appointment",
        "description": (
            "Book an appointment (showing, inspection, etc.) on a transaction at a "
            "specific time. This creates a calendar event when a calendar is "
            "connected, so it requires confirmed=true — set that only after the "
            "agent confirms the time, or when scheduling is autonomous for this brokerage."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                },
                "scheduled_at": {
                    "type": "string",
                    "description": "ISO 8601 datetime, ideally one of the proposed slots.",
                },
                "type": {
                    "type": "string",
                    "description": "Appointment type, e.g. 'showing' or 'inspection'.",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional attendee emails.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true to book. Set only after the agent confirms, "
                        "or when scheduling is autonomous for this brokerage."
                    ),
                },
            },
            "required": ["address_query", "scheduled_at", "confirmed"],
        },
    },
    {
        "name": "notify_appointment_parties",
        "description": (
            "Email the deal's parties to PROPOSE a booked appointment time and "
            "coordinate (e.g. the listing agent for access, the buyer for "
            "availability). Use after booking, when the agent wants to reach out. "
            "The email proposes the time and asks if it works — it does NOT confirm "
            "it. This contacts outside parties, so it requires confirmed=true; get "
            "the agent's go-ahead first. Targets the deal's soonest upcoming "
            "appointment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                },
                "parties": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Which parties to contact, by role key: buyer, seller, "
                        "listing_agent, selling_agent, lender, title. Defaults to the "
                        "agents and buyer who have an email on file."
                    ),
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true to send. Set only after the agent confirms they "
                        "want to reach out to the parties."
                    ),
                },
            },
            "required": ["address_query", "confirmed"],
        },
    },
    {
        "name": "list_appointments",
        "description": "List the scheduled appointments for a transaction. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                }
            },
            "required": ["address_query"],
        },
    },
    {
        "name": "get_upcoming_appointments",
        "description": (
            "List upcoming appointments across ALL of the agent's deals, soonest "
            "first. Read-only. Use this when the agent asks what's on their calendar, "
            "what's next, or what's coming up in general (not tied to one property). "
            "For a single deal's appointments, use list_appointments instead."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_compliance_checklist",
        "description": (
            "Show what's still missing from a transaction's compliance file — the "
            "pending required documents (agency disclosure, wire fraud advisory, "
            "lead-based paint, etc.). Read-only. Use when the agent asks what's "
            "missing or outstanding on a deal's file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                }
            },
            "required": ["address_query"],
        },
    },
    {
        "name": "mark_checklist_item",
        "description": (
            "Mark a compliance checklist item complete (or waived / not applicable) "
            "for a transaction. Identify the item by a keyword from its label, e.g. "
            "'inspection report'. Requires confirmed=true — confirm the exact item "
            "with the agent first, then call again with confirmed=true."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                },
                "item_query": {
                    "type": "string",
                    "description": "Keyword identifying the checklist item, e.g. 'inspection report'.",
                },
                "status": {
                    "type": "string",
                    "enum": ["complete", "waived", "not_applicable"],
                    "description": "The new status (default 'complete').",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Must be true to apply. Set only after the agent confirms.",
                },
            },
            "required": ["address_query", "item_query", "confirmed"],
        },
    },
    {
        "name": "get_emd_status",
        "description": (
            "Report the earnest money deposit status for a transaction — amount, due "
            "date, whether it's been received, and who's holding it. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                }
            },
            "required": ["address_query"],
        },
    },
    {
        "name": "mark_emd_received",
        "description": (
            "Mark the earnest money deposit as received for a transaction. Requires "
            "confirmed=true — confirm with the agent first. Optionally include the date "
            "received (YYYY-MM-DD); defaults to today."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                },
                "received_date": {
                    "type": "string",
                    "description": "Date received in YYYY-MM-DD (optional; defaults to today).",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Must be true to apply. Set only after the agent confirms.",
                },
            },
            "required": ["address_query", "confirmed"],
        },
    },
    {
        "name": "get_pending_tasks",
        "description": (
            "Show the pending workflow tasks for a transaction — what needs to happen "
            "next — grouped by urgency (overdue, due today, this week, upcoming). "
            "Read-only. Use when the agent asks what's next or what they need to do on a deal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                }
            },
            "required": ["address_query"],
        },
    },
    {
        "name": "mark_task_complete",
        "description": (
            "Mark a workflow task complete for a transaction. Identify the task by a "
            "keyword from its label, e.g. 'order inspection'. Requires confirmed=true — "
            "confirm the exact task with the agent first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": "Part of the property address to identify the transaction.",
                },
                "task_query": {
                    "type": "string",
                    "description": "Keyword identifying the task, e.g. 'order inspection'.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Must be true to apply. Set only after the agent confirms.",
                },
            },
            "required": ["address_query", "task_query", "confirmed"],
        },
    },
    {
        "name": "suggest_next_actions",
        "description": (
            "Synthesize the top concrete next actions an agent should take, "
            "cross-referencing pending workflow tasks, missing required checklist "
            "items, EMD status, upcoming deadlines, and missing party contacts on "
            "active deals. Returns a curated, prioritized list with the specific "
            "tool that would advance each one. Read-only. Use when the agent asks "
            "open questions like 'what should I do?', 'what's next?', or 'where are "
            "we?' — instead of dumping a raw task list. Pass address_query to scope "
            "to one deal, or omit it for a brokerage-wide top-3."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address_query": {
                    "type": "string",
                    "description": (
                        "Optional. Part of the property address to scope to one "
                        "transaction. Omit for a brokerage-wide synthesis."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "approve_and_send_reply",
        "description": (
            "Send a suggested reply to the OUTSIDE party now. Use this when the "
            "agent approves the drafted reply (e.g. 'send it', 'go ahead', 'yes "
            "send that'). The agent's approval IS the required confirmation. You "
            "may pass edited_body/edited_subject if the agent asked for changes "
            "before sending. Only call this when there's a suggested reply on the "
            "current deal and the agent has clearly approved sending it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reply_id": {
                    "type": "string",
                    "description": "The suggested-reply id. Omit if there's only one open suggestion on this deal.",
                },
                "edited_subject": {"type": "string", "description": "Optional revised subject."},
                "edited_body": {"type": "string", "description": "Optional revised body to send instead of the draft."},
            },
            "required": [],
        },
    },
    {
        "name": "schedule_reply",
        "description": (
            "Defer sending a suggested reply to an outside party until a trigger. "
            "Use when the agent says to wait. Nothing is ever sent automatically — "
            "when the trigger fires, the draft re-surfaces for the agent's final "
            "confirm. trigger_type:\n"
            "- 'time': hold until send_at, then re-surface for the agent's confirm. "
            "Convert phrases like 'Friday 9am' or 'in 2 hours' to an ISO-8601 "
            "datetime using today's date and the deal's timezone.\n"
            "- 'event': re-surface for the agent's confirm when the event becomes "
            "true. Valid event values: 'stage:<stage>' (e.g. 'stage:pending', "
            "'stage:closed'), 'emd_received', or 'checklist:<item label>' (a "
            "checklist item completing).\n"
            "- 'manual': a free-form hold Penny can't detect ('after I talk to my "
            "client'). Penny holds the draft and reminds the agent. Put the "
            "agent's wording in hold_note."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trigger_type": {
                    "type": "string",
                    "enum": ["time", "event", "manual"],
                },
                "send_at": {
                    "type": "string",
                    "description": "ISO-8601 datetime, required when trigger_type='time'.",
                },
                "event": {
                    "type": "string",
                    "description": "Event spec, required when trigger_type='event'. e.g. 'stage:pending', 'emd_received', 'checklist:Inspection'.",
                },
                "hold_note": {
                    "type": "string",
                    "description": "The agent's wording, required when trigger_type='manual'.",
                },
                "reply_id": {
                    "type": "string",
                    "description": "The suggested-reply id. Omit if there's only one open suggestion on this deal.",
                },
            },
            "required": ["trigger_type"],
        },
    },
    {
        "name": "edit_reply",
        "description": (
            "Revise a suggested reply's draft text without sending it (the agent "
            "wants changes but hasn't said to send yet). Updates the stored draft."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "reply_id": {
                    "type": "string",
                    "description": "The suggested-reply id. Omit if there's only one open suggestion on this deal.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "dismiss_reply",
        "description": (
            "Discard a suggested reply without sending it (the agent says not to "
            "respond, or to drop it)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reply_id": {
                    "type": "string",
                    "description": "The suggested-reply id. Omit if there's only one open suggestion on this deal.",
                },
            },
            "required": [],
        },
    },
]


# --------------------------------------------------------------------------- #
# Tool executors
# --------------------------------------------------------------------------- #

def _fmt_stage(stage: str | None) -> str:
    return (stage or "unknown").replace("_", " ").title()


def _fmt_date(d: str | None) -> str:
    if not d:
        return "not set"
    try:
        return date.fromisoformat(str(d)).strftime("%b %d, %Y")
    except ValueError:
        return str(d)


def _summarise_tx(tx: dict[str, Any]) -> str:
    parts = [
        f"• {tx.get('address', 'Unknown address')}",
        f"  Stage: {_fmt_stage(tx.get('stage'))}",
        f"  Closing: {_fmt_date(tx.get('closing_date'))}",
    ]
    if tx.get("buyer_name"):
        parts.append(f"  Buyer: {tx['buyer_name']}")
    if tx.get("seller_name"):
        parts.append(f"  Seller: {tx['seller_name']}")
    return "\n".join(parts)


def _detail_tx(tx: dict[str, Any]) -> str:
    lines = [f"📋 {tx.get('address', 'Unknown')}"]
    fields = [
        ("Stage", _fmt_stage(tx.get("stage"))),
        ("Sale price", f"${tx['sale_price']:,.0f}" if tx.get("sale_price") else None),
        ("Financing", tx.get("financing")),
        ("Contract date", _fmt_date(tx.get("contract_date"))),
        ("Closing date", _fmt_date(tx.get("closing_date"))),
        ("Buyer", tx.get("buyer_name")),
        ("Seller", tx.get("seller_name")),
        ("Listing agent", tx.get("listing_agent_name")),
        ("Selling agent", tx.get("selling_agent_name")),
        ("Lender", tx.get("lender_name")),
        ("Title co.", tx.get("title_company")),
        ("MLS #", tx.get("mls_number")),
    ]
    for label, val in fields:
        if val:
            lines.append(f"  {label}: {val}")
    if tx.get("notes"):
        lines.append(f"  Notes: {tx['notes']}")
    return "\n".join(lines)


async def _exec_list_transactions(brokerage_id: str, _inputs: dict) -> str:
    txs = await sb.list_transactions(brokerage_id)
    if not txs:
        return "No transactions found for your brokerage."
    return f"You have {len(txs)} transaction(s):\n\n" + "\n\n".join(
        _summarise_tx(tx) for tx in txs
    )


async def _exec_get_transaction_details(brokerage_id: str, inputs: dict) -> str:
    query = inputs.get("address_query", "")
    txs = await sb.search_transactions(brokerage_id, query)
    if not txs:
        return f"No transaction found matching '{query}'."
    if len(txs) > 1:
        names = ", ".join(t.get("address", "?") for t in txs[:5])
        return (
            f"Found {len(txs)} transactions matching '{query}': {names}. "
            "Please be more specific."
        )
    return _detail_tx(txs[0])


async def _exec_update_transaction_stage(brokerage_id: str, inputs: dict) -> str:
    query = inputs.get("address_query", "")
    new_stage = inputs.get("stage", "")
    txs = await sb.search_transactions(brokerage_id, query)
    if not txs:
        return f"No transaction found matching '{query}'."
    if len(txs) > 1:
        return (
            f"Found {len(txs)} transactions matching '{query}'. "
            "Please be more specific."
        )
    tx = txs[0]
    stage_data: dict[str, Any] = {"stage": new_stage}
    if new_stage == "closed" and tx.get("stage") != "closed":
        stage_data["closed_at"] = datetime.now(timezone.utc).isoformat()
    updated = await sb.update_transaction(brokerage_id, tx["id"], stage_data)
    if updated:
        if new_stage != tx.get("stage"):
            try:
                await workflow.generate_stage_tasks(updated, new_stage)
            except Exception:
                pass
        return (
            f"Updated {tx.get('address', 'transaction')} to "
            f"{_fmt_stage(new_stage)}."
        )
    return "Update failed — please try again."


async def _exec_add_transaction_note(brokerage_id: str, inputs: dict) -> str:
    query = inputs.get("address_query", "")
    note_text = inputs.get("note", "").strip()
    txs = await sb.search_transactions(brokerage_id, query)
    if not txs:
        return f"No transaction found matching '{query}'."
    if len(txs) > 1:
        return (
            f"Found {len(txs)} transactions matching '{query}'. "
            "Please be more specific."
        )
    tx = txs[0]
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    new_note = f"[{timestamp}] {note_text}"
    existing = tx.get("notes") or ""
    combined = f"{existing}\n{new_note}".strip()
    await sb.update_transaction(brokerage_id, tx["id"], {"notes": combined})
    return f"Note added to {tx.get('address', 'transaction')}."


async def _resolve_single(
    brokerage_id: str, query: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a query to exactly one transaction.

    Returns ``(tx, None)`` on a unique match, or ``(None, message)`` when there
    is no match or the query is ambiguous.
    """
    txs = await sb.search_transactions(brokerage_id, query)
    if not txs:
        return None, f"No transaction found matching '{query}'."
    if len(txs) > 1:
        names = ", ".join(t.get("address", "?") for t in txs[:5])
        return None, (
            f"Found {len(txs)} transactions matching '{query}': {names}. "
            "Please be more specific."
        )
    return txs[0], None


async def _exec_preview_intro_email(brokerage_id: str, inputs: dict) -> str:
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    address = tx.get("address", "this transaction")
    parties = email_client.gather_intro_parties(tx)
    if not parties:
        return (
            f"No parties on {address} have email addresses on file yet, so there's "
            "no one to introduce. Add buyer/seller/agent/lender/title emails first."
        )
    brokerage = await sb.get_brokerage(brokerage_id)
    brokerage_name = (brokerage or {}).get("name", "the brokerage")
    subject, _html, plain = email_client.build_intro_content(tx, brokerage_name)
    recipients = "\n".join(
        f"  - {p['role']}: {p['name']} <{p['email']}>" for p in parties
    )
    already = (
        "\n\nNote: an intro email was already sent for this deal."
        if tx.get("intro_email_sent")
        else ""
    )
    return (
        f"Intro email preview for {address}:\n\n"
        f"To ({len(parties)} recipients):\n{recipients}\n\n"
        f"Subject: {subject}\n\n{plain}{already}"
    )


async def _exec_send_intro_email(brokerage_id: str, inputs: dict) -> str:
    # Intro emails may be sent autonomously when the brokerage has opted in
    # (the `intro-email` task autonomy toggle); otherwise a human must confirm.
    autonomous = False
    try:
        autonomy = await sb.get_task_autonomy(brokerage_id)
        autonomous = any(
            r.get("task_id") == "intro-email" and r.get("autonomous") for r in autonomy
        )
    except Exception:
        autonomous = False
    if not inputs.get("confirmed") and not autonomous:
        return (
            "Not sent — I need explicit confirmation first. Show the agent the "
            "preview (preview_intro_email) and ask them to confirm, then call this "
            "again with confirmed=true."
        )
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    address = tx.get("address", "this transaction")
    if tx.get("intro_email_sent"):
        return (
            f"The intro email for {address} was already sent, so I won't send it "
            "again."
        )
    parties = email_client.gather_intro_parties(tx)
    if not parties:
        return (
            f"No parties on {address} have email addresses on file, so there's no "
            "one to send the intro email to."
        )
    brokerage = await sb.get_brokerage(brokerage_id)
    brokerage_name = (brokerage or {}).get("name", "the brokerage")
    result = await asyncio.to_thread(
        email_client.send_intro_email, tx, brokerage_name, brokerage
    )
    if not result["sent"]:
        return f"I couldn't send the intro email: {result['reason']}."
    await sb.update_transaction(brokerage_id, tx["id"], {"intro_email_sent": True})
    try:
        subject, _html, plain = email_client.build_intro_content(tx, brokerage_name)
        await sb.insert_transaction_email({
            "transaction_id": tx["id"],
            "direction": "outbound",
            "sender_email": email_client.from_email(),
            "recipient_emails": [p["email"] for p in result["recipients"]],
            "subject": subject,
            "body_text": plain,
            "read": True,
        })
    except Exception:  # noqa: BLE001 — logging is best-effort
        pass
    who = ", ".join(p["name"] for p in result["recipients"])
    return (
        f"Sent the intro email for {address} to {len(result['recipients'])} "
        f"people: {who}."
    )


async def _exec_draft_document(brokerage_id: str, inputs: dict) -> str:
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    brokerage = await sb.get_brokerage(brokerage_id)
    brokerage_name = (brokerage or {}).get("name", "the brokerage")
    agent_id = _current_agent_id.get() or tx.get("agent_id")
    rules = await sb.get_confirmed_knowledge_rules(brokerage_id, agent_id)
    try:
        draft = await doc_generate.generate_document(
            transaction=tx,
            doc_type=inputs.get("doc_type", "status_update"),
            brokerage_name=brokerage_name,
            style_rules=rules,
            recipient=inputs.get("recipient"),
            instructions=inputs.get("instructions"),
        )
    except doc_generate.DocNotConfigured:
        return (
            "I can't draft documents yet — the backend is missing its AI key "
            "(ANTHROPIC_API_KEY)."
        )
    except doc_generate.DocGenerationError as exc:
        return f"I couldn't draft that document: {exc}"
    address = tx.get("address", "this transaction")
    subject = draft.get("subject") or "(no subject)"
    return (
        f"Draft for {address}:\n\nSubject: {subject}\n\n{draft['body']}\n\n"
        "Review and edit as needed — you can send it from the web app, or tell me "
        "what to change."
    )


def _fmt_parties(keys: list[str] | None) -> str:
    labels = {
        "buyer": "buyer",
        "seller": "seller",
        "listing_agent": "listing agent",
        "selling_agent": "selling agent",
        "lender": "lender",
        "title": "title",
        "tc": "TC",
    }
    names = [labels.get(k, k) for k in (keys or [])]
    return ", ".join(names) if names else "no one set"


async def _exec_list_deadlines(brokerage_id: str, inputs: dict) -> str:
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    deadlines = await sb.list_deadlines_for_transaction(tx["id"])
    if not deadlines:
        return f"No deadlines tracked yet for {tx.get('address', 'this transaction')}."
    lines = [f"Deadlines for {tx.get('address', 'this transaction')}:"]
    for d in deadlines:
        reminders = [
            name
            for name, flag in (
                ("5-day", "reminder_5day_sent"),
                ("2-day", "reminder_2day_sent"),
                ("day-of", "reminder_day_sent"),
            )
            if d.get(flag)
        ]
        sent = f" (sent: {', '.join(reminders)})" if reminders else ""
        lines.append(
            f"- {d.get('label', 'Deadline')}: due {_fmt_date(d.get('due_date'))}"
            f" · parties: {_fmt_parties(d.get('responsible_parties'))}{sent}"
        )
    return "\n".join(lines)


async def _exec_add_deadline(brokerage_id: str, inputs: dict) -> str:
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    label = (inputs.get("label") or "").strip()
    due_date = (inputs.get("due_date") or "").strip()
    if not label:
        return "I need a label for the deadline (e.g. 'Inspection contingency')."
    try:
        date.fromisoformat(due_date)
    except ValueError:
        return "I need the due date in YYYY-MM-DD format."
    valid_keys = {"buyer", "seller", "listing_agent", "selling_agent", "lender", "title", "tc"}
    parties = [k for k in (inputs.get("responsible_parties") or []) if k in valid_keys]
    await sb.insert_deadline({
        "transaction_id": tx["id"],
        "label": label,
        "due_date": due_date,
        "responsible_parties": parties,
        "status": "pending",
    })
    who = f" Responsible: {_fmt_parties(parties)}." if parties else ""
    return (
        f"Added '{label}' due {_fmt_date(due_date)} for "
        f"{tx.get('address', 'the transaction')}. I'll remind you at the 5-day, "
        f"2-day, and day-of marks.{who}"
    )


async def _exec_review_compliance(brokerage_id: str, inputs: dict) -> str:
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    pdf_bytes = None
    path = (tx.get("contract_pdf_url") or "").strip()
    if path:
        try:
            pdf_bytes = await sb.download_object("contracts", path)
        except Exception:
            pdf_bytes = None
    review = await compliance.review_transaction(tx, pdf_bytes)
    address = tx.get("address", "this transaction")
    counts = review["counts"]
    lines = [
        f"Compliance review for {address} ({review['ruleset_state']} checklist):",
        f"{counts['issue']} issue(s), {counts['warning']} warning(s).",
    ]
    for f in review["findings"][:8]:
        lines.append(f"- [{f['severity']}] {f['message']}")
    if not review["contract_reviewed"]:
        lines.append(
            "(Contract not AI-reviewed — no PDF on file or AI unavailable; "
            "structural + checklist only.)"
        )
    current = tx.get("compliance_status") or "not reviewed"
    lines.append(
        f"Current status: {current}. I can't approve compliance — please review "
        "and sign off in the web app."
    )
    return "\n".join(lines)


def _money(value: Any) -> str:
    return f"${value:,.0f}" if isinstance(value, (int, float)) else "?"


async def _exec_get_comparable_sales(brokerage_id: str, inputs: dict) -> str:
    address = (inputs.get("address") or "").strip()
    if not address:
        return "I need a property address to pull comparable sales."
    try:
        result = await rentcast.get_value_estimate(address)
    except rentcast.RentcastNotConfigured:
        return (
            "Comparable sales aren't set up yet — your broker needs to add the "
            "RENTCAST_API_KEY on the backend."
        )
    except rentcast.RentcastError as exc:
        return f"I couldn't pull comps: {exc}"
    lines = [f"Comps for {result['subject_address']}:"]
    if result.get("estimate"):
        rng = ""
        if result.get("range_low") and result.get("range_high"):
            rng = f" (range {_money(result['range_low'])}–{_money(result['range_high'])})"
        lines.append(f"Estimated value: {_money(result['estimate'])}{rng}")
    comps = result.get("comparables") or []
    if not comps:
        lines.append("No comparable properties came back for that address.")
    for c in comps[:5]:
        bits = [c.get("address") or "Unknown address", _money(c.get("price"))]
        bd, ba, sf = c.get("bedrooms"), c.get("bathrooms"), c.get("square_footage")
        spec = []
        if bd:
            spec.append(f"{bd:g}bd")
        if ba:
            spec.append(f"{ba:g}ba")
        if sf:
            spec.append(f"{sf:g} sqft")
        if spec:
            bits.append("/".join(spec))
        lines.append("- " + " · ".join(bits))
    return "\n".join(lines)


def _fmt_slot(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return dt.strftime("%a %b %d, ") + f"{hour}:{dt.minute:02d} {ampm}"


async def _brokerage_busy(brokerage_id: str) -> list[tuple[datetime, datetime]]:
    txs = await sb.list_transactions(brokerage_id)
    appts = await sb.list_appointments_in([t["id"] for t in txs])
    busy: list[tuple[datetime, datetime]] = []
    for a in appts:
        when = a.get("scheduled_at")
        if not when:
            continue
        try:
            bs = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        except ValueError:
            continue
        busy.append((bs, bs + timedelta(minutes=scheduling.DEFAULT_DURATION_MIN)))
    return busy


async def _exec_propose_showing_times(brokerage_id: str, inputs: dict) -> str:
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    brokerage = await sb.get_brokerage(brokerage_id) or {}
    tz = scheduling.resolve_timezone(brokerage.get("state"))
    now = datetime.now(tz)
    days = int(inputs.get("days") or 5)
    busy = await _brokerage_busy(brokerage_id)
    slots = scheduling.propose_slots(
        work_start=brokerage.get("work_start"),
        work_end=brokerage.get("work_end"),
        buffer_minutes=brokerage.get("buffer_minutes") or 0,
        tz=tz,
        start_day=now.date(),
        days=days,
        busy=busy,
        now=now,
        max_slots=6,
    )
    if not slots:
        return (
            f"I couldn't find open times for {tx.get('address', 'this property')} in "
            "your working hours over that range."
        )
    lines = [f"Open times for {tx.get('address', 'this property')} ({tz.key}):"]
    lines += [f"- {_fmt_slot(s)}" for s in slots]
    lines.append("Tell me which one to book and I'll schedule it once you confirm.")
    return "\n".join(lines)


async def _exec_book_appointment(brokerage_id: str, inputs: dict) -> str:
    autonomous = False
    try:
        autonomy = await sb.get_task_autonomy(brokerage_id)
        autonomous = any(
            r.get("task_id") == "scheduling" and r.get("autonomous") for r in autonomy
        )
    except Exception:
        autonomous = False
    if not inputs.get("confirmed") and not autonomous:
        return (
            "Not booked — I need confirmation first. Show the agent the time and "
            "ask them to confirm, then call this again with confirmed=true."
        )
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    raw = (inputs.get("scheduled_at") or "").strip()
    try:
        start = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return "I need the time as an ISO 8601 datetime (e.g. 2026-06-01T14:30:00-05:00)."
    brokerage = await sb.get_brokerage(brokerage_id) or {}
    # Anchor a naive time to the brokerage tz; a timestamptz column would
    # otherwise treat an offset-less time as UTC and shift it.
    if start.tzinfo is None:
        start = start.replace(tzinfo=scheduling.resolve_timezone(brokerage.get("state")))
    appt_type = (inputs.get("type") or "showing").strip()
    attendees = [a for a in (inputs.get("attendees") or []) if a and a.strip()]
    end = start + timedelta(minutes=scheduling.DEFAULT_DURATION_MIN)
    address = (tx.get("address") or "the property").strip()
    # Route to the deal's agent calendar if connected, else the brokerage's.
    cal_agent = None
    if tx.get("agent_id"):
        try:
            cal_agent = await sb.get_agent(brokerage_id, tx["agent_id"])
        except Exception:
            cal_agent = None
    account = calendar_provider.resolve_account(brokerage, cal_agent)
    event_id = await calendar_provider.create_event(
        account,
        summary=f"{appt_type.replace('_', ' ').title()} — {address}",
        start=start,
        end=end,
        attendees=attendees,
    )
    await sb.insert_appointment({
        "transaction_id": tx["id"],
        "type": appt_type,
        "showing_method": brokerage.get("showing_method"),
        "scheduled_at": start.isoformat(),
        "confirmed": True,
        "calendar_event_id": event_id,
        "attendees": attendees,
    })
    synced = " and added it to your calendar" if event_id else ""
    return f"Booked the {appt_type} for {address} on {_fmt_slot(start)}{synced}."


# Sensible default targets for coordinating an appointment: the agents (for
# access) and the buyer (for availability). Filtered to those with an email.
_DEFAULT_COORDINATE_ROLES = ["listing_agent", "selling_agent", "buyer"]


async def _exec_notify_appointment_parties(brokerage_id: str, inputs: dict) -> str:
    if not inputs.get("confirmed"):
        return (
            "Not sent — I need your go-ahead first. This emails the parties to propose "
            "the time. Confirm and I'll reach out (call again with confirmed=true)."
        )
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err

    appts = await sb.list_appointments_for_transaction(tx["id"])
    now = datetime.now(timezone.utc)
    upcoming: list[tuple[datetime, dict]] = []
    for a in appts:
        when = a.get("scheduled_at")
        if not when:
            continue
        try:
            dt = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= now:
            upcoming.append((dt, a))
    if not upcoming:
        return (
            f"There's no upcoming appointment on {tx.get('address', 'this deal')} to "
            "coordinate yet. Book a time first, then I can propose it to the parties."
        )
    upcoming.sort(key=lambda x: x[0])
    _dt, appt = upcoming[0]

    keys = [k for k in (inputs.get("parties") or []) if k in email_client.PARTY_KEYS]
    if not keys:
        keys = _DEFAULT_COORDINATE_ROLES
    parties = email_client.gather_parties_by_keys(tx, keys)
    if not parties:
        return (
            "I don't have an email on file for the parties you'd want to coordinate "
            "with (listing agent, buyer). Add a contact and I'll reach out."
        )

    brokerage = await sb.get_brokerage(brokerage_id) or {}
    tz = scheduling.resolve_timezone(brokerage.get("state"))
    start = appt["scheduled_at"]
    try:
        sdt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        if sdt.tzinfo is None:
            sdt = sdt.replace(tzinfo=tz)
        local = sdt.astimezone(tz)
        hour = local.hour % 12 or 12
        ampm = "AM" if local.hour < 12 else "PM"
        when_str = local.strftime("%A, %b %d, ") + f"{hour}:{local.minute:02d} {ampm} ({tz.key})"
    except (ValueError, KeyError):
        when_str = "a time to be confirmed"

    address = (tx.get("address") or "your transaction").strip()
    subject, html, plain = email_client.build_appointment_coordination_content(
        address, appt.get("type") or "appointment", when_str, brokerage.get("name", "your brokerage")
    )
    recipients = [p["email"] for p in parties]
    sent = await asyncio.to_thread(
        email_client.send_email,
        to_emails=recipients,
        subject=subject,
        html=html,
        plain=plain,
        reply_to=email_client.reply_to_address(tx["id"]),
        disclosure=email_client.disclosure_text(brokerage),
    )
    if not sent:
        return "I couldn't send that — email isn't configured or the send failed."
    try:
        await sb.insert_transaction_email({
            "transaction_id": tx["id"],
            "direction": "outbound",
            "sender_email": email_client.from_email(),
            "recipient_emails": recipients,
            "subject": subject,
            "body_text": plain,
            "body_html": html,
            "read": True,
        })
    except Exception:  # noqa: BLE001
        pass
    who = ", ".join(p["name"] for p in parties)
    return (
        f"Sent — I proposed {when_str} for the {appt.get('type') or 'appointment'} at "
        f"{address} to {who} and asked them to confirm it works."
    )


async def _exec_list_appointments(brokerage_id: str, inputs: dict) -> str:
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    appts = await sb.list_appointments_for_transaction(tx["id"])
    if not appts:
        return f"No appointments scheduled for {tx.get('address', 'this transaction')}."
    lines = [f"Appointments for {tx.get('address', 'this transaction')}:"]
    for a in appts:
        when = a.get("scheduled_at")
        label = a.get("type", "appointment")
        try:
            dt = datetime.fromisoformat(str(when).replace("Z", "+00:00")) if when else None
        except ValueError:
            dt = None
        lines.append(f"- {label}: {_fmt_slot(dt) if dt else 'time TBD'}")
    return "\n".join(lines)


async def _exec_get_upcoming_appointments(brokerage_id: str, inputs: dict) -> str:
    txs = await sb.list_transactions(brokerage_id)
    addr_by_id = {t["id"]: (t.get("address") or "a property") for t in txs}
    appts = await sb.list_appointments_in(list(addr_by_id.keys())) if addr_by_id else []
    now = datetime.now(timezone.utc)
    upcoming: list[tuple[datetime, dict]] = []
    for a in appts:
        when = a.get("scheduled_at")
        if not when:
            continue
        try:
            dt = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt < now:
            continue
        upcoming.append((dt, a))
    if not upcoming:
        return (
            "Nothing coming up on the calendar. You have no future appointments booked "
            "right now. Want me to propose showing times for one of your deals?"
        )
    upcoming.sort(key=lambda x: x[0])
    lines = ["Here's what's coming up:"]
    for dt, a in upcoming[:15]:
        addr = addr_by_id.get(a.get("transaction_id"), "a property")
        label = (a.get("type") or "appointment").replace("_", " ")
        lines.append(f"- {_fmt_slot(dt)}: {label} at {addr}")
    return "\n".join(lines)


_DONE_CHECKLIST = {"complete", "waived", "not_applicable"}


async def _exec_get_compliance_checklist(brokerage_id: str, inputs: dict) -> str:
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    items = await sb.list_checklist_items(tx["id"])
    address = tx.get("address", "this transaction")
    if not items:
        return (
            f"No compliance checklist exists yet for {address}. It's created from a "
            "template when the transaction is set up."
        )
    pending = [i for i in items if i.get("required") and i.get("status") not in _DONE_CHECKLIST]
    total_req = sum(1 for i in items if i.get("required"))
    done_req = total_req - len(pending)
    if not pending:
        return f"✅ {address}: all {total_req} required compliance items are complete."
    lines = [
        f"{address} compliance file — {done_req}/{total_req} required items done. "
        f"Still missing:",
    ]
    lines += [f"- {i.get('label')}" for i in pending]
    return "\n".join(lines)


async def _exec_mark_checklist_item(brokerage_id: str, inputs: dict) -> str:
    if not inputs.get("confirmed"):
        return (
            "Not marked — confirm the exact item with the agent first, then call "
            "again with confirmed=true."
        )
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    query = (inputs.get("item_query") or "").strip().lower()
    if not query:
        return "Which checklist item? Give me a keyword from its label."
    new_status = inputs.get("status") or "complete"
    if new_status not in _DONE_CHECKLIST:
        return "Status must be complete, waived, or not_applicable."
    items = await sb.list_checklist_items(tx["id"])
    matches = [i for i in items if query in (i.get("label") or "").lower()]
    if not matches:
        return f"No checklist item matching '{query}' on {tx.get('address', 'this transaction')}."
    if len(matches) > 1:
        names = ", ".join(m.get("label", "?") for m in matches[:5])
        return f"Multiple items match '{query}': {names}. Please be more specific."
    item = matches[0]
    data: dict[str, Any] = {"status": new_status}
    if new_status == "complete":
        data["completed_at"] = datetime.now(timezone.utc).isoformat()
    await sb.update_checklist_item(item["id"], data)
    verb = {"complete": "complete", "waived": "waived", "not_applicable": "not applicable"}[new_status]
    return f"Marked '{item.get('label')}' as {verb} for {tx.get('address', 'the transaction')}."


async def _exec_get_emd_status(brokerage_id: str, inputs: dict) -> str:
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    address = tx.get("address", "this transaction")
    amount = tx.get("emd_amount")
    amount_str = _money(amount) if amount is not None else "an unspecified amount"
    if tx.get("emd_received"):
        when = tx.get("emd_received_date")
        held = tx.get("emd_held_by")
        held_str = f", held by {held}" if held else ""
        return (
            f"EMD for {address}: received{f' on {_fmt_date(when)}' if when else ''} "
            f"({amount_str}{held_str})."
        )
    due = tx.get("emd_due_date")
    due_str = f", due {_fmt_date(due)}" if due else ""
    return f"EMD for {address}: NOT yet received ({amount_str}{due_str})."


async def _exec_mark_emd_received(brokerage_id: str, inputs: dict) -> str:
    if not inputs.get("confirmed"):
        return "Not marked — confirm with the agent first, then call again with confirmed=true."
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    received_date = (inputs.get("received_date") or "").strip()
    if received_date:
        try:
            date.fromisoformat(received_date)
        except ValueError:
            return "I need the received date in YYYY-MM-DD format."
    else:
        received_date = date.today().isoformat()
    await sb.update_transaction(
        brokerage_id, tx["id"], {"emd_received": True, "emd_received_date": received_date}
    )
    return f"Marked EMD received on {_fmt_date(received_date)} for {tx.get('address', 'the transaction')}."


async def _exec_get_pending_tasks(brokerage_id: str, inputs: dict) -> str:
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    tasks = await sb.list_transaction_tasks(tx["id"])
    pending = [t for t in tasks if t.get("status") == "pending"]
    address = tx.get("address", "this transaction")
    if not pending:
        return f"No pending tasks for {address} — you're all caught up."
    today = date.today()

    def bucket(t: dict) -> str:
        due = t.get("due_date")
        try:
            d = date.fromisoformat(str(due)[:10]) if due else None
        except ValueError:
            d = None
        if d is None:
            return "upcoming"
        if d < today:
            return "overdue"
        if d == today:
            return "today"
        if (d - today).days <= 7:
            return "week"
        return "upcoming"

    groups: dict[str, list[dict]] = {"overdue": [], "today": [], "week": [], "upcoming": []}
    for t in pending:
        groups[bucket(t)].append(t)

    lines = [f"📋 {address} — Pending Tasks"]
    headers = [
        ("overdue", "🔴 OVERDUE"),
        ("today", "📅 DUE TODAY"),
        ("week", "📅 THIS WEEK"),
        ("upcoming", "UPCOMING"),
    ]
    for key, label in headers:
        items = groups[key]
        if not items:
            continue
        lines.append("")
        lines.append(label)
        for t in items:
            due = t.get("due_date")
            suffix = f" (due {_fmt_date(due)})" if due else ""
            lines.append(f"• {t.get('label')}{suffix}")
    return "\n".join(lines)


async def _exec_mark_task_complete(brokerage_id: str, inputs: dict) -> str:
    if not inputs.get("confirmed"):
        return (
            "Not marked — confirm the exact task with the agent first, then call "
            "again with confirmed=true."
        )
    tx, err = await _resolve_single(brokerage_id, inputs.get("address_query", ""))
    if err:
        return err
    query = (inputs.get("task_query") or "").strip().lower()
    if not query:
        return "Which task? Give me a keyword from its label."
    tasks = await sb.list_transaction_tasks(tx["id"])
    matches = [
        t for t in tasks
        if t.get("status") == "pending" and query in (t.get("label") or "").lower()
    ]
    if not matches:
        return f"No pending task matching '{query}' on {tx.get('address', 'this transaction')}."
    if len(matches) > 1:
        names = ", ".join(m.get("label", "?") for m in matches[:5])
        return f"Multiple tasks match '{query}': {names}. Please be more specific."
    task = matches[0]
    await sb.update_transaction_task(
        task["id"],
        {"status": "complete", "completed_at": datetime.now(timezone.utc).isoformat()},
    )
    return f"Marked '{task.get('label')}' complete for {tx.get('address', 'the transaction')}."


async def _exec_suggest_next_actions(brokerage_id: str, inputs: dict) -> str:
    """Curated top-3 synthesis across active deals, or scoped to one deal.

    Delegates the cross-referencing to ``next_actions`` (shared with the
    home-page briefing) and formats the result for chat.
    """
    query = (inputs.get("address_query") or "").strip()

    if query:
        tx, err = await _resolve_single(brokerage_id, query)
        if err:
            return err
        actions = await next_actions.collect_for_transaction(tx)
        scope_label = tx.get("address") or "the deal"
    else:
        try:
            actions = await next_actions.collect_for_brokerage(brokerage_id)
        except Exception:  # noqa: BLE001
            return "Couldn't load your deals right now — try again in a moment."
        scope_label = "your active deals"

    if not actions:
        return f"Nothing pressing on {scope_label} right now — you're caught up."

    top, remaining = next_actions.top_actions(actions, limit=3)
    lines = [f"Top next moves on {scope_label}:"]
    for a in top:
        lines.append(f"- {a['headline']} — I can {a['offer']}.")
    if remaining > 0:
        lines.append(f"({remaining} more on the list — ask me about a specific deal for the rest.)")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Suggested-reply tools (two-way email): act on a queued reply to an outside
# party. Scoped to the email thread's transaction via _current_transaction_id.
# --------------------------------------------------------------------------- #

_OPEN_REPLY_STATUSES = ["pending", "scheduled", "awaiting_event", "held"]


def _html_escape(text: str) -> str:
    import html as _h

    return _h.escape(text)


def _parse_dt(raw: str) -> datetime | None:
    """Parse an ISO-8601 datetime (tolerating a trailing 'Z'); assume UTC if naive."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _event_label(event: str) -> str:
    """Human phrasing for an event trigger spec."""
    e = (event or "").strip()
    if e.startswith("stage:"):
        return f"the deal moves to {e.split(':', 1)[1].replace('_', ' ')}"
    if e == "emd_received":
        return "the EMD is marked received"
    if e.startswith("checklist:"):
        return f"\"{e.split(':', 1)[1]}\" is checked off"
    return e or "that happens"


async def _resolve_reply(
    brokerage_id: str, inputs: dict
) -> tuple[dict | None, str | None]:
    """Find the suggested reply the agent means, scoped to the current deal."""
    tx_id = _current_transaction_id.get()
    if not tx_id:
        return None, (
            "I can only manage a suggested reply from inside the email thread it "
            "belongs to."
        )
    reply_id = inputs.get("reply_id")
    if reply_id:
        row = await sb.get_pending_email_reply(reply_id)
        if (
            row is None
            or row.get("brokerage_id") != brokerage_id
            or row.get("transaction_id") != tx_id
        ):
            return None, "I couldn't find that suggested reply on this deal."
        if row.get("status") not in _OPEN_REPLY_STATUSES:
            return None, "That suggested reply was already resolved."
        return row, None
    rows = await sb.list_pending_email_replies_for_transaction(tx_id)
    rows = [r for r in rows if r.get("status") in _OPEN_REPLY_STATUSES]
    if not rows:
        return None, "There's no open suggested reply on this deal right now."
    if len(rows) > 1:
        listing = "; ".join(
            f"{r.get('to_name') or r.get('to_email')}: \"{(r.get('subject') or '').strip()}\""
            for r in rows
        )
        return None, (
            "There are a few open suggested replies on this deal — which one? "
            + listing
        )
    return rows[0], None


async def _exec_approve_and_send_reply(brokerage_id: str, inputs: dict) -> str:
    row, err = await _resolve_reply(brokerage_id, inputs)
    if err:
        return err
    assert row is not None
    subject = (inputs.get("edited_subject") or row.get("subject") or "").strip()
    body = (inputs.get("edited_body") or row.get("draft_body") or "").strip()
    to_email = (row.get("to_email") or "").strip()
    if not to_email:
        return "There's no recipient address on that reply, so I can't send it."
    if not body:
        return "The draft is empty — tell me what to say and I'll send it."
    brokerage = await sb.get_brokerage(brokerage_id)
    html_body = (
        '<html><body><div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        "white-space:pre-wrap;color:#111827;font-size:15px;line-height:1.6;\">"
        f"{_html_escape(body)}</div></body></html>"
    )
    sent = await asyncio.to_thread(
        email_client.send_email,
        to_emails=[to_email],
        subject=subject,
        html=html_body,
        plain=body,
        reply_to=email_client.reply_to_address(row["transaction_id"]),
        disclosure=email_client.disclosure_text(brokerage),
    )
    if not sent:
        return "I couldn't send it — email isn't configured or the send failed."
    await sb.update_pending_email_reply(
        row["id"],
        {"status": "sent", "resolved_at": datetime.now(timezone.utc).isoformat()},
    )
    try:
        await sb.insert_transaction_email(
            {
                "transaction_id": row["transaction_id"],
                "direction": "outbound",
                "sender_email": email_client.from_email(),
                "recipient_emails": [to_email],
                "subject": subject,
                "body_text": body,
                "body_html": html_body,
                "read": True,
            }
        )
    except sb.SupabaseError:
        pass
    return f"Sent to {row.get('to_name') or to_email}."


async def _exec_schedule_reply(brokerage_id: str, inputs: dict) -> str:
    row, err = await _resolve_reply(brokerage_id, inputs)
    if err:
        return err
    assert row is not None
    trigger_type = (inputs.get("trigger_type") or "").strip()
    if trigger_type == "time":
        raw = (inputs.get("send_at") or "").strip()
        when = _parse_dt(raw)
        if when is None:
            return "I couldn't read that send time — give me a date and time."
        await sb.update_pending_email_reply(
            row["id"],
            {
                "status": "scheduled",
                "trigger_type": "time",
                "scheduled_send_at": when.isoformat(),
                "trigger_event": None,
            },
        )
        return (
            f"Got it — I'll hold the reply to {row.get('to_name') or row.get('to_email')} "
            f"and check back with you on {when.strftime('%b %-d at %-I:%M %p')} before "
            "anything goes out."
        )
    if trigger_type == "event":
        event = (inputs.get("event") or "").strip()
        if not event:
            return "Which event should I wait for (e.g. it goes pending, EMD received)?"
        await sb.update_pending_email_reply(
            row["id"],
            {
                "status": "awaiting_event",
                "trigger_type": "event",
                "trigger_event": event,
                "scheduled_send_at": None,
            },
        )
        return (
            f"Will do — I'll hold the reply and check back with you when {_event_label(event)}, "
            "before anything goes out."
        )
    if trigger_type == "manual":
        note = (inputs.get("hold_note") or "").strip()
        await sb.update_pending_email_reply(
            row["id"],
            {"status": "held", "trigger_type": "manual", "hold_note": note or None},
        )
        return (
            "Holding it for now — I won't send anything until you tell me to, and I'll "
            "remind you it's waiting."
        )
    return "I can hold a reply until a time, a deal event, or just on hold — which one?"


async def _exec_edit_reply(brokerage_id: str, inputs: dict) -> str:
    row, err = await _resolve_reply(brokerage_id, inputs)
    if err:
        return err
    assert row is not None
    patch: dict[str, Any] = {}
    if inputs.get("subject") is not None:
        patch["subject"] = inputs["subject"]
    if inputs.get("body") is not None:
        patch["draft_body"] = inputs["body"]
    if not patch:
        return "Tell me what to change and I'll update the draft."
    await sb.update_pending_email_reply(row["id"], patch)
    return "Updated the draft. Say the word when you want me to send it."


async def _exec_dismiss_reply(brokerage_id: str, inputs: dict) -> str:
    row, err = await _resolve_reply(brokerage_id, inputs)
    if err:
        return err
    assert row is not None
    await sb.update_pending_email_reply(
        row["id"],
        {"status": "dismissed", "resolved_at": datetime.now(timezone.utc).isoformat()},
    )
    return "Done — I won't send that one."


_TOOL_MAP = {
    "list_transactions": _exec_list_transactions,
    "get_transaction_details": _exec_get_transaction_details,
    "update_transaction_stage": _exec_update_transaction_stage,
    "add_transaction_note": _exec_add_transaction_note,
    "preview_intro_email": _exec_preview_intro_email,
    "send_intro_email": _exec_send_intro_email,
    "draft_document": _exec_draft_document,
    "list_deadlines": _exec_list_deadlines,
    "add_deadline": _exec_add_deadline,
    "review_compliance": _exec_review_compliance,
    "get_comparable_sales": _exec_get_comparable_sales,
    "propose_showing_times": _exec_propose_showing_times,
    "book_appointment": _exec_book_appointment,
    "notify_appointment_parties": _exec_notify_appointment_parties,
    "list_appointments": _exec_list_appointments,
    "get_upcoming_appointments": _exec_get_upcoming_appointments,
    "get_compliance_checklist": _exec_get_compliance_checklist,
    "mark_checklist_item": _exec_mark_checklist_item,
    "get_emd_status": _exec_get_emd_status,
    "mark_emd_received": _exec_mark_emd_received,
    "get_pending_tasks": _exec_get_pending_tasks,
    "mark_task_complete": _exec_mark_task_complete,
    "suggest_next_actions": _exec_suggest_next_actions,
    "approve_and_send_reply": _exec_approve_and_send_reply,
    "schedule_reply": _exec_schedule_reply,
    "edit_reply": _exec_edit_reply,
    "dismiss_reply": _exec_dismiss_reply,
}


# --------------------------------------------------------------------------- #
# Agent entry point
# --------------------------------------------------------------------------- #

async def run_penny_agent(
    brokerage_id: str,
    brokerage_name: str,
    contact_display_name: str | None,
    history: list[dict[str, Any]],
    current_message: str,
    agent_id: str | None = None,
    channel: str = "whatsapp",
    transaction_id: str | None = None,
) -> str:
    """Run the Penny conversational agent and return a reply.

    Args:
        brokerage_id: The brokerage UUID (for DB-scoped tool calls).
        brokerage_name: Human-readable brokerage name for the system prompt.
        contact_display_name: Realtor's registered display name (or None).
        history: Recent messages, oldest-first. Each has keys:
                 direction ('inbound'|'outbound'), body.
        current_message: The realtor's current message text (already transcribed
                         if it was a voice memo).
        agent_id: The requesting agent's UUID, when the contact is linked to one —
                  used to apply that agent's personal style to drafted documents.
        channel: 'whatsapp' (text-message tone) or 'web' (in-app chat panel tone).
                 Only shapes the communication-style guidance; tools are identical.

    Returns:
        Plain text reply suitable for the originating channel.
    """
    if not settings.ANTHROPIC_API_KEY:
        return (
            "I'm not fully configured yet — please ask your broker to set the "
            "ANTHROPIC_API_KEY on the backend."
        )

    _current_agent_id.set(agent_id)
    _current_transaction_id.set(transaction_id)

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    today = date.today().strftime("%B %d, %Y")
    agent_label = contact_display_name or "the agent"

    # On the email channel we know the deal the thread is about. Surface any open
    # suggested replies to outside parties so the agent can approve / defer them
    # in plain language (approve_and_send_reply / schedule_reply / edit / dismiss).
    pending_reply_block = ""
    if transaction_id:
        try:
            open_replies = [
                r
                for r in await sb.list_pending_email_replies_for_transaction(transaction_id)
                if r.get("status") in _OPEN_REPLY_STATUSES
            ]
        except sb.SupabaseError:
            open_replies = []
        if open_replies:
            parts = [
                "\nSuggested replies awaiting this agent's decision on this deal:",
            ]
            for r in open_replies:
                state = r.get("status")
                when = ""
                if state == "scheduled" and r.get("scheduled_send_at"):
                    when = f" (currently scheduled for {r['scheduled_send_at']})"
                elif state == "awaiting_event" and r.get("trigger_event"):
                    when = f" (currently waiting for {_event_label(r['trigger_event'])})"
                elif state == "held":
                    when = " (currently on hold)"
                parts.append(
                    f"- id={r.get('id')} → reply to {r.get('to_name') or r.get('to_email')}, "
                    f"subject \"{(r.get('subject') or '').strip()}\"{when}.\n"
                    f"  Their message summary: {r.get('summary') or '(none)'}\n"
                    f"  Proposed reply: {(r.get('draft_body') or '').strip()[:500]}"
                )
            parts.append(
                "If the agent approves, call approve_and_send_reply (their approval is "
                "the confirmation). If they want to wait, call schedule_reply. If they "
                "want changes, call edit_reply. If they say drop it, call dismiss_reply. "
                "When unsure which they mean, ask."
            )
            pending_reply_block = "\n".join(parts) + "\n\n"

    # Is this brokerage pre-authorised to send intro emails autonomously?
    intro_autonomous = False
    try:
        autonomy = await sb.get_task_autonomy(brokerage_id)
        intro_autonomous = any(
            r.get("task_id") == "intro-email" and r.get("autonomous")
            for r in autonomy
        )
    except Exception:
        intro_autonomous = False

    if intro_autonomous:
        intro_rule = (
            "- This brokerage has pre-authorised autonomous intro emails. When the "
            "agent asks you to send one, call preview_intro_email to show what will "
            "go out, then call send_intro_email with confirmed=true."
        )
    else:
        intro_rule = (
            "- Intro emails are NOT autonomous for this brokerage. You MUST call "
            "preview_intro_email and get the agent's explicit 'yes' before calling "
            "send_intro_email with confirmed=true. Never send without that confirmation."
        )

    if channel == "web":
        channel_intro = (
            "You help agents manage their transactions from the Penny web app, "
            "through this chat panel."
        )
        style_block = (
            "Communication style:\n"
            "- You're in a web chat panel. Be concise and direct: a short answer or a "
            "few short dash-prefixed lines, not long essays.\n"
            "- Write PLAIN TEXT only. Do NOT use markdown: no ** for bold, no # headers, "
            "no tables. For a heading just write the words and a colon. Use plain dashes "
            "for lists.\n"
            "- Numbers and dates should be human-readable (e.g. 'May 26, 2026', '$450,000').\n"
            "- If you cannot find a transaction, say so and suggest the agent be more specific.\n"
            "- Never invent data. Only report what the tools return.\n\n"
        )
    elif channel == "email":
        channel_intro = (
            "You are replying to one of the brokerage's own agents over email — they "
            "emailed you about a deal and you answer by email, in the same thread."
        )
        style_block = (
            "Communication style:\n"
            "- This is an email reply to a colleague. Be professional but warm, and get "
            "to the point: a short paragraph or a few dash-prefixed lines.\n"
            "- Write PLAIN TEXT only (it is rendered as an email body). No markdown: no "
            "** for bold, no # headers, no tables. Plain dashes for lists.\n"
            "- Do NOT add a greeting line with the recipient's name unless it reads "
            "naturally, and do NOT sign off with a name — the email already carries the "
            "Penny signature and disclosure.\n"
            "- Numbers and dates should be human-readable (e.g. 'May 26, 2026', '$450,000').\n"
            "- If you cannot find a transaction, say so and ask the agent to clarify.\n"
            "- Never invent data. Only report what the tools return.\n"
            "- You are emailing the agent, not an outside party. Anything that sends or "
            "commits to outside parties (intro email, document send, notifying parties) "
            "still requires the agent's explicit confirmation.\n\n"
        )
    else:
        channel_intro = "You help agents manage their transactions via WhatsApp."
        style_block = (
            "Communication style:\n"
            "- Keep replies concise and conversational — this is a text message interface.\n"
            "- Use plain text only. No markdown tables, no bullet markdown (use plain dashes).\n"
            "- Numbers and dates should be human-readable (e.g. 'May 26, 2026', '$450,000').\n"
            "- If you cannot find a transaction, say so and suggest the agent be more specific.\n"
            "- Never invent data. Only report what the tools return.\n\n"
        )

    system = (
        f"You are Penny, a real estate transaction coordinator assistant for "
        f"{brokerage_name}. {channel_intro}\n\n"
        f"Today's date: {today}\n"
        f"You are speaking with: {agent_label}\n\n"
        f"{style_block}"
        "Punctuation: never use em dashes (—) or en dashes (–) in your replies. "
        "Rephrase with a period, comma, colon, or 'and'. This is a firm style rule.\n\n"
        "Scope (stay in your lane):\n"
        "- You help with real estate transaction coordination: what you can do, "
        "specifics of this brokerage's deals, how to set up and use the Penny web "
        "app, and the coordination work itself (deadlines, scheduling, documents, "
        "compliance, comps, EMD, parties). Answer those fully.\n"
        "- For anything outside that (general knowledge, coding, personal tasks, "
        "writing unrelated to a deal, current events, trivia), don't answer it. Give "
        "one friendly line steering back to your job, e.g. 'That's outside what I "
        "handle, but I can help with your deals, the app, or scheduling.' Keep it "
        "brief and don't lecture.\n"
        "- Legal, tax, and financial advice are a hard line: do NOT give an opinion "
        "or interpretation, even if it sounds real-estate-adjacent (whether a clause "
        "is enforceable, tax consequences of a sale, what someone legally must do). "
        "Decline and point the agent to a licensed attorney, CPA, or their broker. "
        "You may still state plain facts already on the deal (dates, amounts, "
        "what a contingency window is) and surface compliance items to verify, but "
        "never the judgment call.\n"
        "- Don't be over-strict: questions about how a transaction works, how to use "
        "a feature, or what a real estate term means ARE in scope. Only redirect when "
        "the ask is genuinely off-topic or is an advice request above.\n\n"
        "Where things live in the web app (use these real locations, never invent "
        "menu names or steps):\n"
        "- The left sidebar is the main nav. Top-level pages: 'Ask Penny' (the home "
        "chat), 'Dashboard' (the full pipeline), 'Needs Review' (broker review "
        "queue, admin only), 'Listings' (MLS listing prep), 'Reports' (broker "
        "reporting, admin only), 'Brand & Style' (letterhead and writing-style "
        "rules), 'Team' (agents and their per-agent style), 'Messaging' (WhatsApp "
        "and SMS numbers plus Reply Handling settings), 'Calendar' (connect a Google "
        "Calendar), 'Compliance' (AI-disclosure and consent settings), and 'Autonomy' "
        "(which tasks Penny may do unattended, plus Document Routing rules).\n"
        "- To connect a calendar: open 'Calendar' in the sidebar and use the Connect "
        "Google Calendar button. A brokerage admin can also connect an individual "
        "agent's calendar from there.\n"
        "- Per-deal work happens on the transaction page (open a deal from the "
        "Dashboard or a Dashboard card). That page has a section nav down the side "
        "with these panels: Details, Deadlines, Scheduling, Earnest Money, Tasks, "
        "Compliance File, Compliance Review, Comparable Sales, Communications, Draft "
        "Document, Signatures, and Contract.\n"
        "- If you are not sure exactly where a setting lives, say so and point them at "
        "the closest sidebar section rather than inventing a path. Never describe "
        "buttons, menus, or steps you are not sure exist.\n\n"
        f"{pending_reply_block}"
        "Sending the intro email:\n"
        "- The intro email introduces every party on a deal (buyer, seller, agents, "
        "lender, title) to each other and presents you as the coordinator.\n"
        f"{intro_rule}\n\n"
        "Deadlines:\n"
        "- You can track deadlines (inspection, financing, appraisal, closing) with "
        "add_deadline and review them with list_deadlines. The agent is reminded "
        "automatically at the 5-day, 2-day, and day-of marks — you don't send those "
        "reminders yourself.\n\n"
        "Compliance:\n"
        "- review_compliance surfaces compliance findings for a deal. You NEVER "
        "approve compliance and never tell the agent a deal is compliant — only "
        "report what to verify and remind them a human must sign off in the web app.\n\n"
        "Comparable sales:\n"
        "- get_comparable_sales pulls comps and an estimated value for any property "
        "address. Use it when the agent asks about comps, a CMA, or what a home is "
        "worth. Present figures plainly and note they're estimates.\n\n"
        "Scheduling:\n"
        "- propose_showing_times suggests open slots; book_appointment books one. "
        "Booking creates a calendar event, so you MUST get the agent's explicit "
        "confirmation of the time before calling book_appointment with confirmed=true "
        "(unless scheduling is autonomous for this brokerage). When booking, ask what "
        "kind of appointment it is (showing, inspection, walkthrough, closing) and pass "
        "it as the type. list_appointments shows one deal's appointments; "
        "get_upcoming_appointments shows what's coming up across ALL the agent's deals, "
        "so use it for general 'what's on my calendar' or 'what's next' questions.\n"
        "- After you book a time, be a coordinator: offer to reach the parties who need "
        "to agree (the listing agent for access, the buyer for availability) with "
        "notify_appointment_parties. Frame it as PROPOSING the time, never confirming it "
        "— outside parties still have to agree, so never tell anyone the time is locked. "
        "This emails outside parties, so it's confirm-gated: get the agent's go-ahead, "
        "then call with confirmed=true.\n\n"
        "Compliance file:\n"
        "- get_compliance_checklist shows what required documents are still missing from "
        "a deal's file. mark_checklist_item marks an item complete/waived — confirm the "
        "exact item with the agent first, then call with confirmed=true.\n\n"
        "Next steps / tasks:\n"
        "- get_pending_tasks shows what needs to happen next on a deal, grouped by "
        "urgency. mark_task_complete marks one done — confirm the exact task first, "
        "then call with confirmed=true.\n\n"
        "Earnest money:\n"
        "- get_emd_status reports whether the earnest money deposit has been received. "
        "mark_emd_received records receipt — confirm with the agent first, then call "
        "with confirmed=true. Penny tracks EMD receipt only — never trust-account math.\n\n"
        "Proactive next moves (important):\n"
        "- When a tool surfaces a list of pending things (tasks, missing checklist "
        "items, upcoming deadlines), don't just enumerate. For each item, infer the "
        "concrete next action and offer to take it — NOT 'want me to mark this "
        "complete?'. mark_task_complete and mark_checklist_item are for after the "
        "work is done, not the offer itself.\n"
        "- Common task → action mappings:\n"
        "    'Order inspection' / 'Schedule walkthrough' → propose_showing_times "
        "(then book_appointment after the agent picks a slot)\n"
        "    'Verify lender has application' / lender follow-up → draft_document "
        "(audience='the lender')\n"
        "    'Confirm EMD receipt' / 'Earnest money' task → get_emd_status first; "
        "if not received, draft_document (audience='title company') asking for the "
        "receipt\n"
        "    'Send intro email' task → preview_intro_email (then send_intro_email "
        "after confirmation)\n"
        "    'Order appraisal' / appraisal task → draft_document (audience='the "
        "lender') about appraisal scheduling\n"
        "    'Final walkthrough' task → propose_showing_times\n"
        "- If a party email is missing on a deal (lender_email, title_email, etc.) "
        "and you'd need it for the action, flag it explicitly — you can't email "
        "someone you can't reach. Ask the agent for the contact.\n"
        "- Offer ONE specific action per item ('I can draft an email to the lender "
        "now — want me to?'), not a buffet of options.\n"
        "- For broad 'what should I do?' / 'what's next?' / 'where are we?' "
        "questions — especially without a specific deal in mind — call "
        "suggest_next_actions for a curated top-3 synthesis instead of dumping raw "
        "task lists. Pass address_query to scope to one deal, or omit it for "
        "brokerage-wide.\n\n"
        "Synthesis:\n"
        "- suggest_next_actions cross-references pending tasks, missing checklist "
        "items, EMD status, upcoming deadlines, and missing party contacts to "
        "surface the most impactful next moves. Use it instead of a raw "
        "get_pending_tasks dump when the agent asks an open question like 'what "
        "should I do' or 'what's next.'"
    )

    # Build the messages array from history + current message.
    messages: list[dict[str, Any]] = []
    for msg in history:
        role = "user" if msg["direction"] == "inbound" else "assistant"
        messages.append({"role": role, "content": msg["body"] or ""})

    # Deduplicate consecutive same-role messages (Claude requires alternating roles).
    merged: list[dict[str, Any]] = []
    for msg in messages:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] += f"\n{msg['content']}"
        else:
            merged.append(dict(msg))
    messages = merged

    # Append the current inbound message.
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += f"\n{current_message}"
    else:
        messages.append({"role": "user", "content": current_message})

    # Cache the stable prefix (tools + system) so it isn't re-billed on every
    # tool-loop round or follow-up turn. The whole system string is one cached
    # block: same brokerage + same day = cache hit; a new day just writes a
    # fresh entry. Tools render before system, so this breakpoint caches both.
    system_blocks = [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
    ]

    # Accumulate token usage across all tool rounds; logged once on exit for
    # per-brokerage unit-economics tracking.
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    try:
        # Agentic tool-use loop.
        for _ in range(8):  # max 8 tool rounds to prevent runaway loops
            response = await client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system_blocks,
                tools=_TOOLS,
                messages=messages,
            )

            u = response.usage
            usage["input_tokens"] += u.input_tokens or 0
            usage["output_tokens"] += u.output_tokens or 0
            usage["cache_creation_input_tokens"] += (
                getattr(u, "cache_creation_input_tokens", 0) or 0
            )
            usage["cache_read_input_tokens"] += (
                getattr(u, "cache_read_input_tokens", 0) or 0
            )

            if response.stop_reason == "end_turn":
                # Extract the final text reply.
                text_parts = [
                    block.text for block in response.content if block.type == "text"
                ]
                return " ".join(text_parts).strip() or "Done."

            if response.stop_reason == "tool_use":
                # Add the assistant's tool-use turn to the conversation.
                messages.append({"role": "assistant", "content": response.content})

                # Execute all tool calls and collect results.
                tool_results: list[dict[str, Any]] = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    executor = _TOOL_MAP.get(block.name)
                    if executor is None:
                        result_text = f"Unknown tool: {block.name}"
                    else:
                        try:
                            result_text = await executor(brokerage_id, block.input)
                        except Exception as exc:
                            result_text = f"Tool error: {exc}"

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })

                messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason — return whatever text we have.
            text_parts = [
                block.text for block in response.content if block.type == "text"
            ]
            return (
                " ".join(text_parts).strip()
                or "I'm not sure how to help with that."
            )

        return "I ran into a problem processing your request. Please try again."
    finally:
        if any(usage.values()):
            try:
                await sb.log_ai_usage(brokerage_id, f"agent_{channel}", MODEL, usage)
            except Exception:
                pass
