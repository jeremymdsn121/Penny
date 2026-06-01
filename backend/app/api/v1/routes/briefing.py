"""Home-page briefing — the proactive "what should I tackle?" surface.

``GET /briefing/next-actions`` returns a prioritized, curated list of concrete
next moves across the brokerage's active deals, synthesized by
``services/next_actions``. This is the same logic behind Sloane's
``suggest_next_actions`` chat tool, exposed deterministically for the landing
page so the briefing renders instantly without an LLM round-trip.

Available to any authenticated agent (it's their own home page) — unlike the
admin-only broker review queue.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.core.security import get_current_brokerage
from app.services import next_actions

router = APIRouter(prefix="/briefing", tags=["briefing"])


@router.get("/next-actions")
async def next_actions_briefing(
    limit: int = 3,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Top next moves across active deals, prioritized. Read-only."""
    limit = max(1, min(limit, 10))
    actions = await next_actions.collect_for_brokerage(brokerage["id"])
    top, remaining = next_actions.top_actions(actions, limit=limit)
    return {"actions": top, "remaining": remaining, "total": len(actions)}
