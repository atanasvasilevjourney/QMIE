"""
QMIE — Desk chart payloads (SVG-ready JSON)
===========================================
Builders only. The UI draws SVG; we do not add a JS chart library.
Never an order ticket.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

ALLOWED_CHART_TFS = frozenset({"1h", "4h", "1d"})


def ts_ms(value: Any) -> Optional[int]:
    """Parse ISO / pandas / epoch-sec / epoch-ms into UTC epoch milliseconds."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v <= 0:
            return None
        if v < 1e11:  # seconds
            return int(v * 1000)
        return int(v)
    try:
        t = pd.Timestamp(value)
        if pd.isna(t):
            return None
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        else:
            t = t.tz_convert("UTC")
        return int(t.value // 1_000_000)
    except (ValueError, TypeError, OverflowError):
        return None


def bars_payload(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Closed OHLCV → list of {t,o,h,l,c,v}. ``t`` is epoch ms."""
    if df is None or df.empty:
        return []
    out: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        t = ts_ms(ts)
        if t is None:
            continue
        out.append({
            "t": t,
            "o": round(float(row["open"]), 8),
            "h": round(float(row["high"]), 8),
            "l": round(float(row["low"]), 8),
            "c": round(float(row["close"]), 8),
            "v": round(float(row["volume"]) if "volume" in row and row["volume"] is not None else 0.0, 8),
        })
    return out


def trades_payload(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One mark-set per journal/paper fill: entry, optional exit, SL/TP."""
    trades: list[dict[str, Any]] = []
    for f in fills:
        entry_px = f.get("fill_price")
        if entry_px is None:
            continue
        entry_t = ts_ms(f.get("bar_time")) or ts_ms(f.get("created_at"))
        if entry_t is None:
            continue
        sl = f.get("stop_loss")
        tp = f.get("take_profit")
        exit_px = f.get("exit_price")
        exit_obj: Optional[dict[str, Any]] = None
        if exit_px is not None:
            exit_t = ts_ms(f.get("updated_at")) or entry_t
            pnl = f.get("pnl")
            exit_obj = {
                "t": exit_t,
                "price": round(float(exit_px), 8),
                "pnl": None if pnl is None else round(float(pnl), 4),
                "reason": f.get("exit_reason"),
            }
        trades.append({
            "fill_id": f.get("id"),
            "symbol": f.get("symbol"),
            "side": (f.get("side") or "").upper(),
            "grade": f.get("grade"),
            "source": f.get("source") or "manual",
            "outcome": f.get("outcome"),
            "size": f.get("size"),
            "entry": {"t": entry_t, "price": round(float(entry_px), 8)},
            "exit": exit_obj,
            "stop_loss": None if sl is None else round(float(sl), 8),
            "take_profit": None if tp is None else round(float(tp), 8),
        })
    return trades


def equity_payload(fills: list[dict[str, Any]]) -> dict[str, Any]:
    """Cumulative cash PnL from closed fills. Starting equity is 0 (not a broker)."""
    closed = [
        f for f in fills
        if f.get("exit_price") is not None and f.get("pnl") is not None
    ]
    closed.sort(key=lambda f: (ts_ms(f.get("updated_at")) or 0, int(f.get("id") or 0)))
    points: list[dict[str, Any]] = [{"t": None, "equity": 0.0, "pnl": 0.0, "n": 0}]
    eq = 0.0
    for i, f in enumerate(closed, start=1):
        eq += float(f["pnl"])
        points.append({
            "t": ts_ms(f.get("updated_at")) or ts_ms(f.get("created_at")),
            "equity": round(eq, 4),
            "pnl": round(float(f["pnl"]), 4),
            "n": i,
            "fill_id": f.get("id"),
            "symbol": f.get("symbol"),
            "outcome": f.get("outcome"),
            "source": f.get("source"),
        })
    counts: dict[str, int] = {}
    tfs: dict[str, int] = {}
    for f in fills:
        sym = f.get("symbol")
        if sym:
            counts[sym] = counts.get(sym, 0) + 1
        tf = f.get("timeframe")
        if tf:
            tfs[str(tf)] = tfs.get(str(tf), 0) + 1
    open_n = sum(1 for f in fills if f.get("outcome") == "OPEN" or f.get("exit_price") is None)
    return {
        "places_orders": False,
        "starting_eq": 0.0,
        "fills": len(fills),
        "closed": len(closed),
        "open": open_n,
        "sum_pnl": round(eq, 4),
        "points": points,
        "symbols": [
            {"symbol": k, "fills": v}
            for k, v in sorted(counts.items())
        ],
        "timeframes": [
            {"timeframe": k, "fills": v}
            for k, v in sorted(tfs.items())
        ],
    }
