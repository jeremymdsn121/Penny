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

from datetime import date, datetime, timezone
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings
from app.core import supabase_client as sb

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


_TOOL_MAP = {
    "list_transactions": _exec_list_transactions,
    "get_transaction_details": _exec_get_transaction_details,
    "update_transaction_stage": _exec_update_transaction_stage,
    "add_transaction_note": _exec_add_transaction_note,
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
        "- Never invent data. Only report what the tools return."
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
