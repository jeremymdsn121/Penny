import asyncio
import html
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage, get_current_user
from app.schemas.transaction import ExtractResponse, TransactionCreate, TransactionUpdate
from app.services import (
    ai_extract,
    compliance,
    compliance_checklist,
    csv_import,
    docusign_provider,
    doc_generate,
    doc_routing,
    email_client,
    rentcast,
    workflow,
)
from app.services.pdf_extract import pdf_page_count

router = APIRouter(prefix="/transactions", tags=["transactions"])

CONTRACTS_BUCKET = "contracts"
COMPLIANCE_BUCKET = "compliance-docs"
MAX_PDF_BYTES = 25 * 1024 * 1024  # 25 MB

_bucket_ready = False
_compliance_bucket_ready = False


async def _ensure_bucket() -> None:
    global _bucket_ready
    if not _bucket_ready:
        await sb.ensure_bucket(CONTRACTS_BUCKET, public=False)
        _bucket_ready = True


async def _ensure_compliance_bucket() -> None:
    global _compliance_bucket_ready
    if not _compliance_bucket_ready:
        await sb.ensure_bucket(COMPLIANCE_BUCKET, public=False)
        _compliance_bucket_ready = True


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


async def _resolve_creator_agent_id(
    brokerage_id: str, user: dict[str, Any]
) -> str | None:
    """Map the creating user to their agent record by email, for auto-assignment."""
    email = (user or {}).get("email")
    if not email:
        return None
    try:
        agent = await sb.get_agent_by_email(brokerage_id, email)
    except sb.SupabaseError:
        return None
    return agent.get("id") if agent else None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    body: TransactionCreate,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    data["brokerage_id"] = brokerage["id"]
    data.setdefault("stage", "under_contract")
    # Auto-assign the deal to the creating agent (unless one was specified).
    if not data.get("agent_id"):
        agent_id = await _resolve_creator_agent_id(brokerage["id"], user)
        if agent_id:
            data["agent_id"] = agent_id
    tx = await sb.insert_transaction(data)
    await _run_post_create_hooks(tx)
    return tx


async def _run_post_create_hooks(tx: dict[str, Any]) -> None:
    """Instantiate the compliance checklist + workflow tasks and fire document
    routing for a freshly created deal. Best-effort and idempotent so it's safe
    to share between single create and bulk CSV import."""
    stage = tx.get("stage") or "under_contract"
    try:
        await compliance_checklist.instantiate_for_transaction(tx)
        await workflow.generate_stage_tasks(tx, stage)
    except sb.SupabaseError:
        pass  # both can be (re)built later
    try:
        await doc_routing.run_stage_routing(tx, stage)
    except sb.SupabaseError:
        pass


