"""Compliance checklist endpoints (V2 Section 2A).

Two groups:
  - /compliance-templates       — the template library (system defaults + custom)
  - /transactions/{id}/checklist — the per-transaction closed-file checklist

The checklist tracks whether required documents are *in the file* (agency
disclosure, wire fraud advisory, lead-based paint, etc.) with completed-by and
timestamp tracking, so the broker-of-record has an audit-ready file.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage, get_current_user

router = APIRouter(tags=["compliance-checklist"])

COMPLIANCE_BUCKET = "compliance-docs"
MAX_DOC_BYTES = 25 * 1024 * 1024
_bucket_ready = False

_ITEM_STATUSES = {"pending", "complete", "waived", "not_applicable"}


async def _ensure_bucket() -> None:
    global _bucket_ready
    if not _bucket_ready:
        await sb.ensure_bucket(COMPLIANCE_BUCKET, public=False)
        _bucket_ready = True


async def _require_tx(brokerage_id: str, transaction_id: str) -> dict[str, Any]:
    tx = await sb.get_transaction(brokerage_id, transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return tx


async def _require_item(transaction_id: str, item_id: str) -> dict[str, Any]:
    item = await sb.get_checklist_item(item_id)
    if item is None or item.get("transaction_id") != transaction_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checklist item not found")
    return item


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #

class TemplateItemIn(BaseModel):
    label: str
    description: str | None = None
    required: bool = True
    document_required: bool = False
    sort_order: int = 0


class TemplateIn(BaseModel):
    name: str
    transaction_type: str = "buy_side"
    state: str | None = None
    clone_from: str | None = None  # template id to copy items from
    items: list[TemplateItemIn] | None = None


class TemplateUpdate(BaseModel):
    name: str | None = None
    state: str | None = None
    items: list[TemplateItemIn] | None = None


@router.get("/compliance-templates")
async def list_templates(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    templates = await sb.list_compliance_templates(brokerage["id"])
    for t in templates:
        t["items"] = await sb.get_template_items(t["id"])
    return templates


@router.post("/compliance-templates", status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    if body.transaction_type not in ("buy_side", "list_side", "dual_agency", "lease"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid transaction_type")
    template = await sb.insert_compliance_template(
        {
            "brokerage_id": brokerage["id"],
            "name": body.name,
            "transaction_type": body.transaction_type,
            "state": body.state,
            "is_system_default": False,
        }
    )

    # Source items: explicit list, or cloned from another template.
    items: list[dict[str, Any]] = []
    if body.items:
        items = [i.model_dump() for i in body.items]
    elif body.clone_from:
        src = await sb.get_compliance_template(brokerage["id"], body.clone_from)
        if src:
            for ti in await sb.get_template_items(src["id"]):
                items.append(
                    {
                        "label": ti["label"],
                        "description": ti.get("description"),
                        "required": ti.get("required", True),
                        "document_required": ti.get("document_required", False),
                        "sort_order": ti.get("sort_order", 0),
                    }
                )
    if items:
        await sb.insert_template_items(
            [{"template_id": template["id"], **i} for i in items]
        )
    template["items"] = await sb.get_template_items(template["id"])
    return template


@router.put("/compliance-templates/{template_id}")
async def update_template(
    template_id: str,
    body: TemplateUpdate,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    existing = await sb.get_compliance_template(brokerage["id"], template_id)
    if existing is None or not existing.get("brokerage_id"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Editable template not found (system defaults can't be edited).",
        )
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "items"}
    if fields:
        await sb.update_compliance_template(brokerage["id"], template_id, fields)
    if body.items is not None:
        await sb.delete_template_items(template_id)
        if body.items:
            await sb.insert_template_items(
                [{"template_id": template_id, **i.model_dump()} for i in body.items]
            )
    template = await sb.get_compliance_template(brokerage["id"], template_id)
    template["items"] = await sb.get_template_items(template_id)
    return template


# --------------------------------------------------------------------------- #
# Per-transaction checklist
# --------------------------------------------------------------------------- #

class ChecklistItemIn(BaseModel):
    label: str
    required: bool = True
    document_required: bool = False


class ChecklistItemPatch(BaseModel):
    status: str | None = None
    waiver_note: str | None = None
    document_url: str | None = None


@router.get("/transactions/{transaction_id}/checklist")
async def get_checklist(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    await _require_tx(brokerage["id"], transaction_id)
    return await sb.list_checklist_items(transaction_id)


@router.post("/transactions/{transaction_id}/checklist/items", status_code=status.HTTP_201_CREATED)
async def add_item(
    transaction_id: str,
    body: ChecklistItemIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    await _require_tx(brokerage["id"], transaction_id)
    existing = await sb.list_checklist_items(transaction_id)
    next_order = max((i.get("sort_order") or 0 for i in existing), default=0) + 1
    rows = await sb.insert_checklist_items(
        [
            {
                "transaction_id": transaction_id,
                "label": body.label,
                "required": body.required,
                "document_required": body.document_required,
                "status": "pending",
                "sort_order": next_order,
            }
        ]
    )
    return rows[0]


@router.patch("/transactions/{transaction_id}/checklist/items/{item_id}")
async def patch_item(
    transaction_id: str,
    item_id: str,
    body: ChecklistItemPatch,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    await _require_tx(brokerage["id"], transaction_id)
    await _require_item(transaction_id, item_id)

    data: dict[str, Any] = {}
    if body.status is not None:
        if body.status not in _ITEM_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"status must be one of {sorted(_ITEM_STATUSES)}",
            )
        data["status"] = body.status
        if body.status == "complete":
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
            data["completed_by"] = user.get("id")
        else:
            data["completed_at"] = None
            data["completed_by"] = None
    if body.waiver_note is not None:
        data["waiver_note"] = body.waiver_note
    if body.document_url is not None:
        data["document_url"] = body.document_url
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update")
    return await sb.update_checklist_item(item_id, data)


@router.delete(
    "/transactions/{transaction_id}/checklist/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_item(
    transaction_id: str,
    item_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    await _require_tx(brokerage["id"], transaction_id)
    item = await _require_item(transaction_id, item_id)
    if item.get("template_item_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template-derived items can't be deleted — waive or mark not applicable instead.",
        )
    await sb.delete_checklist_item(item_id)


@router.post("/transactions/{transaction_id}/checklist/items/{item_id}/document")
async def upload_item_document(
    transaction_id: str,
    item_id: str,
    file: UploadFile = File(...),
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Upload a supporting document for a checklist item and mark it complete."""
    await _require_tx(brokerage["id"], transaction_id)
    await _require_item(transaction_id, item_id)

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(content) > MAX_DOC_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the 25 MB limit",
        )
    await _ensure_bucket()
    ext = (file.filename or "file").rsplit(".", 1)[-1][:8] if "." in (file.filename or "") else "bin"
    path = f"{brokerage['id']}/{transaction_id}/{uuid.uuid4()}.{ext}"
    try:
        await sb.upload_object(
            COMPLIANCE_BUCKET, path, content, file.content_type or "application/octet-stream"
        )
    except sb.SupabaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"Upload failed: {exc.detail}")

    return await sb.update_checklist_item(
        item_id,
        {
            "document_url": path,
            "status": "complete",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "completed_by": user.get("id"),
        },
    )
