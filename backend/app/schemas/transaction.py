from typing import Any

from pydantic import BaseModel


class TransactionCreate(BaseModel):
    """Fields used to create a transaction — typically the confirmed output of
    contract extraction. All optional; the user confirms/fills before saving."""

    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    buyer_name: str | None = None
    buyer_email: str | None = None
    buyer_phone: str | None = None
    seller_name: str | None = None
    seller_email: str | None = None
    seller_phone: str | None = None
    list_price: float | None = None
    sale_price: float | None = None
    financing: str | None = None
    contract_date: str | None = None  # YYYY-MM-DD
    closing_date: str | None = None  # YYYY-MM-DD
    stage: str | None = "under_contract"
    listing_agent_name: str | None = None
    listing_agent_email: str | None = None
    selling_agent_name: str | None = None
    selling_agent_email: str | None = None
    lender_name: str | None = None
    lender_email: str | None = None
    title_company: str | None = None
    title_email: str | None = None
    tc_name: str | None = None
    tc_email: str | None = None
    mls_number: str | None = None
    contract_pdf_url: str | None = None
    agent_id: str | None = None


class TransactionUpdate(TransactionCreate):
    pass


class ExtractResponse(BaseModel):
    contract_pdf_url: str  # storage object path
    signed_url: str | None = None  # short-lived URL for preview
    page_count: int
    fields: dict[str, Any]
    not_found: list[str]
