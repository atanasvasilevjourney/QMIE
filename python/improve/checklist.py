"""
QMIE native Smart Checklist — operator overlay, not a new score
===============================================================
TrendSpider-style at-a-glance gates on fields QMIE already stores.
Does not call MCP, does not retune W_*, does not place orders.

Verdicts: GO / WATCH / SKIP
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def flatten_signal(row: dict[str, Any]) -> dict[str, Any]:
    """Merge SQLite columns with JSON `raw` so timeframe/adx/htf are visible."""
    extra: dict[str, Any] = {}
    raw = row.get("raw")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                extra = parsed
        except json.JSONDecodeError:
            extra = {}
    elif isinstance(raw, dict):
        extra = raw
    out = dict(extra)
    for k, v in row.items():
        if k == "raw":
            continue
        if v is not None and v != "":
            out[k] = v
    return out


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _s(v: Any) -> str:
    return str(v or "").strip()


def atr_pct_of(flat: dict[str, Any]) -> Optional[float]:
    direct = _f(flat.get("atr_pct"))
    if direct is not None:
        return direct
    atr = _f(flat.get("atr"))
    px = _f(flat.get("signal_price") or flat.get("price"))
    if atr is not None and px and px > 0:
        return 100.0 * atr / px
    return None


def radar_row_for(symbol: str, radar: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not radar:
        return None
    want = _s(symbol).upper()
    for row in radar.get("rows") or []:
        if isinstance(row, dict) and _s(row.get("symbol")).upper() == want:
            return row
    return None


def radar_color_for(symbol: str, radar: Optional[dict[str, Any]]) -> Optional[str]:
    row = radar_row_for(symbol, radar)
    if not row:
        return None
    c = _s(row.get("color")).upper()
    return c or None


def consecutive_manual_losses(
    fills: Optional[list[dict[str, Any]]],
    *,
    symbol: Optional[str] = None,
) -> int:
    """Newest-first streak of closed *manual* losses. Paper rows do not count.

    When ``symbol`` is set, only that ticker's fills count (book-wide
    cooldown starves a 4h alert stream — skip-next is per name).
    """
    if not fills:
        return 0
    want = _s(symbol).upper()
    closed = [
        f for f in fills
        if _s(f.get("outcome")).upper() in ("WIN", "LOSS")
    ]
    if want:
        closed = [f for f in closed if _s(f.get("symbol")).upper() == want]
    closed.sort(key=_fill_sort_key, reverse=True)
    streak = 0
    for f in closed:
        if _s(f.get("source")).lower() == "paper":
            continue
        if _s(f.get("outcome")).upper() == "LOSS":
            streak += 1
            continue
        break
    return streak


def _parse_ts(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        dt = v
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(v).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fill_sort_key(f: dict[str, Any]) -> tuple[float, int]:
    ts = _parse_ts(f.get("updated_at") or f.get("timestamp"))
    epoch = ts.timestamp() if ts is not None else 0.0
    try:
        fid = int(f.get("id") or 0)
    except (TypeError, ValueError):
        fid = 0
    return (epoch, fid)


def last_manual_close_ts(
    fills: Optional[list[dict[str, Any]]],
    *,
    symbol: Optional[str] = None,
) -> Optional[datetime]:
    if not fills:
        return None
    want = _s(symbol).upper()
    best: Optional[datetime] = None
    for f in fills:
        if _s(f.get("outcome")).upper() not in ("WIN", "LOSS"):
            continue
        if _s(f.get("source")).lower() == "paper":
            continue
        if want and _s(f.get("symbol")).upper() != want:
            continue
        ts = _parse_ts(f.get("updated_at") or f.get("timestamp"))
        if ts is not None and (best is None or ts > best):
            best = ts
    return best


COOLDOWN_HOURS = 24.0


@dataclass
class CheckItem:
    id: str
    passed: bool
    required: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NativeChecklist:
    verdict: str  # GO / WATCH / SKIP
    action: str
    symbol: str
    side: str
    grade: str
    timeframe: str
    signal_id: Optional[int] = None
    items: list[CheckItem] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "action": self.action,
            "symbol": self.symbol,
            "side": self.side,
            "grade": self.grade,
            "timeframe": self.timeframe,
            "signal_id": self.signal_id,
            "items": [i.as_dict() for i in self.items],
            "places_orders": False,
        }


def evaluate_native(
    row: dict[str, Any],
    *,
    radar: Optional[dict[str, Any]] = None,
    fills: Optional[list[dict[str, Any]]] = None,
) -> NativeChecklist:
    """Checklist using persisted QMIE fields + optional radar/journal.

    KovaView overlays live here (too_late, btc_regime, cooldown) — not in
    ``compute_signal``. Missing radar/fills never hard-SKIP.
    """
    flat = flatten_signal(row)
    symbol = _s(flat.get("symbol")).upper() or "?"
    side = _s(flat.get("side")).upper()
    grade = _s(flat.get("grade"))
    tf = _s(flat.get("timeframe")).lower()
    strategy = _s(flat.get("strategy"))
    items: list[CheckItem] = []

    is_breakout = "DailyBreakout" in strategy or _s(flat.get("setup_type")) == "breakout"
    grade_ok = grade in ("A", "A+")
    side_ok = side in ("BUY", "SELL")
    if is_breakout:
        items.append(CheckItem(
            "qmie_alert",
            side_ok,
            True,
            f"{strategy or 'QMIE-DailyBreakout'} {side} — separate from A/A+ grade",
        ))
    else:
        items.append(CheckItem(
            "qmie_alert",
            grade_ok and side_ok,
            True,
            f"QMIE {side or '—'} {grade or '—'} "
            f"score {flat.get('score') if flat.get('score') is not None else '—'} "
            "(need A/A+ directional)",
        ))

    htf = _s(flat.get("htf")).lower()
    if not htf:
        items.append(CheckItem("htf_aligned", False, False, "HTF field missing on this row"))
    else:
        items.append(CheckItem(
            "htf_aligned",
            htf == "aligned",
            True,
            f"HTF {htf}",
        ))

    daily = _s(flat.get("daily_trend")).lower()
    if daily in ("", "unknown"):
        items.append(CheckItem("daily_trend", False, False, "daily_trend unknown"))
    elif side == "BUY":
        items.append(CheckItem("daily_trend", daily == "bullish", True, f"daily {daily} vs BUY"))
    elif side == "SELL":
        items.append(CheckItem("daily_trend", daily == "bearish", True, f"daily {daily} vs SELL"))
    else:
        items.append(CheckItem("daily_trend", False, True, f"daily {daily} vs {side or 'no side'}"))

    adx = _f(flat.get("adx"))
    if adx is None:
        items.append(CheckItem("adx_gate", False, False, "ADX missing"))
    else:
        items.append(CheckItem(
            "adx_gate",
            adx >= 20.0,
            False,
            f"ADX {adx:.1f} (measurement protocol ≥ 20; live default still 0)",
        ))

    ap = atr_pct_of(flat)
    if ap is None:
        items.append(CheckItem("atr_band", False, False, "ATR% missing"))
    else:
        items.append(CheckItem(
            "atr_band",
            0.4 <= ap <= 4.0,
            False,
            f"ATR% {ap:.2f} (OOS band 0.4–4.0)",
        ))

    if not tf:
        items.append(CheckItem("timeframe_edge", False, False, "timeframe missing"))
    else:
        items.append(CheckItem(
            "timeframe_edge",
            tf in ("4h", "4H", "240"),
            False,
            f"TF {tf} — frozen OOS: 4h A/A+ PF 1.61, 1h dilutes",
        ))

    color = radar_color_for(symbol, radar)
    if color is None:
        items.append(CheckItem("radar_color", False, False, "No radar row for symbol"))
    elif side == "BUY":
        items.append(CheckItem(
            "radar_color",
            color == "GREEN",
            color == "RED",
            f"Radar {color} vs BUY (RED = skip overlay; GREY = watch)",
        ))
    elif side == "SELL":
        items.append(CheckItem(
            "radar_color",
            color == "RED",
            color == "GREEN",
            f"Radar {color} vs SELL (GREEN = skip overlay; GREY = watch)",
        ))
    else:
        items.append(CheckItem("radar_color", False, False, f"Radar {color}"))

    # KovaView SPY analog: BTC 1D radar. RED blocks new BUY risk.
    # GREY is advisory. SELL is not gated. Missing BTC row = WATCH, not SKIP.
    btc_color = radar_color_for("BTCUSDT", radar)
    if side != "BUY":
        items.append(CheckItem(
            "btc_regime",
            True,
            False,
            f"BTC {btc_color or 'n/a'} — SELL not gated by buys_allowed",
        ))
    elif btc_color is None:
        items.append(CheckItem(
            "btc_regime",
            False,
            False,
            "BTC radar missing — cannot confirm buys_allowed",
        ))
    elif btc_color == "RED":
        items.append(CheckItem(
            "btc_regime",
            False,
            True,
            "BTC RED — buys_allowed false (SPY SMA200 analog)",
        ))
    elif btc_color == "GREY":
        items.append(CheckItem(
            "btc_regime",
            False,
            False,
            "BTC GREY — wait (advisory, not a hard veto)",
        ))
    else:
        items.append(CheckItem(
            "btc_regime",
            True,
            False,
            f"BTC {btc_color} — buys_allowed",
        ))

    # too_late: chase-risk on an extended same-side radar state.
    rrow = radar_row_for(symbol, radar)
    if rrow is None:
        items.append(CheckItem("too_late", False, False, "No radar row for too_late"))
    elif rrow.get("is_late_stage"):
        chasing = (
            (side == "BUY" and color == "GREEN")
            or (side == "SELL" and color == "RED")
        )
        items.append(CheckItem(
            "too_late",
            not chasing,
            chasing,
            (
                f"late-stage {color} chase — skip"
                if chasing
                else f"late-stage {color} — not a same-side chase"
            ),
        ))
    else:
        items.append(CheckItem("too_late", True, False, "not late-stage"))

    streak = consecutive_manual_losses(fills, symbol=symbol)
    last_loss_book = last_manual_close_ts(fills, symbol=symbol)
    sig_ts = _parse_ts(flat.get("timestamp") or flat.get("bar_time"))
    if streak >= 2 and last_loss_book is not None and sig_ts is not None:
        hours = (sig_ts - last_loss_book).total_seconds() / 3600.0
        if hours < COOLDOWN_HOURS:
            items.append(CheckItem(
                "cooldown",
                False,
                True,
                f"{streak} consecutive {symbol} manual losses — "
                f"{hours:.1f}h < {COOLDOWN_HOURS:.0f}h pause",
            ))
        else:
            items.append(CheckItem(
                "cooldown",
                True,
                False,
                f"{symbol} streak {streak} but pause expired ({hours:.0f}h)",
            ))
    elif streak >= 2:
        items.append(CheckItem(
            "cooldown",
            False,
            False,
            f"{streak} consecutive {symbol} losses — no clocks; confirm skip-next",
        ))
    else:
        items.append(CheckItem(
            "cooldown",
            True,
            False,
            f"cooldown clear ({symbol} manual loss streak {streak}; paper ignored)",
        ))

    fr = _f(flat.get("funding_rate"))
    if fr is None:
        items.append(CheckItem("funding", False, False, "funding_rate missing"))
    else:
        crowded = (side == "BUY" and fr > 0.001) or (side == "SELL" and fr < -0.001)
        items.append(CheckItem(
            "funding",
            not crowded,
            False,
            f"funding {fr:.5f} (crowded if BUY>+0.001 or SELL<-0.001)",
        ))

    required_fail = [i for i in items if i.required and not i.passed]
    optional_fail = [i for i in items if (not i.required) and not i.passed]
    if required_fail:
        verdict = "SKIP"
        action = (
            "Skip this alert. Required overlay failed: "
            + ", ".join(i.id for i in required_fail)
            + ". Not an order. Do not retune W_*."
        )
    elif optional_fail:
        verdict = "WATCH"
        action = (
            "Watch — optional gates failed: "
            + ", ".join(i.id for i in optional_fail)
            + ". Open the Pine visualizer before clicking."
        )
    else:
        verdict = "GO"
        action = (
            "Overlay agrees with stored QMIE fields. Confirm on "
            "quant_visualizer.pine, then enter manually. Not an order."
        )
    sid = flat.get("id")
    try:
        signal_id = int(sid) if sid is not None else None
    except (TypeError, ValueError):
        signal_id = None
    return NativeChecklist(
        verdict=verdict,
        action=action,
        symbol=symbol,
        side=side,
        grade=grade,
        timeframe=tf,
        signal_id=signal_id,
        items=items,
    )
