"""CSV transaction import — the migration path for brokerages with an existing
book of business (e.g. deals already living in Dotloop / SkySlope / a spreadsheet).

Rather than per-vendor parsers (which would mean coding blind against export
formats we can't see), this accepts a documented Sloane column set AND aliases the
common header variants those tools emit, so a lightly-edited export maps without
manual renaming. Everything here is pure (no DB/IO) so it's unit-testable; the
route layer supplies the existing-address set for duplicate detection.

Flow: the route calls ``build_preview`` (parse + normalize + validate + flag
dupes, nothing written), the user reviews, then the route inserts the confirmed
rows through the normal create path so each imported deal gets its checklist,
workflow tasks, and routing like any other.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any

# Canonical transaction field -> accepted header variants (normalized form:
# lowercased, non-alphanumerics collapsed to single spaces, trimmed). The
# canonical Sloane header for each field is the first listed.
FIELD_ALIASES: dict[str, list[str]] = {
    "address": ["address", "property address", "property", "street address", "street", "subject property", "property street"],
    "city": ["city", "property city"],
    "state": ["state", "property state", "st"],
    "zip": ["zip", "zip code", "zipcode", "postal code", "property zip"],
    "buyer_name": ["buyer name", "buyer", "buyers", "purchaser", "purchaser name", "buyer s"],
    "buyer_email": ["buyer email", "buyer e mail"],
    "buyer_phone": ["buyer phone", "buyer phone number", "buyer cell"],
    "seller_name": ["seller name", "seller", "sellers", "vendor", "seller s"],
    "seller_email": ["seller email"],
    "seller_phone": ["seller phone", "seller phone number", "seller cell"],
    "list_price": ["list price", "listing price", "asking price"],
    "sale_price": ["sale price", "sales price", "purchase price", "price", "contract price", "sold price"],
    "financing": ["financing", "loan type", "financing type"],
    "contract_date": ["contract date", "under contract date", "executed date", "acceptance date", "offer date", "binding date"],
    "closing_date": ["closing date", "close date", "settlement date", "coe", "coe date", "estimated closing date", "est closing date"],
    "stage": ["stage", "status", "transaction status", "deal stage"],
    "listing_agent_name": ["listing agent", "listing agent name", "list agent", "listing side agent"],
    "listing_agent_email": ["listing agent email", "list agent email"],
    "selling_agent_name": ["selling agent", "selling agent name", "buyer agent", "buyers agent", "buyside agent", "buyer s agent"],
    "selling_agent_email": ["selling agent email", "buyer agent email"],
    "lender_name": ["lender", "lender name", "loan officer", "mortgage company"],
    "lender_email": ["lender email", "loan officer email"],
    "title_company": ["title company", "title", "escrow company", "closing company", "settlement company"],
    "title_email": ["title email", "escrow email", "title company email"],
    "tc_name": ["tc", "tc name", "transaction coordinator", "coordinator"],
    "tc_email": ["tc email", "transaction coordinator email"],
    "mls_number": ["mls", "mls number", "mls id", "listing id"],
    "transaction_type": ["transaction type", "type", "deal type", "side", "representation"],
    "emd_amount": ["emd", "emd amount", "earnest money", "earnest money deposit", "earnest money amount"],
    "emd_due_date": ["emd due date", "earnest money due", "earnest money due date"],
}

# Reverse lookup: normalized header variant -> canonical field.
_ALIAS_TO_FIELD: dict[str, str] = {
    variant: field for field, variants in FIELD_ALIASES.items() for variant in variants
}

# Columns offered in the downloadable template (canonical headers, sensible order).
TEMPLATE_COLUMNS: list[str] = [
    "address", "city", "state", "zip",
    "buyer_name", "buyer_email", "buyer_phone",
    "seller_name", "seller_email", "seller_phone",
    "list_price", "sale_price", "financing",
    "contract_date", "closing_date", "stage", "transaction_type",
    "listing_agent_name", "listing_agent_email",
    "selling_agent_name", "selling_agent_email",
    "lender_name", "lender_email",
    "title_company", "title_email",
    "tc_name", "tc_email",
    "mls_number", "emd_amount", "emd_due_date",
]

# Fields parsed as YYYY-MM-DD, prices, etc.
_DATE_FIELDS = {"contract_date", "closing_date", "emd_due_date"}
_PRICE_FIELDS = {"list_price", "sale_price", "emd_amount"}

VALID_STAGES = {"under_contract", "pending", "closed", "cancelled"}
_STAGE_ALIASES: dict[str, str] = {
    "under contract": "under_contract", "undercontract": "under_contract",
    "active": "under_contract", "new": "under_contract", "open": "under_contract",
    "pending": "pending", "pending sale": "pending", "contingent": "pending",
    "closed": "closed", "sold": "closed", "settled": "closed", "completed": "closed",
    "cancelled": "cancelled", "canceled": "cancelled", "terminated": "cancelled",
    "withdrawn": "cancelled", "expired": "cancelled", "dead": "cancelled",
}

VALID_TYPES = {"buy_side", "list_side", "dual_agency", "lease"}
_TYPE_ALIASES: dict[str, str] = {
    "buy side": "buy_side", "buyer": "buy_side", "buy": "buy_side",
    "buyer representation": "buy_side", "buyside": "buy_side",
    "list side": "list_side", "listing": "list_side", "seller": "list_side",
    "list": "list_side", "seller representation": "list_side", "listside": "list_side",
    "dual": "dual_agency", "dual agency": "dual_agency", "both": "dual_agency",
    "lease": "lease", "rental": "lease", "tenant": "lease", "landlord": "lease",
}

MAX_ROWS = 500


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (h or "").strip().lower()).strip()


def _norm_address(a: str) -> str:
    """Loose address key for duplicate detection."""
    return re.sub(r"[^a-z0-9]+", " ", (a or "").strip().lower()).strip()


def _parse_price(raw: str) -> float | None:
    cleaned = re.sub(r"[^0-9.]", "", raw or "")
    if not cleaned or cleaned == ".":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y/%m/%d")


def _parse_date(raw: str) -> str | None:
    """Return an ISO YYYY-MM-DD string, or None if unparseable."""
    from datetime import datetime

    s = (raw or "").strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def map_headers(headers: list[str]) -> tuple[dict[int, str], list[str]]:
    """Map column indices to canonical fields. Returns (index->field, unmapped headers)."""
    mapping: dict[int, str] = {}
    unmapped: list[str] = []
    for i, h in enumerate(headers):
        field = _ALIAS_TO_FIELD.get(_norm_header(h))
        if field and field not in mapping.values():
            mapping[i] = field
        elif (h or "").strip():
            unmapped.append(h.strip())
    return mapping, unmapped


def normalize_row(raw: dict[str, str]) -> tuple[dict[str, Any], list[str], list[str]]:
    """Clean one mapped row. Returns (data, errors, warnings).

    Errors block the row from importing; warnings note a dropped/defaulted value
    but let the row through.
    """
    data: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []

    for field, value in raw.items():
        val = (value or "").strip()
        if not val:
            continue
        if field in _PRICE_FIELDS:
            n = _parse_price(val)
            if n is None:
                warnings.append(f"Couldn't read {field} \"{val}\" — left blank")
            else:
                data[field] = n
        elif field in _DATE_FIELDS:
            iso = _parse_date(val)
            if iso is None:
                warnings.append(f"Couldn't read {field} \"{val}\" — left blank")
            else:
                data[field] = iso
        elif field == "stage":
            stage = _STAGE_ALIASES.get(_norm_header(val))
            if stage:
                data["stage"] = stage
            else:
                warnings.append(f"Unknown stage \"{val}\" — defaulted to Under Contract")
                data["stage"] = "under_contract"
        elif field == "transaction_type":
            t = _TYPE_ALIASES.get(_norm_header(val))
            if t:
                data["transaction_type"] = t
            else:
                warnings.append(f"Unknown transaction type \"{val}\" — left blank")
        else:
            data[field] = val

    if not data.get("address"):
        errors.append("Missing property address")
    data.setdefault("stage", "under_contract")

    return data, errors, warnings


def build_preview(content: bytes, existing_addresses: set[str]) -> dict[str, Any]:
    """Parse + validate a CSV upload without writing anything.

    ``existing_addresses`` is the set of normalized addresses already on file for
    the brokerage, used to flag likely duplicates.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1", errors="replace")

    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration:
        return {
            "rows": [], "recognized_columns": [], "unmapped_columns": [],
            "summary": {"total": 0, "ready": 0, "errors": 0, "duplicates": 0},
            "error": "The file is empty.",
        }

    mapping, unmapped = map_headers(headers)
    if not mapping:
        return {
            "rows": [], "recognized_columns": [], "unmapped_columns": unmapped,
            "summary": {"total": 0, "ready": 0, "errors": 0, "duplicates": 0},
            "error": "No recognizable columns. Download the template to see expected headers.",
        }

    recognized = sorted(set(mapping.values()))
    seen_in_file: set[str] = set()
    rows: list[dict[str, Any]] = []
    ready = err_count = dup_count = 0

    for line_no, raw_cols in enumerate(reader, start=2):
        if not any((c or "").strip() for c in raw_cols):
            continue  # skip blank lines
        raw: dict[str, str] = {}
        for idx, field in mapping.items():
            raw[field] = raw_cols[idx] if idx < len(raw_cols) else ""

        data, errors, warnings = normalize_row(raw)

        addr_key = _norm_address(data.get("address", ""))
        duplicate = False
        if addr_key:
            if addr_key in existing_addresses:
                duplicate = True
                warnings.append("A transaction with this address is already on file")
            elif addr_key in seen_in_file:
                duplicate = True
                warnings.append("This address also appears earlier in the file")
            seen_in_file.add(addr_key)

        if len(rows) >= MAX_ROWS:
            return {
                "rows": rows, "recognized_columns": recognized, "unmapped_columns": unmapped,
                "summary": {"total": len(rows), "ready": ready, "errors": err_count, "duplicates": dup_count},
                "error": f"File exceeds the {MAX_ROWS}-row import limit. Split it and import in batches.",
            }

        if errors:
            err_count += 1
        else:
            ready += 1
        if duplicate:
            dup_count += 1

        rows.append({
            "row_number": line_no,
            "data": data,
            "errors": errors,
            "warnings": warnings,
            "duplicate": duplicate,
            "importable": not errors,
        })

    return {
        "rows": rows,
        "recognized_columns": recognized,
        "unmapped_columns": unmapped,
        "summary": {
            "total": len(rows), "ready": ready, "errors": err_count, "duplicates": dup_count,
        },
    }