@router.get("")
async def list_all(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    txs = await sb.list_transactions(brokerage["id"])
    ids = [t["id"] for t in txs]
    pct = await compliance_checklist.pct_for_transactions(ids)
    # Overdue pending-task counts per transaction (one query).
    today = date.today()
    overdue: dict[str, int] = {}
    for row in await sb.transaction_tasks_in(ids):
        due = row.get("due_date")
        try:
            if due and date.fromisoformat(str(due)[:10]) < today:
                overdue[row["transaction_id"]] = overdue.get(row["transaction_id"], 0) + 1
        except ValueError:
            pass
    for t in txs:
        t["checklist_pct"] = pct.get(t["id"], 0)
        t["overdue_tasks"] = overdue.get(t["id"], 0)
    return txs


# --------------------------------------------------------------------------- #
# CSV import — migration path for brokerages with existing deals (Dotloop /
# SkySlope / spreadsheet exports). Parse + preview, then confirm to commit.
# --------------------------------------------------------------------------- #

MAX_CSV_BYTES = 5 * 1024 * 1024  # 5 MB


@router.get("/import/template")
async def import_template(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> Response:
    """Download a CSV template with the expected headers and one example row."""
    return Response(
        content=csv_import.template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="penny-transactions-template.csv"'},
    )


@router.post("/import/preview")
async def import_preview(
    file: UploadFile = File(...),
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Parse a CSV and return a validated preview. Writes nothing."""
    name = (file.filename or "").lower()
    if not name.endswith(".csv") and (file.content_type or "") not in (
        "text/csv", "application/vnd.ms-excel", "application/csv", "text/plain",
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be a CSV")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="CSV exceeds the 5 MB limit",
        )
    existing = {
        csv_import._norm_address(t.get("address", ""))
        for t in await sb.list_transactions(brokerage["id"])
        if t.get("address")
    }
    return csv_import.build_preview(content, existing)


class ImportCommitIn(BaseModel):
    rows: list[dict[str, Any]]


@router.post("/import")
async def import_commit(
    body: ImportCommitIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Insert the confirmed rows. Each goes through the normal create hooks so an
    imported deal gets its checklist, workflow tasks, and routing."""
    if not body.rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No rows to import")
    if len(body.rows) > csv_import.MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many rows (limit {csv_import.MAX_ROWS}).",
        )

    creator_agent_id = await _resolve_creator_agent_id(brokerage["id"], user)
    allowed = set(TransactionCreate.model_fields)
    created = 0
    failed: list[dict[str, Any]] = []
    for i, raw in enumerate(body.rows):
        data = {k: v for k, v in raw.items() if k in allowed and v not in (None, "")}
        if not data.get("address"):
            failed.append({"index": i, "reason": "Missing address"})
            continue
        data["brokerage_id"] = brokerage["id"]
        data.setdefault("stage", "under_contract")
        if creator_agent_id and not data.get("agent_id"):
            data["agent_id"] = creator_agent_id
        try:
            tx = await sb.insert_transaction(data)
            await _run_post_create_hooks(tx)
            created += 1
        except sb.SupabaseError as exc:
            failed.append({"index": i, "reason": str(exc)})

    return {"created": created, "failed": failed}


@router.get("/{transaction_id}")
async def get_one(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    items = await sb.list_checklist_items(transaction_id)
    tx["checklist_pct"] = compliance_checklist.pct_from_items(items)["pct"]
    return tx


@router.patch("/{transaction_id}")
async def update_one(
    transaction_id: str,
    body: TransactionUpdate,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    prev = await sb.get_transaction(brokerage["id"], transaction_id)
    if prev is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    # Stamp closed_at on the transition into 'closed' (clear it if reopened).
    new_stage = data.get("stage")
    if new_stage and new_stage != prev.get("stage"):
        if new_stage == "closed":
            data["closed_at"] = datetime.now(timezone.utc).isoformat()
        elif prev.get("stage") == "closed":
            data["closed_at"] = None
    tx = await sb.update_transaction(brokerage["id"], transaction_id, data)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    # On a stage transition, generate the new stage's workflow tasks and fire
    # any document-routing rules for the new stage (both best-effort).
    if new_stage and new_stage != prev.get("stage"):
        try:
            await workflow.generate_stage_tasks(tx, new_stage)
        except sb.SupabaseError:
            pass
        try:
            await doc_routing.run_stage_routing(tx, new_stage)
        except sb.SupabaseError:
            pass
    return tx


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_one(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    """Delete a transaction. Child rows cascade via their FKs."""
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    await sb.delete_transaction(brokerage["id"], transaction_id)


# --------------------------------------------------------------------------- #
# Document drafting + sending (PRD §8.3) — drafts in the brokerage's voice
# using confirmed knowledge_rules; sending is a separate, confirmed step.
# --------------------------------------------------------------------------- #

class DraftDocumentIn(BaseModel):
    doc_type: str = "status_update"
    recipient: str | None = None
    instructions: str | None = None
    # When set, layer this agent's confirmed style rules on top of the brokerage's.
    agent_id: str | None = None


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
    agent_id = body.agent_id or tx.get("agent_id")
    rules = await sb.get_confirmed_knowledge_rules(brokerage["id"], agent_id)
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
        reply_to=email_client.reply_to_address(transaction_id),
        disclosure=email_client.disclosure_text(brokerage),
    )
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send — email isn't configured or the send failed.",
        )
    try:
        await sb.insert_transaction_email(
            {
                "transaction_id": transaction_id,
                "direction": "outbound",
                "sender_email": email_client.from_email(),
                "recipient_emails": recipients,
                "subject": body.subject,
                "body_text": body.body,
                "body_html": html_body,
                "read": True,
            }
        )
    except sb.SupabaseError:
        pass  # logging is best-effort
    return {"sent": True, "recipients": recipients}


# --------------------------------------------------------------------------- #
# Compliance review (PRD task ``compliance`` — locked, human-confirmed). The
# review only SURFACES findings; it never approves. Setting the compliance
# status is a separate, explicitly-confirmed human decision.
# --------------------------------------------------------------------------- #

class ComplianceDecisionIn(BaseModel):
    status: str
    confirmed: bool = False


@router.post("/{transaction_id}/compliance-review")
async def compliance_review(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Run a compliance review and surface findings. Read-only — never approves."""
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    pdf_bytes: bytes | None = None
    path = (tx.get("contract_pdf_url") or "").strip()
    if path:
        try:
            pdf_bytes = await sb.download_object(CONTRACTS_BUCKET, path)
        except sb.SupabaseError:
            pdf_bytes = None  # contract review degrades to structural + checklist
    return await compliance.review_transaction(tx, pdf_bytes)


@router.post("/{transaction_id}/compliance-decision")
async def compliance_decision(
    transaction_id: str,
    body: ComplianceDecisionIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Record the human's compliance decision. Requires explicit confirmation."""
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required to set compliance status.",
        )
    if body.status not in compliance.ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {sorted(compliance.ALLOWED_STATUSES)}.",
        )
    tx = await sb.update_transaction(
        brokerage["id"], transaction_id, {"compliance_status": body.status}
    )
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return {"compliance_status": tx.get("compliance_status")}


# --------------------------------------------------------------------------- #
# Comparable sales (PRD Phase 3) — Rentcast value estimate + comps for the
# property. Read-only; nothing is persisted.
# --------------------------------------------------------------------------- #

@router.post("/{transaction_id}/comps")
async def comparable_sales(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    address = rentcast.compose_address(tx)
    if not address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This transaction has no property address to look up.",
        )
    try:
        return await rentcast.get_value_estimate(address)
    except rentcast.RentcastNotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Comparable sales aren't configured yet — set RENTCAST_API_KEY on the backend.",
        )
    except rentcast.RentcastError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/{transaction_id}/property-record")
async def property_record(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Public-record property profile + tax/assessment history (read-only)."""
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    address = rentcast.compose_address(tx)
    if not address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This transaction has no property address to look up.",
        )
    try:
        return await rentcast.get_property_record(address)
    except rentcast.RentcastNotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Property records aren't configured yet — set RENTCAST_API_KEY on the backend.",
        )
    except rentcast.RentcastError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


# --------------------------------------------------------------------------- #
# Earnest money deposit receipt (PRD V2 Section 5) — receipt tracking only.
# Scalar EMD fields are set via the generic PATCH; this endpoint handles the
# optional receipt-document upload and marks the deposit received.
# --------------------------------------------------------------------------- #

@router.post("/{transaction_id}/emd-receipt")
async def upload_emd_receipt(
    transaction_id: str,
    file: UploadFile = File(...),
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the 25 MB limit",
        )
    await _ensure_compliance_bucket()
    ext = (file.filename or "file").rsplit(".", 1)[-1][:8] if "." in (file.filename or "") else "bin"
    path = f"{brokerage['id']}/{transaction_id}/emd-{uuid.uuid4()}.{ext}"
    try:
        await sb.upload_object(
            COMPLIANCE_BUCKET, path, content, file.content_type or "application/octet-stream"
        )
    except sb.SupabaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"Upload failed: {exc.detail}")
    updated = await sb.update_transaction(
        brokerage["id"], transaction_id, {"emd_receipt_document_url": path, "emd_received": True}
    )
    return {"emd_receipt_document_url": path, "emd_received": True, "transaction": updated}


# --------------------------------------------------------------------------- #
# DocuSign e-signature (PRD V2 Section 8) — behind a seam. Confirm-gated, but
# reports "not connected" until DocuSign credentials/partner review exist.
# --------------------------------------------------------------------------- #

class DocuSignSigner(BaseModel):
    name: str
    email: str
    role: str | None = None


class DocuSignSendIn(BaseModel):
    document_url: str | None = None  # storage path; defaults to the contract PDF
    signers: list[DocuSignSigner] = []
    email_subject: str | None = None
    message: str | None = None
    confirmed: bool = False


@router.get("/{transaction_id}/docusign/status")
async def docusign_status(
    transaction_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return docusign_provider.status(brokerage)


@router.post("/{transaction_id}/docusign/send")
async def docusign_send(
    transaction_id: str,
    body: DocuSignSendIn,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required before sending for signature.",
        )
    tx = await sb.get_transaction(brokerage["id"], transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    document_url = body.document_url or tx.get("contract_pdf_url")
    if not document_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No document to send — upload or extract the contract first.",
        )
    return await docusign_provider.send_envelope(
        brokerage,
        document_url=document_url,
        signers=[s.model_dump() for s in body.signers],
        email_subject=body.email_subject or f"Please sign: {tx.get('address') or 'document'}",
        message=body.message or "",
    )
