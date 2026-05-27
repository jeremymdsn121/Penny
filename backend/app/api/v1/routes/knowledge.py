"""Knowledge base — brand & style document ingestion.

A brokerage admin uploads a style reference (letterhead, sample letter, email
template). We store the original in a private bucket, ask Penny to propose style
rules from it, and persist those rules as *unconfirmed* knowledge_rules. The
admin reviews and confirms them; confirmed rules are injected into Penny's AI
prompts (see supabase_client.get_confirmed_knowledge_rules).

All endpoints require a valid JWT and are scoped to the caller's brokerage.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.services import style_extract

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

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


class RuleUpdate(BaseModel):
    confirmed: bool | None = None
    category: str | None = None
    rule: str | None = None


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #

@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Upload a style reference, store it, and propose style rules from it."""
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

    # Store the original in the private knowledge bucket.
    await _ensure_bucket()
    path = f"{brokerage['id']}/{uuid.uuid4()}.{_ext(file.filename, kind)}"
    try:
        await sb.upload_object(
            KNOWLEDGE_BUCKET, path, content, file.content_type or "application/octet-stream"
        )
    except sb.SupabaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"Upload failed: {exc.detail}")

    document = await sb.insert_knowledge_document(
        {
            "brokerage_id": brokerage["id"],
            "filename": file.filename or "upload",
            "storage_path": path,
            "content_type": file.content_type,
            "file_size": len(content),
            "status": "processing",
        }
    )

    # Extract proposed style rules. Failures are non-fatal: the file is kept and
    # the document is marked 'failed' so the admin can retry or delete it.
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


@router.get("/documents")
async def list_documents(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    return await sb.list_knowledge_documents(brokerage["id"])


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    doc = await sb.get_knowledge_document(brokerage["id"], document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    # Best-effort storage cleanup; the DB row is the source of truth.
    if doc.get("storage_path"):
        try:
            await sb.delete_object(KNOWLEDGE_BUCKET, doc["storage_path"])
        except sb.SupabaseError:
            pass
    await sb.delete_knowledge_document(brokerage["id"], document_id)


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #

@router.get("/rules")
async def list_rules(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    return await sb.list_knowledge_rules(brokerage["id"])


@router.patch("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    body: RuleUpdate,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Confirm and/or edit a proposed rule. Confirming is the human approval step."""
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update")
    rule = await sb.update_knowledge_rule(brokerage["id"], rule_id, data)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    await sb.delete_knowledge_rule(brokerage["id"], rule_id)
