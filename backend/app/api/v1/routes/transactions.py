import asyncio
import html
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.schemas.transaction import ExtractResponse, TransactionCreate, TransactionUpdate
from app.services import ai_extract, doc_generate, email_client
from app.services.pdf_extract import pdf_page_count

router = APIRouter(prefix="/transactions", tags=["transactions"])

CONTRACTS_BUCKET = "contracts"
MAX_PDF_BYTES = 25 * 1024 * 1024  # 25 MB

_bucket_ready = False


async def _ensure_bucket() -> None:
    global _bucket_ready
    if not _bucket_ready:
        await sb.ensure_bucket(CONTRACTS_BUCKET, public=False)
        _bucket_ready = True


@router.post("/extract", response_model=ExtractResponse)
async def extract(
    file: UploadFile = File(...),
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> ExtractResponse:
    # Validate type + size before doing any work (PRD §10).
    if (file.content_type or "") not in ("application/pdf", "application/x-pdf") and not (
        file.filename or ""
    ).lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be a PDF")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="PDF exceeds the 25 MB limit",
        )

    # Confirm it's a readable PDF and get the page count.
    try:
        page_count = pdf_page_count(content)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not read PDF")

    # Store the original in the private contracts bucket.
    await _ensure_bucket()
    path = f"{brokerage['id']}/{uuid.uuid4()}.pdf"
    try:
        await sb.upload_object(CONTRACTS_BUCKET, path, content, "application/pdf")
    except sb.SupabaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"Upload failed: {exc.detail}")

    # AI field extraction — send raw PDF bytes directly (handles all PDF types).
    rules = await sb.get_confirmed_knowledge_rules(brokerage["id"])
    try:
        fields = await ai_extract.extract_contract_fields(content, rules)
    except ai_extract.AINotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI extraction isn't configured yet — set ANTHROPIC_API_KEY on the backend.",
        )
    except ai_extract.AIExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    not_found = [k for k, v in fields.items() if v in (None, "")]
    signed_url = None
    try:
        signed_url = await sb.create_signed_url(CONTRACTS_BUCKET, path)
    except sb.SupabaseError:
        pass  # preview URL is best-effort

    return ExtractResponse(
        contract_pdf_url=path,
        signed_url=signed_url,
        page_count=page_count,
        fields=fields,
        not_found=not_found,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    body: TransactionCreate,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    data["brokerage_id"] = brokerage["id"]
    data.setdefault("stage", "under_contract")
    return await sb.insert_transaction(data)


@router.get("")
async def list_all(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    return await sb.list_transactions(brokerage["id"])


@router.get("/{transaction_id}")
async def get_one(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return tx


@router.patch("/{transaction_id}")
async def update_one(
    transaction_id: str,
    body: TransactionUpdate,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    tx = await sb.update_transaction(brokerage["id"], transaction_id, data)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return tx


# --------------------------------------------------------------------------- #
# Document drafting + sending (PRD §8.3) — drafts in the brokerage's voice
# using confirmed knowledge_rules; sending is a separate, confirmed step.
# --------------------------------------------------------------------------- #

class DraftDocumentIn(BaseModel):
    doc_type: str = "status_update"
    recipient: str | None = None
    instructions: str | None = None


class SendDocumentIn(BaseModel):
    to_emails: list[str]
    subject: str
    body: str
    confirmed: bool = False


@router.post("/{transaction_id}/draft-document")
async def draft_document(
    transaction_id: str,
    body: DraftDocumentIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Draft a document for this transaction. Read-only — sends nothing."""
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    rules = await sb.get_confirmed_knowledge_rules(brokerage["id"])
    try:
        draft = await doc_generate.generate_document(
            transaction=tx,
            doc_type=body.doc_type,
            brokerage_name=brokerage.get("name", "your brokerage"),
            style_rules=rules,
            recipient=body.recipient,
            instructions=body.instructions,
        )
    except doc_generate.DocNotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI isn't configured yet — set ANTHROPIC_API_KEY on the backend.",
        )
    except doc_generate.DocGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return {"doc_type": body.doc_type, **draft}


@router.post("/{transaction_id}/send-document")
async def send_document(
    transaction_id: str,
    body: SendDocumentIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Send a (reviewed) document by email. Requires explicit confirmation."""
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required before sending.",
        )
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    recipients = [e.strip() for e in body.to_emails if e and e.strip()]
    if not recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No recipient email provided."
        )
    html_body = (
        '<html><body><div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        f'white-space:pre-wrap;color:#111827;font-size:15px;line-height:1.6;">{html.escape(body.body)}</div></body></html>'
    )
    sent = await asyncio.to_thread(
        email_client.send_email,
        to_emails=recipients,
        subject=body.subject,
        html=html_body,
        plain=body.body,
    )
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send — email isn't configured or the send failed.",
        )
    return {"sent": True, "recipients": recipients}
