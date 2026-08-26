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
TF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


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
            "timeframe": f.get("timeframe"),
        })
    return trades


def interval_ms(bars: list[dict[str, Any]]) -> int:
    """Median adjacent-bar delta so one missing candle does not blow the grid."""
    if len(bars) < 2:
        return TF_MS["1h"]
    deltas = sorted(int(bars[i]["t"]) - int(bars[i - 1]["t"]) for i in range(1, len(bars)))
    deltas = [d for d in deltas if d > 0]
    if not deltas:
        return TF_MS["1h"]
    return int(deltas[len(deltas) // 2])


def tf_window_ms(timeframe: Any, *, chart_ms: int) -> int:
    key = str(timeframe or "").lower()
    return int(TF_MS.get(key, chart_ms) or chart_ms)


def snap_entry_index(
    bars: list[dict[str, Any]],
    *,
    t: int,
    price: float,
    window_ms: int,
) -> Optional[int]:
    """Map a fill onto the closed candle that actually printed that price.

    HTF alerts are stamped at the *open* of the closed HTF bar, but
    ``signal_price`` is that bar's *close*. On a faster chart that close
    lives on the last LTF candle of the window — not the open.
    """
    if not bars:
        return None
    step = interval_ms(bars)
    window_ms = max(int(window_ms), step)
    lo = int(t) - step
    hi = int(t) + window_ms
    candidates = [i for i, b in enumerate(bars) if lo <= int(b["t"]) < hi]
    if not candidates:
        nearest = min(range(len(bars)), key=lambda i: abs(int(bars[i]["t"]) - int(t)))
        if abs(int(bars[nearest]["t"]) - int(t)) > window_ms + step:
            return None
        return nearest
    containing = [
        i for i in candidates
        if float(bars[i]["l"]) <= float(price) <= float(bars[i]["h"])
    ]
    if containing:
        return containing[-1]
    return min(candidates, key=lambda i: abs(float(bars[i]["c"]) - float(price)))


def snap_exit_index(
    bars: list[dict[str, Any]],
    *,
    after_i: int,
    price: float,
    t: Optional[int] = None,
) -> Optional[int]:
    """First bar *after* the signal bar whose range contains the exit (SL/TP)."""
    if not bars:
        return None
    start = max(0, int(after_i) + 1)
    containing = [
        i for i in range(start, len(bars))
        if float(bars[i]["l"]) <= float(price) <= float(bars[i]["h"])
    ]
    if not containing:
        if t is None:
            return None
        step = interval_ms(bars)
        later = list(range(start, len(bars)))
        if not later:
            return None
        nearest = min(later, key=lambda i: abs(int(bars[i]["t"]) - int(t)))
        if abs(int(bars[nearest]["t"]) - int(t)) > step * 2:
            return None
        return nearest
    if t is not None:
        step = interval_ms(bars)
        for i in containing:
            bt = int(bars[i]["t"])
            if bt <= int(t) < bt + step:
                return i
    return containing[0]


def align_trades(
    bars: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    *,
    chart_tf: str = "1h",
) -> list[dict[str, Any]]:
    """Stamp ``i`` (bar index) so the SVG can sit marks on candle centres."""
    if not bars:
        for tr in trades:
            tr["aligned"] = False
            tr["on_ohlc"] = False
        return trades
    chart_ms = interval_ms(bars)
    out: list[dict[str, Any]] = []
    for tr in trades:
        row = dict(tr)
        entry = dict(row.get("entry") or {})
        t = entry.get("t")
        px = entry.get("price")
        window = tf_window_ms(row.get("timeframe") or chart_tf, chart_ms=chart_ms)
        entry_i: Optional[int] = None
        if t is not None and px is not None:
            entry_i = snap_entry_index(bars, t=int(t), price=float(px), window_ms=window)
        if entry_i is None:
            row["aligned"] = False
            row["on_ohlc"] = False
            row["entry"] = entry
            out.append(row)
            continue
        entry["i"] = entry_i
        entry["t"] = int(bars[entry_i]["t"])
        row["entry"] = entry
        bar = bars[entry_i]
        row["aligned"] = True
        row["on_ohlc"] = float(bar["l"]) <= float(px) <= float(bar["h"])
        ext = row.get("exit")
        if ext and ext.get("price") is not None:
            exit_obj = dict(ext)
            exit_i = snap_exit_index(
                bars,
                after_i=entry_i,
                price=float(exit_obj["price"]),
                t=int(exit_obj["t"]) if exit_obj.get("t") is not None else None,
            )
            if exit_i is not None:
                exit_obj["i"] = exit_i
                exit_obj["t"] = int(bars[exit_i]["t"])
                xb = bars[exit_i]
                exit_obj["on_ohlc"] = float(xb["l"]) <= float(exit_obj["price"]) <= float(xb["h"])
            row["exit"] = exit_obj
        out.append(row)
    return out


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
