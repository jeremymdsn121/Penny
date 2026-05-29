"""Rentcast — comparable sales + value estimates (PRD Phase 3).

Thin async client over the Rentcast AVM endpoint. Given a property address, the
``/avm/value`` endpoint returns an estimated value, a value range, and a list of
comparable properties (recently sold/listed similar homes with price, beds,
baths, size, distance, and a correlation score) — i.e. the comps.

Like the other integrations, this no-ops loudly: it raises ``RentcastNotConfigured``
when ``RENTCAST_API_KEY`` is unset so callers can return a clean 503, and
``RentcastError`` on any API/parse problem.
"""

from typing import Any

import httpx

from app.config import settings

BASE_URL = "https://api.rentcast.io/v1"
_TIMEOUT = httpx.Timeout(30.0)


class RentcastNotConfigured(Exception):
    """Raised when no RENTCAST_API_KEY is configured."""


class RentcastError(Exception):
    """Raised when the Rentcast API errors or returns no usable data."""


def compose_address(tx: dict[str, Any]) -> str:
    """Build a single-line address string from a transaction row."""
    street = (tx.get("address") or "").strip()
    city = (tx.get("city") or "").strip()
    state = (tx.get("state") or "").strip()
    zip_code = (tx.get("zip") or "").strip()
    locality = " ".join(p for p in [state, zip_code] if p)
    parts = [p for p in [street, city, locality] if p]
    return ", ".join(parts)


def _num(value: Any) -> float | int | None:
    if isinstance(value, (int, float)):
        return value
    return None


def _parse_comparable(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "address": c.get("formattedAddress") or c.get("addressLine1"),
        "price": _num(c.get("price")),
        "bedrooms": _num(c.get("bedrooms")),
        "bathrooms": _num(c.get("bathrooms")),
        "square_footage": _num(c.get("squareFootage")),
        "year_built": _num(c.get("yearBuilt")),
        "property_type": c.get("propertyType"),
        "listing_type": c.get("listingType"),
        "days_on_market": _num(c.get("daysOnMarket")),
        "distance": _num(c.get("distance")),
        "correlation": _num(c.get("correlation")),
    }


async def get_value_estimate(address: str, comp_count: int = 6) -> dict[str, Any]:
    """Fetch a value estimate + comparables for an address.

    Returns ``{subject_address, estimate, range_low, range_high, comparables}``.
    Raises RentcastNotConfigured / RentcastError.
    """
    if not settings.RENTCAST_API_KEY:
        raise RentcastNotConfigured("RENTCAST_API_KEY is not set")
    address = (address or "").strip()
    if not address:
        raise RentcastError("No address to look up.")

    params = {"address": address, "compCount": max(1, min(comp_count, 25))}
    headers = {"X-Api-Key": settings.RENTCAST_API_KEY, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{BASE_URL}/avm/value", params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise RentcastError(f"Rentcast request failed: {exc}") from exc

    if resp.status_code == 401:
        raise RentcastError("Rentcast rejected the API key.")
    if resp.status_code == 404:
        raise RentcastError("Rentcast couldn't find comparable sales for that address.")
    if resp.status_code >= 400:
        raise RentcastError(f"Rentcast error (HTTP {resp.status_code}).")

    try:
        data = resp.json()
    except ValueError as exc:
        raise RentcastError("Rentcast returned an unreadable response.") from exc

    comps = data.get("comparables")
    comparables = [_parse_comparable(c) for c in comps] if isinstance(comps, list) else []
    return {
        "subject_address": address,
        "estimate": _num(data.get("price")),
        "range_low": _num(data.get("priceRangeLow")),
        "range_high": _num(data.get("priceRangeHigh")),
        "comparables": comparables,
    }


def _year_series(raw: Any, *fields: str) -> list[dict[str, Any]]:
    """Flatten a {year: {...}} map into a list sorted newest-first.

    Rentcast keys ``taxAssessments``/``propertyTaxes`` by year string; each value
    is an object. We keep ``year`` plus the requested numeric ``fields``.
    """
    if not isinstance(raw, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        year = _num(entry.get("year")) or (int(key) if str(key).isdigit() else None)
        row: dict[str, Any] = {"year": year}
        for f in fields:
            row[f] = _num(entry.get(f))
        rows.append(row)
    return sorted(rows, key=lambda r: r["year"] or 0, reverse=True)


async def get_property_record(address: str) -> dict[str, Any]:
    """Fetch the public-record property profile + tax history for an address.

    Uses Rentcast ``/properties`` (county assessor data). Returns subject details
    plus ``tax_assessments`` (assessed value / land / improvements by year) and
    ``property_taxes`` (annual tax total by year). Assessed values are for tax
    purposes and are **not** market value — the caller surfaces that caveat.
    Raises RentcastNotConfigured / RentcastError, mirroring get_value_estimate.
    """
    if not settings.RENTCAST_API_KEY:
        raise RentcastNotConfigured("RENTCAST_API_KEY is not set")
    address = (address or "").strip()
    if not address:
        raise RentcastError("No address to look up.")

    params = {"address": address}
    headers = {"X-Api-Key": settings.RENTCAST_API_KEY, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{BASE_URL}/properties", params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise RentcastError(f"Rentcast request failed: {exc}") from exc

    if resp.status_code == 401:
        raise RentcastError("Rentcast rejected the API key.")
    if resp.status_code == 404:
        raise RentcastError("Rentcast has no property record for that address.")
    if resp.status_code >= 400:
        raise RentcastError(f"Rentcast error (HTTP {resp.status_code}).")

    try:
        data = resp.json()
    except ValueError as exc:
        raise RentcastError("Rentcast returned an unreadable response.") from exc

    # /properties returns a list of matching records; take the first.
    rec = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
    if not rec:
        raise RentcastError("Rentcast has no property record for that address.")

    return {
        "subject_address": rec.get("formattedAddress") or address,
        "year_built": _num(rec.get("yearBuilt")),
        "lot_size": _num(rec.get("lotSize")),
        "square_footage": _num(rec.get("squareFootage")),
        "bedrooms": _num(rec.get("bedrooms")),
        "bathrooms": _num(rec.get("bathrooms")),
        "property_type": rec.get("propertyType"),
        "owner_occupied": rec.get("ownerOccupied"),
        "last_sale_price": _num(rec.get("lastSalePrice")),
        "last_sale_date": rec.get("lastSaleDate"),
        "tax_assessments": _year_series(
            rec.get("taxAssessments"), "value", "land", "improvements"
        ),
        "property_taxes": _year_series(rec.get("propertyTaxes"), "total"),
    }
