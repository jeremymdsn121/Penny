"""Broker reporting endpoints (V2 Section 7).

A one-page readout (pipeline / production / compliance) plus a CSV export of
closed deals. Metrics are computed from existing transaction data.
"""

import csv
import io
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core import supabase_client as sb
from app.core.security import get_current_brokerage
from app.services import compliance_checklist, reporting

router = APIRouter(prefix="/reports", tags=["reports"])

_PERIODS = ("month", "quarter", "ytd")


def _norm_period(period: str) -> str:
    return period if period in _PERIODS else "month"


@router.get("/broker-summary")
async def broker_summary(
    period: str = Query("month"),
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> dict[str, Any]:
    period = _norm_period(period)
    txs = await sb.list_transactions(brokerage["id"])
    deadlines = await sb.list_deadlines_in([t["id"] for t in txs])
    agents = {a["id"]: a.get("name") for a in await sb.list_agents(brokerage["id"])}
    return await reporting.build_summary(period, txs, deadlines, agents)


@router.get("/transactions-export")
async def transactions_export(
    period: str = Query("month"),
    brokerage: dict[str, Any] = Depends(get_current_brokerage),
) -> StreamingResponse:
    period = _norm_period(period)
    start = reporting.period_start(period)
    txs = await sb.list_transactions(brokerage["id"])

    def closed_in_period(t: dict[str, Any]) -> bool:
        if t.get("stage") != "closed" or not t.get("closed_at"):
            return False
        try:
            return date.fromisoformat(str(t["closed_at"])[:10]) >= start
        except ValueError:
            return False

    closed = [t for t in txs if closed_in_period(t)]
    agents = {a["id"]: a.get("name") for a in await sb.list_agents(brokerage["id"])}
    pct_map = await compliance_checklist.pct_for_transactions([t["id"] for t in closed])

    rows = reporting.build_export_rows(closed, agents, pct_map)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    buf.seek(0)
    filename = f"sloane-closed-{period}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
