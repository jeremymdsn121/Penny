"""Agents — brokerage roster + per-agent style profiles (V2 Section 1B).

The brokerage admin manages the agent roster here. Each agent can also build a
personal "My Style" profile: upload a sample letter/email, Penny proposes style
rules (stored unconfirmed with the agent's agent_id), the agent confirms them,
and those confirmed rules layer on top of the brokerage-wide style for that
agent's generated documents (see supabase_client.get_confirmed_knowledge_rules).

Confirming/editing/deleting individual proposed rules reuses the existing
knowledge endpoints (PATCH/DELETE /knowledge/rules/{id}) — they are scoped by
brokerage_id + rule id and work for agent-scoped rules too.

All endpoints require a valid JWT and are scoped to the caller's brokerage.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.services import style_extract

router = APIRouter(prefix="/agents", tags=["agents"])

KNOWLEDGE_BUCKET = "knowledge-docs"
MAX_DOC_BYTES = 25 * 1024 * 1024  # 25 MB

_EXT_BY_KIND = {"pdf": "pdf", "image": "img", "docx": "docx"}
_bucket_ready = False


async def _ensure_bucket() -> None:
    global _bucket_ready
    if not _bucket_ready:
        await sb.ensure_bucket(KNOWLEDGE_BUCKET, public=False)
        _bucket_ready = True


def _ext(filename: str | None, kind: str) -> str:
    name = (filename or "").lower()
    if "." in name:
        return name.rsplit(".", 1)[-1][:8]
    return _EXT_BY_KIND.get(kind, "bin")


async def _require_agent(brokerage_id: str, agent_id: str) -> dict[str, Any]:
    agent = await sb.get_agent(brokerage_id, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


class AgentIn(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    license_number: str | None = None
    role: str | None = None


class AgentUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    license_number: str | None = None
    role: str | None = None


# --------------------------------------------------------------------------- #
# Roster CRUD
# --------------------------------------------------------------------------- #

@router.get("")
async def list_all(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    """List agents with a count of confirmed style rules each has on file."""
    agents = await sb.list_agents(brokerage["id"])
    counts = await sb.count_agent_style_rules(brokerage["id"])
    for a in agents:
        a["style_rule_count"] = counts.get(a["id"], 0)
    return agents


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    body: AgentIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    data["brokerage_id"] = brokerage["id"]
    return await sb.insert_agent(data)


@router.patch("/{agent_id}")
async def update_one(
    agent_id: str,
    body: AgentUpdate,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update")
    agent = await sb.update_agent(brokerage["id"], agent_id, data)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_one(
    agent_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    await _require_agent(brokerage["id"], agent_id)
    await sb.delete_agent(brokerage["id"], agent_id)


# --------------------------------------------------------------------------- #
# Per-agent style profile
# --------------------------------------------------------------------------- #

@router.get("/{agent_id}/style-rules")
async def list_style_rules(
    agent_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    await _require_agent(brokerage["id"], agent_id)
    return await sb.list_knowledge_rules_for_agent(brokerage["id"], agent_id)


@router.get("/{agent_id}/style-documents")
async def list_style_documents(
    agent_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    await _require_agent(brokerage["id"], agent_id)
    return await sb.list_knowledge_documents_for_agent(brokerage["id"], agent_id)


@router.post("/{agent_id}/style-documents", status_code=status.HTTP_201_CREATED)
async def upload_style_document(
    agent_id: str,
    file: UploadFile = File(...),
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Upload an agent's sample letter/email and propose agent-scoped style rules."""
    await _require_agent(brokerage["id"], agent_id)

    kind = style_extract.infer_kind(file.content_type, file.filename)
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type — upload a PDF, image, or .docx.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(content) > MAX_DOC_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the 25 MB limit",
        )

    await _ensure_bucket()
    path = f"{brokerage['id']}/agents/{agent_id}/{uuid.uuid4()}.{_ext(file.filename, kind)}"
    try:
        await sb.upload_object(
            KNOWLEDGE_BUCKET, path, content, file.content_type or "application/octet-stream"
        )
    except sb.SupabaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"Upload failed: {exc.detail}")

    document = await sb.insert_knowledge_document(
        {
            "brokerage_id": brokerage["id"],
            "agent_id": agent_id,
            "filename": file.filename or "upload",
            "storage_path": path,
            "content_type": file.content_type,
            "file_size": len(content),
            "status": "processing",
        }
    )

    rules: list[dict[str, Any]] = []
    extraction_error: str | None = None
    try:
        proposed = await style_extract.extract_style_rules(
            content, file.content_type, file.filename
        )
    except style_extract.StyleNotConfigured:
        extraction_error = (
            "AI isn't configured yet — set ANTHROPIC_API_KEY on the backend to "
            "extract style rules. Your file was saved."
        )
    except style_extract.StyleExtractionError as exc:
        extraction_error = str(exc)
    else:
        if proposed:
            rules = await sb.insert_knowledge_rules(
                brokerage["id"],
                [
                    {
                        "category": r["category"],
                        "rule": r["rule"],
                        "source_document": file.filename or "upload",
                        "document_id": document["id"],
                        "agent_id": agent_id,
                        "confirmed": False,
                    }
                    for r in proposed
                ],
            )

    await sb.update_knowledge_document(
        brokerage["id"],
        document["id"],
        {"status": "failed" if extraction_error else "processed", "error": extraction_error},
    )
    document["status"] = "failed" if extraction_error else "processed"

    return {"document": document, "rules": rules, "extraction_error": extraction_error}


@router.delete("/{agent_id}/style-profile", status_code=status.HTTP_204_NO_CONTENT)
async def delete_style_profile(
    agent_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    """Admin action: wipe an agent's entire style profile (rules + documents)."""
    await _require_agent(brokerage["id"], agent_id)
    # Best-effort: remove stored files first, then the rows.
    docs = await sb.list_knowledge_documents_for_agent(brokerage["id"], agent_id)
    for doc in docs:
        if doc.get("storage_path"):
            try:
                await sb.delete_object(KNOWLEDGE_BUCKET, doc["storage_path"])
            except sb.SupabaseError:
                pass
    await sb.delete_agent_style_profile(brokerage["id"], agent_id)
