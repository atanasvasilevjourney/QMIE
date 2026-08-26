"""
QMIE — Manual trade journal
===========================
Records fills against persisted scanner alerts. No broker, no orders.
Used to compare what the operator actually took vs the alert stream.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from db import Database
from models import JournalClose, JournalCreate

logger = logging.getLogger(__name__)


class JournalError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def realized_r(
    side: Optional[str],
    fill: float,
    exit_px: float,
    stop: Optional[float],
) -> Optional[float]:
    """R-multiple vs the signal stop. Positive = in favour of the side."""
    if stop is None:
        return None
    risk = abs(fill - stop)
    if risk <= 0:
        return None
    side_u = (side or "").upper()
    if side_u == "BUY":
        return round((exit_px - fill) / risk, 4)
    if side_u == "SELL":
        return round((fill - exit_px) / risk, 4)
    return None


def cash_pnl(
    side: Optional[str],
    fill: float,
    exit_px: float,
    size: float,
) -> Optional[float]:
    """Signed USDT PnL. Positive = in favour of the side. Not an order."""
    if size <= 0:
        return None
    side_u = (side or "").upper()
    if side_u == "BUY":
        return round(size * (exit_px - fill), 4)
    if side_u == "SELL":
        return round(size * (fill - exit_px), 4)
    return None


def outcome_from_r(r: Optional[float], has_exit: bool) -> str:
    if not has_exit:
        return "OPEN"
    if r is None:
        return "OPEN"
    return "WIN" if r > 0 else "LOSS"


def outcome_from_close(
    *,
    r: Optional[float],
    pnl: Optional[float],
    has_exit: bool,
) -> str:
    if not has_exit:
        return "OPEN"
    if r is not None:
        return "WIN" if r > 0 else "LOSS"
    if pnl is not None:
        return "WIN" if pnl > 0 else "LOSS"
    return "OPEN"


def drift_message(
    *,
    live_win_pct: float,
    baseline: float,
    closed: int,
    min_fills: int,
    pts: float,
) -> Optional[str]:
    """Return an alert string when live A/A+ win rate drifts, else None."""
    if closed < min_fills:
        return None
    if abs(live_win_pct - baseline) <= pts:
        return None
    direction = "above" if live_win_pct > baseline else "below"
    return (
        f"Journal drift: live A/A+ win {live_win_pct:.1f}% is {direction} "
        f"OOS baseline {baseline:.1f}% by {abs(live_win_pct - baseline):.1f} pts "
        f"(n={closed} closed fills)."
    )


async def create_fill(db: Database, body: JournalCreate) -> dict[str, Any]:
    sig = await db.get_signal(body.signal_id)
    if sig is None:
        raise JournalError(404, "signal_not_found")
    if body.size <= 0 or body.fill_price <= 0:
        raise JournalError(400, "fill_price_and_size_must_be_positive")

    has_exit = body.exit_price is not None
    if has_exit and body.exit_price <= 0:
        raise JournalError(400, "exit_price_must_be_positive")

    r = (
        realized_r(sig.get("side"), body.fill_price, body.exit_price, sig.get("stop_loss"))
        if has_exit else None
    )
    pnl = (
        cash_pnl(sig.get("side"), body.fill_price, body.exit_price, body.size)
        if has_exit else None
    )
    outcome = outcome_from_close(r=r, pnl=pnl, has_exit=has_exit)
    return await db.insert_fill(
        signal_id=body.signal_id,
        fill_price=body.fill_price,
        size=body.size,
        exit_price=body.exit_price,
        notes=body.notes,
        realized_r=r,
        outcome=outcome,
        pnl=pnl,
        source="manual",
        exit_reason="manual" if has_exit else None,
    )


async def close_fill(db: Database, fill_id: int, body: JournalClose) -> dict[str, Any]:
    row = await db.get_fill(fill_id)
    if row is None:
        raise JournalError(404, "fill_not_found")
    if body.exit_price <= 0:
        raise JournalError(400, "exit_price_must_be_positive")
    sig = await db.get_signal(int(row["signal_id"]))
    if sig is None:
        raise JournalError(404, "signal_not_found")
    r = realized_r(sig.get("side"), float(row["fill_price"]), body.exit_price, sig.get("stop_loss"))
    pnl = cash_pnl(sig.get("side"), float(row["fill_price"]), body.exit_price, float(row["size"]))
    notes = body.notes if body.notes is not None else row.get("notes")
    return await db.update_fill_exit(
        fill_id,
        exit_price=body.exit_price,
        realized_r=r,
        outcome=outcome_from_close(r=r, pnl=pnl, has_exit=True),
        notes=notes,
        pnl=pnl,
        exit_reason=row.get("exit_reason") or "manual",
    )
