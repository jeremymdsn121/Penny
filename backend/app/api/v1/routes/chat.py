"""Web chat with Penny.

The same conversational agent that powers WhatsApp/SMS, exposed over an
authenticated browser endpoint so brokers can ask Penny about their pipeline,
deadlines, compliance file, comps, etc. from the web app's home screen.

Stateless: the client holds the thread and replays recent turns on each call,
so no new table/migration is needed. Tools and confirmation gates are identical
to the messaging channels — this only changes the entry point and the reply tone.
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.security import get_current_brokerage, get_current_user
from app.services import penny_agent

router = APIRouter(prefix="/chat", tags=["chat"])

# Cap replayed history so a long-lived browser thread can't blow up token use.
_MAX_HISTORY_TURNS = 20


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
