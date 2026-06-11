"""Web chat with Penny.

The same conversational agent that powers WhatsApp/SMS, exposed over an
authenticated browser endpoint so brokers can ask Penny about their pipeline,
deadlines, compliance file, comps, etc. from the web app's home screen.

Stateless: the client holds the thread and replays recent turns on each call,
so no new table/migration is needed. Tools and confirmation gates are identical
to the messaging channels — this only changes the entry point and the reply tone.
"""

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.config import settings
from app.core import supabase_client as sb
from app.core.security import get_current_brokerage, get_current_user
from app.services import penny_agent

router = APIRouter(prefix="/chat", tags=["chat"])

# Cap replayed history so a long-lived browser thread can't blow up token use.
_MAX_HISTORY_TURNS = 20

_BREATHER_REPLY = (
    "I've handled a lot of questions for your brokerage today and I'm taking a "
    "short breather to keep things running smoothly. Try me again a little later "
    "— and if you're regularly hitting this, let's talk about raising the limit."
)


async def _over_daily_cap(brokerage_id: str) -> bool:
    """True when the brokerage has burned past its soft daily token ceiling."""
    cap = settings.AI_DAILY_TOKEN_CAP_PER_BROKERAGE
    if cap <= 0:
        return False  # cap disabled
    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    used = await sb.ai_tokens_used_today(brokerage_id, midnight.isoformat())
    return used >= cap


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)


class ChatOut(BaseModel):
    reply: str


def _display_name(user: dict[str, Any]) -> str | None:
    meta = user.get("user_metadata") or {}
    for key in ("full_name", "name", "display_name"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


@router.post("", response_model=ChatOut)
async def chat(
    body: ChatIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> ChatOut:
    """Run one turn of the Penny web-chat agent and return its reply."""
    # Soft cost ceiling: stop running the (expensive, tool-looping) agent once a
    # brokerage has burned its daily token budget — runaway/abuse protection on
    # our API key. Returns a normal reply shape, not an error, so the UI degrades
    # gracefully rather than showing a failure.
    if await _over_daily_cap(brokerage["id"]):
        return ChatOut(reply=_BREATHER_REPLY)

    # Map the browser-side {role, content} thread to the agent's
    # {direction, body} history shape, keeping only the most recent turns.
    recent = body.history[-_MAX_HISTORY_TURNS:]
    history = [
        {
            "direction": "inbound" if turn.role == "user" else "outbound",
            "body": turn.content,
        }
        for turn in recent
    ]

    reply = await penny_agent.run_penny_agent(
        brokerage_id=brokerage["id"],
        brokerage_name=brokerage.get("name", "your brokerage"),
        contact_display_name=_display_name(user),
        history=history,
        current_message=body.message,
        channel="web",
    )
    return ChatOut(reply=reply)
