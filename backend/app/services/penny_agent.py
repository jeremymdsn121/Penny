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
from datetime import date, datetime, timezone
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings
from app.core import supabase_client as sb
from app.services import compliance, doc_generate, email_client

MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 1024

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
    updated = await sb.update_transaction(brokerage_id, tx["id"], {"stage": new_stage})
    if updated:
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
    if not inputs.get("confirmed"):
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
        email_client.send_intro_email, tx, brokerage_name
    )
    if not result["sent"]:
        return f"I couldn't send the intro email: {result['reason']}."
    await sb.update_transaction(brokerage_id, tx["id"], {"intro_email_sent": True})
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
    rules = await sb.get_confirmed_knowledge_rules(brokerage_id)
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
) -> str:
    """Run the Penny conversational agent and return a WhatsApp-ready reply.

    Args:
        brokerage_id: The brokerage UUID (for DB-scoped tool calls).
        brokerage_name: Human-readable brokerage name for the system prompt.
        contact_display_name: Realtor's registered display name (or None).
        history: Recent messages from whatsapp_messages, oldest-first.
                 Each has keys: direction ('inbound'|'outbound'), body.
        current_message: The realtor's current message text (already transcribed
                         if it was a voice memo).

    Returns:
        Plain text reply to send via WhatsApp.
    """
    if not settings.ANTHROPIC_API_KEY:
        return (
            "I'm not fully configured yet — please ask your broker to set the "
            "ANTHROPIC_API_KEY on the backend."
        )

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    today = date.today().strftime("%B %d, %Y")
    agent_label = contact_display_name or "the agent"

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

    system = (
        f"You are Penny, a real estate transaction coordinator assistant for "
        f"{brokerage_name}. You help agents manage their transactions via WhatsApp.\n\n"
        f"Today's date: {today}\n"
        f"You are speaking with: {agent_label}\n\n"
        "Communication style:\n"
        "- Keep replies concise and conversational — this is a text message interface.\n"
        "- Use plain text only. No markdown tables, no bullet markdown (use plain dashes).\n"
        "- Numbers and dates should be human-readable (e.g. 'May 26, 2026', '$450,000').\n"
        "- If you cannot find a transaction, say so and suggest the agent be more specific.\n"
        "- Never invent data. Only report what the tools return.\n\n"
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
        "report what to verify and remind them a human must sign off in the web app."
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

    # Agentic tool-use loop.
    for _ in range(8):  # max 8 tool rounds to prevent runaway loops
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=_TOOLS,
            messages=messages,
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
        return " ".join(text_parts).strip() or "I'm not sure how to help with that."

    return "I ran into a problem processing your request. Please try again."
