"""Unattended scheduled scans (the production replacement for the dev buttons).

The deadline reminder scan and the scheduled-reply scan are idempotent,
per-brokerage endpoints designed for a scheduler — but they require a brokerage
JWT, which a cron job doesn't have. This route is the cron-callable variant:
one POST, authenticated by the ``CRON_SECRET`` shared secret, loops every
brokerage and runs both scans.

Point a scheduled job (e.g. a Render cron running every 15 minutes) at:

    curl -X POST https://api.poweredbypenny.com/api/v1/cron/run-scans \
         -H "X-Cron-Secret: $CRON_SECRET"

Safety properties:
  - Disabled (503) when CRON_SECRET is unset; 403 on a wrong secret
    (constant-time compare). Never open.
  - Both scans are idempotent (reminder flags / status transitions are claimed
    before anything goes out), so overlapping or repeated runs can't
    double-send.
  - Per-brokerage isolation: one tenant's failure is recorded and the loop
    moves on. The response always reports what ran and what failed.
  - Nothing here adds send paths — it only invokes the same scans the
    per-brokerage endpoints already expose.
"""

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status

from app.config import settings
from app.core import supabase_client as sb
from app.services import deadline_reminders, email_scheduler, status_updates

router = APIRouter(prefix="/cron", tags=["cron"])
logger = logging.getLogger(__name__)


@router.post("/run-scans")
async def run_scans(
    x_cron_secret: str = Header(default=""),
) -> dict[str, Any]:
    if not settings.CRON_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cron scans are disabled — CRON_SECRET is not configured.",
        )
    if not hmac.compare_digest(x_cron_secret, settings.CRON_SECRET):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid secret")

    brokerages = await sb.list_brokerages()
    summary: dict[str, Any] = {
        "brokerages": len(brokerages),
        "reminders_processed": 0,
        "replies_resurfaced": 0,
        "replies_reminded": 0,
        "status_updates_processed": 0,
        "errors": [],
    }
    for b in brokerages:
        bid = b["id"]
        try:
            result = await deadline_reminders.run_reminders(bid)
            summary["reminders_processed"] += result.get("processed", 0)
        except Exception as exc:  # noqa: BLE001 — one tenant never blocks the rest
            logger.error("Cron reminder scan failed for brokerage %s: %s", bid, exc)
            summary["errors"].append({"brokerage_id": bid, "scan": "reminders"})
        try:
            counts = await email_scheduler.run_for_brokerage(bid)
            summary["replies_resurfaced"] += counts.get("resurfaced", 0)
            summary["replies_reminded"] += counts.get("reminded", 0)
        except Exception as exc:  # noqa: BLE001
            logger.error("Cron reply scan failed for brokerage %s: %s", bid, exc)
            summary["errors"].append({"brokerage_id": bid, "scan": "scheduled-replies"})
        try:
            su = await status_updates.run_status_updates(bid)
            summary["status_updates_processed"] += su.get("processed", 0)
        except Exception as exc:  # noqa: BLE001
            logger.error("Cron status-update scan failed for brokerage %s: %s", bid, exc)
            summary["errors"].append({"brokerage_id": bid, "scan": "status-updates"})

    return {"ok": True, **summary}
