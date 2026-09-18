"""
Signal thread development — repeat alerts on the same symbol/strategy.

Read-only overlay for Journal: price since first alert, latest radar validity.
Never places orders.
"""
from __future__ import annotations

from typing import Any, Optional

from improve.checklist import flatten_signal


def _side_key(side: Any) -> str:
    if side is None:
        return "-"
    return str(side).upper()


def _thread_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("symbol") or "").upper(),
        str(row.get("strategy") or "unknown"),
        _side_key(row.get("side")),
    )


def _radar_for_symbol(radar_rows: dict[str, dict[str, Any]], symbol: str) -> Optional[dict[str, Any]]:
    sym = symbol.upper()
    if sym in radar_rows:
        return radar_rows[sym]
    spot = sym if sym.endswith("USDT") else f"{sym}USDT"
    return radar_rows.get(spot)


def _pct_move(side: Optional[str], entry: float, current: float) -> Optional[float]:
    if entry <= 0 or current <= 0:
        return None
    raw = (current - entry) / entry * 100.0
    if _side_key(side) == "SELL":
        raw = -raw
    return round(raw, 2)


def _is_daily_lane(strategy: str, timeframe: Optional[str]) -> bool:
    st = (strategy or "").lower()
    tf = (timeframe or "").lower()
    return "daily" in st or "breakout" in st or tf in ("1d", "d", "day")


def assess_radar_validity(
    *,
    side: Optional[str],
    strategy: str,
    timeframe: Optional[str],
    radar: Optional[dict[str, Any]],
) -> tuple[str, str]:
    """Return (status, detail) for operator review — not a trade gate."""
    if radar is None:
        return ("UNKNOWN", "No daily radar row for symbol")
    color = str(radar.get("color") or "GREY").upper()
    days = int(radar.get("days_in_state") or 0)
    late = bool(radar.get("is_late_stage"))
    sk = _side_key(side)
    daily = _is_daily_lane(strategy, timeframe)

    if daily:
        want = "GREEN" if sk == "BUY" else "RED" if sk == "SELL" else None
        if want and color != want:
            return ("INVALID", f"Radar now {color} — conflicts with {sk} alert")
        if late:
            return ("LATE", f"Radar {color} but extended ({days}d) — chase risk")
        if days <= 3 and color in ("GREEN", "RED"):
            return ("FRESH", f"Radar {color} · day {days} in regime")
        if want and color == want:
            return ("VALID", f"Radar still {color} · {days}d in trend")
        return ("WATCH", f"Radar {color} · review vs {sk}")

    # Leveraged TEMA lane: daily color as context only
    if sk == "BUY" and color == "RED":
        return ("INVALID", "Daily radar RED — long context weak")
    if sk == "SELL" and color == "GREEN":
        return ("INVALID", "Daily radar GREEN — short context weak")
    if late:
        return ("LATE", f"Daily {color} extended — size down")
    return ("VALID", f"Daily radar {color} · {days}d")


def build_signal_developments(
    signal_rows: list[dict[str, Any]],
    *,
    radar_rows: Optional[list[dict[str, Any]]] = None,
    min_alerts: int = 2,
    include_open_fill_symbols: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Group ENTRY alerts; surface repeats and how price/regime evolved."""
    include_open_fill_symbols = include_open_fill_symbols or set()
    radar_map: dict[str, dict[str, Any]] = {}
    for r in radar_rows or []:
        sym = str(r.get("symbol") or "").upper()
        if sym:
            radar_map[sym] = r

    flat = [flatten_signal(r) for r in signal_rows if str(r.get("event", "entry")).lower() == "entry"]
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in flat:
        buckets.setdefault(_thread_key(row), []).append(row)

    out: list[dict[str, Any]] = []
    for (symbol, strategy, side), alerts in buckets.items():
        alerts_sorted = sorted(alerts, key=lambda r: int(r.get("id") or 0))
        count = len(alerts_sorted)
        if count < min_alerts and symbol not in include_open_fill_symbols:
            continue

        first = alerts_sorted[0]
        latest = alerts_sorted[-1]
        first_price = float(first.get("signal_price") or first.get("price") or 0)
        latest_price = float(latest.get("signal_price") or latest.get("price") or 0)
        radar = _radar_for_symbol(radar_map, symbol)
        mark = float(radar.get("price") or 0) if radar else latest_price
        if mark <= 0:
            mark = latest_price

        status, detail = assess_radar_validity(
            side=side if side != "-" else latest.get("side"),
            strategy=strategy,
            timeframe=str(latest.get("timeframe") or ""),
            radar=radar,
        )

        timeline = [
            {
                "id": int(a.get("id") or 0),
                "received_at": a.get("received_at"),
                "signal_price": a.get("signal_price"),
                "bar_time": a.get("bar_time") or a.get("closed_bar_at"),
                "grade": a.get("grade"),
            }
            for a in reversed(alerts_sorted)
        ]

        out.append(
            {
                "symbol": symbol,
                "strategy": strategy,
                "side": side if side != "-" else latest.get("side"),
                "alert_count": count,
                "first_alert_at": first.get("received_at"),
                "last_alert_at": latest.get("received_at"),
                "first_price": first_price or None,
                "last_alert_price": latest_price or None,
                "mark_price": mark or None,
                "pct_since_first": _pct_move(side, first_price, mark) if first_price else None,
                "pct_since_last_alert": _pct_move(side, latest_price, mark) if latest_price else None,
                "latest_signal_id": int(latest.get("id") or 0),
                "validity_status": status,
                "validity_detail": detail,
                "radar": (
                    {
                        "color": radar.get("color"),
                        "days_in_state": radar.get("days_in_state"),
                        "pct_since_flip": radar.get("pct_since_flip"),
                        "flipped_at": radar.get("flipped_at"),
                        "flip_from": radar.get("flip_from"),
                        "is_late_stage": radar.get("is_late_stage"),
                        "is_fresh_flip": radar.get("is_fresh_flip"),
                        "adx": radar.get("adx"),
                    }
                    if radar
                    else None
                ),
                "timeline": timeline,
            }
        )

    out.sort(
        key=lambda t: (t.get("last_alert_at") or "", t.get("symbol") or ""),
        reverse=True,
    )
    return out
