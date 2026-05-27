"""MLS push seam (PRD task ``mls-entry``).

The single place a real MLS *write* integration will plug in. There is no
universal "push to the MLS": each MLS is independent, the RESO Web API is mostly
read-only, and write/listing-input access is per-MLS (or per-platform, e.g.
Spark API for Flexmls markets) and gated behind credentials, a data-access
agreement, and broker authorization.

So for now this reports "not connected" and pushes nothing — listings are
prepared as MLS-ready data the agent enters manually. When a per-market write
integration is secured and testable, only the bodies below change; callers stay
the same. (Deliberately not built blind — see the deferred-integration note in
project memory / CLAUDE.md.)
"""

from typing import Any


def status(brokerage: dict[str, Any]) -> dict[str, Any]:
    """Whether an MLS write integration is connected for this brokerage."""
    return {
        "connected": False,
        "provider": None,
        # Even if a provider is configured later, push stays gated per market.
        "push_enabled": False,
    }


def is_connected(brokerage: dict[str, Any]) -> bool:
    s = status(brokerage)
    return s["connected"] and s["push_enabled"]


async def push_listing(
    brokerage: dict[str, Any], listing: dict[str, Any]
) -> dict[str, Any]:
    """Push a prepared listing to the MLS. No-op until a write integration lands.

    Returns ``{pushed, mls_number, reason}``.
    """
    return {
        "pushed": False,
        "mls_number": None,
        "reason": (
            "Direct MLS publishing isn't connected. Listings are prepared as "
            "MLS-ready data to enter into your MLS; per-market write integration "
            "is a planned add-on."
        ),
    }
