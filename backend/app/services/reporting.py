"""Broker reporting (V2 Section 7).

One-page pipeline/production/compliance readout computed entirely from existing
transaction data — no external BI. Periods: month | quarter | ytd.
"""

from datetime import date, datetime
from typing import Any

from app.services import compliance_checklist

ACTIVE_STAGES = ("under_contract", "pending")


def period_start(period: str, today: date | None = None) -> date:
    today = today or date.today()
    if period == "quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        return date(today.year, q_start_month, 1)
    if period == "ytd":
        return date(today.year, 1, 1)
    # default: month
    return date(today.year, today.month, 1)


def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


def _parse_date(v: Any) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _deal_volume(tx: dict[str, Any]) -> float:
    return _num(tx.get("sale_price")) or _num(tx.get("list_price"))


async def build_summary(
    period: str,
    transactions: list[dict[str, Any]],
    deadlines: list[dict[str, Any]],
    agents: dict[str, str | None],
) -> dict[str, Any]:
    today = date.today()
    start = period_start(period, today)
    month_start = date(today.year, today.month, 1)

    active = [t for t in transactions if (t.get("stage") or "") in ACTIVE_STAGES]
    closed_period = [
        t
        for t in transactions
        if (t.get("stage") == "closed")
        and (_parse_date(t.get("closed_at")) is not None)
        and (_parse_date(t.get("closed_at")) >= start)
    ]

    # --- Pipeline ---
    by_stage: dict[str, int] = {}
    for t in active:
        by_stage[t["stage"]] = by_stage.get(t["stage"], 0) + 1
    month_end = _month_end(today)
    closing_this_month = [
        t
        for t in active
        if (d := _parse_date(t.get("closing_date"))) is not None
        and month_start <= d <= month_end
    ]

    pipeline = {
        "active_transactions": len(active),
        "active_volume": round(sum(_deal_volume(t) for t in active)),
        "by_stage": by_stage,
        "closing_this_month": len(closing_this_month),
        "closing_this_month_volume": round(sum(_deal_volume(t) for t in closing_this_month)),
    }

    # --- At risk ---
    active_ids = [t["id"] for t in active]
    pct_map = await compliance_checklist.pct_for_transactions(active_ids)
    overdue_by_tx: set[str] = set()
    for d in deadlines:
        if d.get("resolved"):
            continue
        due = _parse_date(d.get("due_date"))
        if due and due < today and d.get("transaction_id") in set(active_ids):
            overdue_by_tx.add(d["transaction_id"])
    closing_soon_incomplete = 0
    stale = 0
    for t in active:
        closing = _parse_date(t.get("closing_date"))
        if closing is not None and (closing - today).days <= 5 and pct_map.get(t["id"], 0) < 80:
            closing_soon_incomplete += 1
        last = t.get("last_activity_at")
        last_dt = _parse_date(last)
        if last_dt is None or (today - last_dt).days >= 7:
            stale += 1
    at_risk = {
        "overdue_deadlines": len(overdue_by_tx),
        "closing_soon_incomplete": closing_soon_incomplete,
        "stale_transactions": stale,
    }

    # --- Production ---
    closed_ids = [t["id"] for t in closed_period]
    closed_pct = await compliance_checklist.pct_for_transactions(closed_ids)
    days_list: list[int] = []
    agent_agg: dict[str, dict[str, Any]] = {}
    for t in closed_period:
        created = _parse_dt(t.get("created_at"))
        closed = _parse_dt(t.get("closed_at"))
        if created and closed:
            days_list.append((closed.date() - created.date()).days)
        aid = t.get("agent_id")
        name = agents.get(aid) or "Unassigned"
        agg = agent_agg.setdefault(name, {"agent_name": name, "closed": 0, "volume": 0.0})
        agg["closed"] += 1
        agg["volume"] += _deal_volume(t)
    production = {
        "closed_count": len(closed_period),
        "closed_volume": round(sum(_deal_volume(t) for t in closed_period)),
        "avg_days_to_close": round(sum(days_list) / len(days_list)) if days_list else 0,
        "agent_breakdown": [
            {**a, "volume": round(a["volume"])}
            for a in sorted(agent_agg.values(), key=lambda x: x["volume"], reverse=True)
        ],
    }

    # --- Compliance ---
    avg_at_close = (
        round(sum(closed_pct.get(i, 0) for i in closed_ids) / len(closed_ids))
        if closed_ids
        else 0
    )
    compliance = {
        "avg_checklist_completion_at_close": avg_at_close,
        "open_compliance_items_total": await _open_items_total(active_ids),
        "needs_attention": sum(1 for t in active if t.get("compliance_status") == "needs_attention"),
    }

    return {
        "period": period,
        "pipeline": pipeline,
        "at_risk": at_risk,
        "production": production,
        "compliance": compliance,
    }


async def _open_items_total(active_ids: list[str]) -> int:
    from app.core import supabase_client as sb

    rows = await sb.checklist_items_in(active_ids)
    return sum(1 for r in rows if r.get("status") == "pending")


def _month_end(today: date) -> date:
    if today.month == 12:
        return date(today.year, 12, 31)
    nxt = date(today.year, today.month + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def _parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def build_export_rows(
    transactions: list[dict[str, Any]],
    agents: dict[str, str | None],
    pct_map: dict[str, int],
) -> list[list[str]]:
    """Rows (incl. header) of closed transactions for CSV export."""
    rows = [
        [
            "Address",
            "Buyer",
            "Seller",
            "Price",
            "Close date",
            "Agent",
            "Days to close",
            "Checklist %",
        ]
    ]
    for t in transactions:
        created = _parse_dt(t.get("created_at"))
        closed = _parse_dt(t.get("closed_at"))
        days = (closed.date() - created.date()).days if created and closed else ""
        rows.append(
            [
                t.get("address") or "",
                t.get("buyer_name") or "",
                t.get("seller_name") or "",
                str(int(_deal_volume(t))) if _deal_volume(t) else "",
                (str(t.get("closed_at"))[:10] if t.get("closed_at") else ""),
                agents.get(t.get("agent_id")) or "",
                str(days),
                str(pct_map.get(t["id"], 0)),
            ]
        )
    return rows