def template_csv() -> str:
    """A header-only CSV template with one illustrative example row."""
    example = {
        "address": "123 Main St", "city": "Austin", "state": "TX", "zip": "78701",
        "buyer_name": "Jane Buyer", "buyer_email": "jane@example.com", "buyer_phone": "512-555-0100",
        "seller_name": "John Seller", "seller_email": "john@example.com", "seller_phone": "512-555-0101",
        "list_price": "450000", "sale_price": "445000", "financing": "Conventional",
        "contract_date": "2026-05-01", "closing_date": "2026-06-15",
        "stage": "under_contract", "transaction_type": "buy_side",
        "listing_agent_name": "Pat Listing", "listing_agent_email": "pat@brokerage.com",
        "selling_agent_name": "Sam Selling", "selling_agent_email": "sam@brokerage.com",
        "lender_name": "Acme Mortgage", "lender_email": "loans@acme.com",
        "title_company": "Lone Star Title", "title_email": "escrow@lonestar.com",
        "tc_name": "", "tc_email": "",
        "mls_number": "TX1234567", "emd_amount": "5000", "emd_due_date": "2026-05-05",
    }
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=TEMPLATE_COLUMNS)
    writer.writeheader()
    writer.writerow({k: example.get(k, "") for k in TEMPLATE_COLUMNS})
    return out.getvalue()
