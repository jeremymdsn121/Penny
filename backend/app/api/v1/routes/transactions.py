import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.schemas.transaction import ExtractResponse, TransactionCreate, TransactionUpdate
from app.services import ai_extract
from app.services.pdf_extract import extract_pdf_text, pdf_page_count

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

    # Confirm it's a readable PDF and get text.
    try:
        page_count = pdf_page_count(content)
        text = extract_pdf_text(content)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not read PDF")
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No extractable text found (scanned PDFs aren't supported yet)",
        )

    # Store the original in the private contracts bucket.
    await _ensure_bucket()
    path = f"{brokerage['id']}/{uuid.uuid4()}.pdf"
    try:
        await sb.upload_object(CONTRACTS_BUCKET, path, content, "application/pdf")
    except sb.SupabaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"Upload failed: {exc.detail}")

    # AI field extraction.
    rules = await sb.get_confirmed_knowledge_rules(brokerage["id"])
    try:
        fields = await ai_extract.extract_contract_fields(text, rules)
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
