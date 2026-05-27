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
