"""Calendar provider seam (PRD task ``scheduling``).

This is the single place the live Google/Microsoft calendar integration will
plug in. For now it reports "not connected" and no-ops, so the rest of
scheduling (slot proposal, booking, the UI) works end-to-end against working
hours + locally-stored appointments today.

Deferred until the OAuth apps are registered and testable:
  * OAuth connect/callback + token storage in
    ``brokerages.google_calendar_token`` / ``microsoft_token`` (jsonb columns
    already exist) + refresh.
  * ``get_busy`` → real free/busy (Google freeBusy / Graph calendarView).
  * ``create_event`` → real event creation with attendee invites.
When that lands, only the bodies below change; callers stay the same.
"""

from datetime import datetime
from typing import Any


def status(brokerage: dict[str, Any]) -> dict[str, Any]:
    """Report whether a calendar is connected for this brokerage."""
    provider = brokerage.get("calendar_provider")
    token = None
    if provider == "google":
        token = brokerage.get("google_calendar_token")
    elif provider == "outlook":
        token = brokerage.get("microsoft_token")
    return {
        "provider": provider,
        "connected": bool(token),
        # Live sync isn't wired yet even if a token somehow exists.
        "sync_enabled": False,
    }


def is_connected(brokerage: dict[str, Any]) -> bool:
    return status(brokerage)["connected"] and status(brokerage)["sync_enabled"]


async def get_busy(
    brokerage: dict[str, Any], start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """Busy intervals from the connected calendar. Empty until OAuth lands."""
    return []


async def create_event(
    brokerage: dict[str, Any],
    *,
    summary: str,
    start: datetime,
    end: datetime,
    attendees: list[str],
) -> str | None:
    """Create a calendar event and return its id. None until OAuth lands."""
    return None
