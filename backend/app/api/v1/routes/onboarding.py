from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.constants import (
    DETAILED_RULESET_STATES,
    LOCKED_TASK_IDS,
    TASK_DEFINITIONS,
    TASK_IDS,
    US_STATES,
)
from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.schemas.auth import BrokerageOut
from app.schemas.onboarding import OnboardingOptions, OnboardingSubmit

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _brokerage_out(row: dict[str, Any]) -> BrokerageOut:
    return BrokerageOut(**{k: row.get(k) for k in BrokerageOut.model_fields})


@router.get("/options", response_model=OnboardingOptions)
async def options() -> OnboardingOptions:
    """Static choices the wizard renders: states + task definitions."""
    return OnboardingOptions(
        states=US_STATES,
        detailed_ruleset_states=DETAILED_RULESET_STATES,
        tasks=TASK_DEFINITIONS,
    )


@router.post("", response_model=BrokerageOut)
async def submit(
    body: OnboardingSubmit,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> BrokerageOut:
    state = body.state.upper()

    # Validate task ids and enforce the compliance lock server-side.
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in body.tasks:
        if item.task_id not in TASK_IDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown task_id: {item.task_id}",
            )
        autonomous = False if item.task_id in LOCKED_TASK_IDS else item.autonomous
        tasks.append({"task_id": item.task_id, "autonomous": autonomous})
        seen.add(item.task_id)

    # Ensure every defined task has a row, defaulting any omitted ones to false.
    for definition in TASK_DEFINITIONS:
        if definition["task_id"] not in seen:
            tasks.append({"task_id": definition["task_id"], "autonomous": False})

    updated = await sb.update_brokerage(
        brokerage["id"],
        {
            "name": body.name,
            "assistant_name": body.assistant_name,
            "state": state,
            "email": body.email,
            "phone": body.phone,
            "email_mode": body.email_mode,
            "monitor_email": body.monitor_email if body.email_mode == "monitor" else None,
            "calendar_provider": body.calendar_provider,
            "work_start": body.work_start,
            "work_end": body.work_end,
            "buffer_minutes": body.buffer_minutes,
            "showing_method": body.showing_method,
            "onboarding_completed": True,
        },
    )
    await sb.replace_task_autonomy(brokerage["id"], tasks)
    return _brokerage_out(updated)
