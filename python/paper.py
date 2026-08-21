"""
QMIE — Paper book (signal-only)
================================
Auto-fills journal rows against dispatched alerts and closes them when
the next closed bars touch SL or TP. Never talks to a broker.

Each alert gets its own paper fill (independent, like the backtest
look-ahead). Size is a USDT notional / entry. EXIT rows are persisted
as QMIE-Paper event=exit so the desk can show close + PnL.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from db import Database
from journal import cash_pnl, outcome_from_close, realized_r
from models import AssetClass, EventType, Side, TVSignal

logger = logging.getLogger(__name__)

PAPER_NOTE = "paper auto-fill"
PAPER_STRATEGY = "QMIE-Paper"


def paper_size(fill_price: float, notional_usdt: float) -> float:
    if fill_price <= 0 or notional_usdt <= 0:
        return 0.0
    return round(notional_usdt / fill_price, 8)


def hit_exit(
    side: str,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    high: float,
    low: float,
) -> Optional[tuple[str, float]]:
    """Same-bar SL+TP → SL (conservative, matches backtest)."""
    side_u = (side or "").upper()
    buy = side_u == "BUY"
    sl = stop_loss
    tp = take_profit
    sl_hit = sl is not None and ((buy and low <= sl) or ((not buy) and high >= sl))
    tp_hit = tp is not None and ((buy and high >= tp) or ((not buy) and low <= tp))
    if sl_hit:
        return "stop_loss", float(sl)
    if tp_hit:
        return "take_profit", float(tp)
    return None


def first_bar_exit(
    df: pd.DataFrame,
    *,
    side: str,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    after: Optional[pd.Timestamp],
) -> Optional[tuple[str, float, pd.Timestamp]]:
    if df is None or df.empty:
        return None
    if stop_loss is None and take_profit is None:
        return None
    for ts, row in df.iterrows():
        ts_p = pd.Timestamp(ts)
        if after is not None and ts_p <= after:
            continue
        hit = hit_exit(side, stop_loss, take_profit, float(row["high"]), float(row["low"]))
        if hit is None:
            continue
        reason, px = hit
        return reason, px, ts_p
    return None


def _as_ts(value: Any) -> Optional[pd.Timestamp]:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) and value > 10_000_000_000:
            return pd.Timestamp(int(value), unit="ms", tz="UTC")
        if isinstance(value, (int, float)) and value > 1_000_000_000:
            return pd.Timestamp(int(value), unit="s", tz="UTC")
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts
    except Exception:
        return None


class PaperBook:
    def __init__(
        self,
        db: Database,
        *,
        enabled: bool = True,
        notional_usdt: float = 1000.0,
        notify_exits: bool = False,
    ):
        self.db = db
        self.enabled = enabled
        self.notional_usdt = notional_usdt
        self.notify_exits = notify_exits

    async def open_entry(self, signal_id: int) -> Optional[dict[str, Any]]:
        if not self.enabled or not signal_id:
            return None
        sig = await self.db.get_signal(signal_id)
        if sig is None:
            return None
        if str(sig.get("event") or "").lower() in ("exit", "close"):
            return None
        if (sig.get("strategy") or "") == PAPER_STRATEGY:
            return None
        existing = await self.db.fill_for_signal(signal_id)
        if existing is not None:
            return None
        px = float(sig.get("signal_price") or 0)
        size = paper_size(px, self.notional_usdt)
        if px <= 0 or size <= 0:
            return None
        return await self.db.insert_fill(
            signal_id=signal_id,
            fill_price=px,
            size=size,
            exit_price=None,
            notes=PAPER_NOTE,
            realized_r=None,
            outcome="OPEN",
            pnl=None,
            source="paper",
            exit_reason=None,
        )

    async def sync_entries(self) -> int:
        """Open a paper fill for every stored entry that has none."""
        if not self.enabled:
            return 0
        n = 0
        for row in await self.db.entry_signals_without_fill():
            opened = await self.open_entry(int(row["id"]))
            if opened is not None:
                n += 1
        return n

    async def close_fill_at(
        self,
        fill: dict[str, Any],
        *,
        exit_price: float,
        reason: str,
        bar_time: Optional[pd.Timestamp] = None,
    ) -> dict[str, Any]:
        sig = await self.db.get_signal(int(fill["signal_id"]))
        if sig is None:
            raise ValueError("signal_not_found")
        side = sig.get("side")
        fill_px = float(fill["fill_price"])
        size = float(fill["size"])
        sl = sig.get("stop_loss")
        r = realized_r(side, fill_px, exit_price, sl)
        pnl = cash_pnl(side, fill_px, exit_price, size)
        outcome = outcome_from_close(r=r, pnl=pnl, has_exit=True)
        notes = fill.get("notes") or PAPER_NOTE
        closed = await self.db.update_fill_exit(
            int(fill["id"]),
            exit_price=exit_price,
            realized_r=r,
            outcome=outcome,
            notes=notes,
            pnl=pnl,
            exit_reason=reason,
        )
        await self._persist_exit_signal(
            sig,
            fill=fill,
            exit_price=exit_price,
            pnl=pnl,
            realized_r=r,
            reason=reason,
            bar_time=bar_time,
        )
        return closed

    async def mark_from_bars(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        timeframe: str,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        closed: list[dict[str, Any]] = []
        for fill in await self.db.open_fills():
            if str(fill.get("symbol") or "").upper() != symbol.upper():
                continue
            tf = str(fill.get("timeframe") or "").lower()
            if tf and tf != timeframe.lower():
                continue
            after = _as_ts(fill.get("bar_time")) or _as_ts(fill.get("created_at"))
            hit = first_bar_exit(
                df,
                side=str(fill.get("side") or ""),
                stop_loss=fill.get("stop_loss"),
                take_profit=fill.get("take_profit"),
                after=after,
            )
            if hit is None:
                continue
            reason, px, ts = hit
            closed.append(
                await self.close_fill_at(fill, exit_price=px, reason=reason, bar_time=ts)
            )
        return closed

    async def mark_with_client(self, client: Any) -> dict[str, int]:
        """Fetch klines per open (symbol, tf) and close SL/TP hits."""
        if not self.enabled:
            return {"closed": 0, "checked": 0}
        opens = await self.db.open_fills()
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for fill in opens:
            sym = str(fill.get("symbol") or "").upper()
            tf = str(fill.get("timeframe") or "1h").lower() or "1h"
            if not sym:
                continue
            groups.setdefault((sym, tf), []).append(fill)
        n_closed = 0
        for (sym, tf), _fills in groups.items():
            try:
                df = await client.fetch_klines(sym, tf, limit=200)
            except Exception:
                logger.warning("paper klines failed %s %s", sym, tf, exc_info=True)
                continue
            closed = await self.mark_from_bars(df, symbol=sym, timeframe=tf)
            n_closed += len(closed)
        return {"closed": n_closed, "checked": len(opens)}

    async def sync_all(self, client: Any | None = None) -> dict[str, int]:
        opened = await self.sync_entries()
        marked = {"closed": 0, "checked": 0}
        if client is not None:
            marked = await self.mark_with_client(client)
        return {"opened": opened, **marked}

    async def snapshot(self) -> dict[str, Any]:
        fills = await self.db.recent_fills(limit=200)
        paper = [f for f in fills if (f.get("source") or "") == "paper"]
        closed = [f for f in paper if (f.get("outcome") or "OPEN") != "OPEN"]
        pnls = [float(f["pnl"]) for f in closed if f.get("pnl") is not None]
        return {
            "enabled": self.enabled,
            "notional_usdt": self.notional_usdt,
            "places_orders": False,
            "fills": len(paper),
            "open": sum(1 for f in paper if (f.get("outcome") or "OPEN") == "OPEN"),
            "closed": len(closed),
            "closed_pnl": round(sum(pnls), 4) if pnls else 0.0,
        }

    async def _persist_exit_signal(
        self,
        sig: dict[str, Any],
        *,
        fill: dict[str, Any],
        exit_price: float,
        pnl: Optional[float],
        realized_r: Optional[float],
        reason: str,
        bar_time: Optional[pd.Timestamp],
    ) -> None:
        side_raw = sig.get("side")
        try:
            side = Side(str(side_raw).upper()) if side_raw else None
        except ValueError:
            side = None
        bar_ms = None
        if bar_time is not None and not pd.isna(bar_time):
            bar_ms = int(pd.Timestamp(bar_time).value // 1_000_000)
        if bar_ms is None:
            bar_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        exit_sig = TVSignal(
            strategy=PAPER_STRATEGY,
            event=EventType.EXIT,
            symbol=str(sig.get("symbol") or fill.get("symbol") or ""),
            asset_class=AssetClass.CRYPTO,
            timeframe=sig.get("timeframe") or fill.get("timeframe"),
            side=side,
            signal_price=exit_price,
            stop_loss=sig.get("stop_loss"),
            take_profit=sig.get("take_profit"),
            score=sig.get("score"),
            reason=f"paper_{reason}",
            setup_type="paper_exit",
            daily_trend=sig.get("daily_trend"),
            bar_time=bar_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
            pnl=pnl,
            realized_r=realized_r,
            fill_id=fill.get("id"),
            entry_price=fill.get("fill_price"),
            entry_signal_id=fill.get("signal_id"),
            size=fill.get("size"),
        )
        try:
            await self.db.insert_signal(exit_sig)
        except Exception:
            logger.exception("paper EXIT persist failed (non-fatal)")
