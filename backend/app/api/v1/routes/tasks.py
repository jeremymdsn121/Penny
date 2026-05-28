"""Per-transaction workflow tasks (V2 Section 3).

Tasks are generated automatically by the workflow engine (on stage entry and as
deadlines approach) and can also be added/skipped manually here.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage, get_current_user

router = APIRouter(prefix="/transactions", tags=["tasks"])

_STATUSES = {"pending", "complete", "skipped"}


async def _require_tx(brokerage_id: str, transaction_id: str) -> dict[str, Any]:
    tx = await sb.get_transaction(brokerage_id, transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return tx


async def _require_task(transaction_id: str, task_id: str) -> dict[str, Any]:
    task = await sb.get_transaction_task(task_id)
    if task is None or task.get("transaction_id") != transaction_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


class TaskIn(BaseModel):
    label: str
    description: str | None = None
    due_date: str | None = None
    assigned_to_role: str | None = None


class TaskPatch(BaseModel):
    status: str | None = None
    skip_reason: str | None = None
    due_date: str | None = None
    label: str | None = None


@router.get("/{transaction_id}/tasks")
async def list_tasks(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    await _require_tx(brokerage["id"], transaction_id)
    return await sb.list_transaction_tasks(transaction_id)


@router.post("/{transaction_id}/tasks", status_code=status.HTTP_201_CREATED)
async def add_task(
    transaction_id: str,
    body: TaskIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    await _require_tx(brokerage["id"], transaction_id)
    rows = await sb.insert_transaction_tasks(
        [
            {
                "transaction_id": transaction_id,
                "label": body.label,
                "description": body.description,
                "due_date": body.due_date,
                "assigned_to_role": body.assigned_to_role,
                "status": "pending",
            }
        ]
    )
    return rows[0]


@router.patch("/{transaction_id}/tasks/{task_id}")
async def patch_task(
    transaction_id: str,
    task_id: str,
    body: TaskPatch,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    await _require_tx(brokerage["id"], transaction_id)
    await _require_task(transaction_id, task_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        if data["status"] not in _STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"status must be one of {sorted(_STATUSES)}",
            )
        if data["status"] == "complete":
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
            data["completed_by"] = user.get("id")
        else:
            data["completed_at"] = None
            data["completed_by"] = None
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update")
    return await sb.update_transaction_task(task_id, data)


@router.delete("/{transaction_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    transaction_id: str,
    task_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    await _require_tx(brokerage["id"], transaction_id)
    await _require_task(transaction_id, task_id)
    await sb.delete_transaction_task(task_id)
