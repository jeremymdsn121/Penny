"""MLS listing prep (PRD task ``mls-entry``).

Upload a listing packet (PDF) → Sloane extracts MLS-ready fields → the agent
reviews/edits and saves a `listings` record → optionally pushes to the MLS.
Pushing goes through ``mls_provider`` (a seam that reports "not connected"
today; per-market write integration is deferred). Listings are brokerage-scoped
directly (the `listings` table has a brokerage_id column + RLS).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.services import mls_extract, mls_provider
from app.services.pdf_extract import pdf_page_count

router = APIRouter(prefix="/listings", tags=["listings"])

PACKETS_BUCKET = "listing-packets"
MAX_PDF_BYTES = 25 * 1024 * 1024

_bucket_ready = False

# Columns a client may set on create/update (mirrors the listings table).
_WRITABLE: set[str] = {
    "status", "address", "city", "state", "zip", "property_type", "list_price",
    "bedrooms", "bathrooms", "square_footage", "lot_size_sqft", "year_built",
    "stories", "garage_spaces", "hoa_fee", "hoa_frequency", "annual_taxes",
    "parcel_number", "mls_number", "public_remarks", "features", "school_district",
    "listing_agent_name", "listing_agent_email", "seller_name", "listing_packet_url",
    "transaction_id", "agent_id",
}


async def _ensure_bucket() -> None:
    global _bucket_ready
    if not _bucket_ready:
        await sb.ensure_bucket(PACKETS_BUCKET, public=False)
        _bucket_ready = True


class ListingPush(BaseModel):
    confirmed: bool = False


def _writable(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k in _WRITABLE}


@router.post("/extract")
async def extract(
    file: UploadFile = File(...),
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Extract MLS fields from a listing packet PDF. Read-only — saves no listing."""
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
    try:
        page_count = pdf_page_count(content)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not read PDF")

    await _ensure_bucket()
    path = f"{brokerage['id']}/{uuid.uuid4()}.pdf"
    try:
        await sb.upload_object(PACKETS_BUCKET, path, content, "application/pdf")
    except sb.SupabaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"Upload failed: {exc.detail}")

    try:
        fields = await mls_extract.extract_listing_fields(content)
    except mls_extract.MLSNotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI extraction isn't configured yet — set ANTHROPIC_API_KEY on the backend.",
        )
    except mls_extract.MLSExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    not_found = [k for k, v in fields.items() if v in (None, "", [])]
    signed_url = None
    try:
        signed_url = await sb.create_signed_url(PACKETS_BUCKET, path)
    except sb.SupabaseError:
        pass
    return {
        "listing_packet_url": path,
        "signed_url": signed_url,
        "page_count": page_count,
        "fields": fields,
        "not_found": not_found,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    body: dict[str, Any],
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    data = _writable(body)
    data["brokerage_id"] = brokerage["id"]
    data.setdefault("status", "draft")
    return await sb.insert_listing(data)


@router.get("")
async def list_all(
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> list[dict[str, Any]]:
    return await sb.list_listings(brokerage["id"])


@router.get("/{listing_id}")
async def get_one(
    listing_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    listing = await sb.get_listing(brokerage["id"], listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")
    return listing


@router.patch("/{listing_id}")
async def update_one(
    listing_id: str,
    body: dict[str, Any],
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    listing = await sb.update_listing(brokerage["id"], listing_id, _writable(body))
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")
    return listing


@router.delete("/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_one(
    listing_id: str,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> None:
    listing = await sb.get_listing(brokerage["id"], listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")
    await sb.delete_listing(brokerage["id"], listing_id)


@router.post("/{listing_id}/push")
async def push(
    listing_id: str,
    body: ListingPush,
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    """Push a prepared listing to the MLS (confirm-gated). No-op until a
    per-market write integration is wired — returns the reason so the UI can
    explain it."""
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required before pushing to the MLS.",
        )
    listing = await sb.get_listing(brokerage["id"], listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")
    result = await mls_provider.push_listing(brokerage, listing)
    if result["pushed"] and result.get("mls_number"):
        await sb.update_listing(
            brokerage["id"], listing_id,
            {"mls_number": result["mls_number"], "status": "active"},
        )
    return result
