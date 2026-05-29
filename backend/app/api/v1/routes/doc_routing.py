"""Document routing configuration + send queue (Autonomy task ``doc-routing``).

Two surfaces:
  * Rules CRUD — per-brokerage config for which stage routes which document to
    which parties.
  * Pending queue — when doc-routing autonomy is off, fired rules land here; the
    deal's agent reviews and confirms each send (confirm-gated, never auto).

Sending a document is a hard-rule confirmed action: ``/pending/{id}/send``
requires ``confirmed=true``. There is no bypass flag.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage, get_current_user
from app.services import doc_routing

router = APIRouter(prefix="/doc-routing", tags=["doc-routing"])


class RuleIn(BaseModel):
    trigger_stage: str
    recipient_roles: list[str] = []
    document_source: str = "contract"
    enabled: bool = True


class RulePatch(BaseModel):
    trigger_stage: str | None = None
    recipient_roles: list[str] | None = None
    document_source: str | None = None
    enabled: bool | None = None


class SendIn(BaseModel):
    confirmed: bool = False


def _validate(stage: str | None, roles: list[str] | None, source: str | None) -> None:
    if stage is not None and stage not in doc_routing.VALID_STAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"trigger_stage must be one of {sorted(doc_routing.VALID_STAGES)}",
        )
    if roles is not None:
        bad = [r for r in roles if r not in doc_routing.VALID_ROLES]
        if bad:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown recipient role(s): {bad}",
            )
    if source is not None and source not in doc_routing.VALID_DOCUMENT_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"document_source must be one of {sorted(doc_routing.VALID_DOCUMENT_SOURCES)}",
        )


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #

@router.get("/rules")
async def list_rules(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    return await sb.list_doc_routing_rules(brokerage["id"])


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: RuleIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    _validate(body.trigger_stage, body.recipient_roles, body.document_source)
    return await sb.insert_doc_routing_rule(
        {
            "brokerage_id": brokerage["id"],
            "trigger_stage": body.trigger_stage,
            "recipient_roles": body.recipient_roles,
            "document_source": body.document_source,
            "enabled": body.enabled,
        }
    )


async def _require_rule(brokerage_id: str, rule_id: str) -> dict[str, Any]:
    rule = await sb.get_doc_routing_rule(rule_id)
    if rule is None or rule.get("brokerage_id") != brokerage_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


@router.patch("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    body: RulePatch,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    await _require_rule(brokerage["id"], rule_id)
    _validate(body.trigger_stage, body.recipient_roles, body.document_source)
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update")
    return await sb.update_doc_routing_rule(rule_id, data)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    await _require_rule(brokerage["id"], rule_id)
    await sb.delete_doc_routing_rule(rule_id)


# --------------------------------------------------------------------------- #
# Pending send queue
# --------------------------------------------------------------------------- #

@router.get("/pending")
async def list_pending(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    return await sb.list_pending_doc_routes(brokerage["id"], status_filter="pending")


async def _require_pending(brokerage_id: str, route_id: str) -> dict[str, Any]:
    route = await sb.get_pending_doc_route(route_id)
    if route is None or route.get("brokerage_id") != brokerage_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    return route


@router.post("/pending/{route_id}/send")
async def send_pending(
    route_id: str,
    body: SendIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required before sending.",
        )
    route = await _require_pending(brokerage["id"], route_id)
    if route.get("status") != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Route is already {route.get('status')}.",
        )
    tx = await sb.get_transaction(brokerage["id"], route["transaction_id"])
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    sent, reason = await doc_routing.send_pending_route(route, tx)
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=reason or "Send failed.",
        )
    updated = await sb.update_pending_doc_route(
        route_id,
        {
            "status": "sent",
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolved_by": user.get("id"),
        },
    )
    return updated


@router.post("/pending/{route_id}/dismiss")
async def dismiss_pending(
    route_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    route = await _require_pending(brokerage["id"], route_id)
    if route.get("status") != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Route is already {route.get('status')}.",
        )
    return await sb.update_pending_doc_route(
        route_id,
        {
            "status": "dismissed",
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolved_by": user.get("id"),
        },
    )
