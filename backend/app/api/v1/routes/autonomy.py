"""Post-onboarding task-autonomy settings.

Onboarding sets the initial autonomy toggles; this exposes them as an editable
settings surface afterward. Same data model (`task_autonomy`), same rules: the
compliance task is locked and can never be made autonomous.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.constants import LOCKED_TASK_IDS, TASK_DEFINITIONS, TASK_IDS
from app.core import supabase_client as sb
from app.core.security import get_current_brokerage, require_admin
from app.schemas.onboarding import TaskAutonomyItem

# Admin-only surface (see security.require_admin — a no-op until multi-seat).
router = APIRouter(
    prefix="/autonomy", tags=["autonomy"], dependencies=[Depends(require_admin)]
)


class AutonomyUpdate(BaseModel):
    tasks: list[TaskAutonomyItem]


async def _merged(brokerage_id: str) -> dict[str, Any]:
    """Task definitions joined with this brokerage's current autonomy values."""
    stored = {
        r["task_id"]: r.get("autonomous", False)
        for r in await sb.get_task_autonomy(brokerage_id)
    }
    tasks = []
    for d in TASK_DEFINITIONS:
        autonomous = (
            False
            if d["task_id"] in LOCKED_TASK_IDS
            else stored.get(d["task_id"], d["default_autonomous"])
        )
        tasks.append({**d, "autonomous": autonomous})
    return {"tasks": tasks}


@router.get("")
async def get_autonomy(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Return every task definition plus its current autonomous flag."""
    return await _merged(brokerage["id"])


@router.put("")
async def update_autonomy(
    body: AutonomyUpdate,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Replace the brokerage's autonomy toggles (compliance stays locked off)."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in body.tasks:
        if item.task_id not in TASK_IDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown task_id: {item.task_id}",
            )
        autonomous = False if item.task_id in LOCKED_TASK_IDS else item.autonomous
        rows.append({"task_id": item.task_id, "autonomous": autonomous})
        seen.add(item.task_id)
    # Any task the client omitted defaults to "needs approval".
    for d in TASK_DEFINITIONS:
        if d["task_id"] not in seen:
            rows.append({"task_id": d["task_id"], "autonomous": False})

    await sb.replace_task_autonomy(brokerage["id"], rows)
    return await _merged(brokerage["id"])
