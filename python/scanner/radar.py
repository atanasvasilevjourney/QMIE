"""
QMIE — Daily Trend Radar (RGG + coil breakouts)
===============================================
Signal-only market map on **daily** candles. Inspired by Signum-style
Trend Radar, implemented with QMIE's Pine-compatible ADX/DMI.

Does **not** place orders. Does **not** retune W_* scoring weights.
Optional Discord/Telegram digest only.

RGG (Red / Grey / Green):
  * GREEN — ADX strong and +DI > −DI (uptrend)
  * RED   — ADX strong and −DI > +DI (downtrend)
  * GREY  — ADX weak / consolidating (coil / chop)

Hysteresis avoids daily color flicker:
  leave GREY only when ADX >= enter_adx;
  enter GREY from a trend only when ADX < exit_adx.

Coil / breakout:
  20-day (configurable) high-low range width as % of close.
  Tight coil = GREY (or any) with width <= coil_max_width_pct.
  Breakout = close outside the prior lookback range after a tight coil.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import numpy as np
import pandas as pd

from .indicators import adx

logger = logging.getLogger(__name__)

Color = Literal["GREEN", "GREY", "RED"]
Breakout = Literal["UP", "DOWN"]


@dataclass
class RadarConfig:
    adx_length: int = 14
    enter_adx: float = 25.0       # leave GREY → trend
    exit_adx: float = 18.0        # trend → GREY
    coil_lookback: int = 20
    coil_max_width_pct: float = 15.0
    fresh_flip_days: int = 3
    late_stage_days: int = 30
    late_stage_move_pct: float = 50.0
    kline_limit: int = 250
    min_bars: int = 60            # need enough history for ADX + coil
    notify: bool = True


@dataclass
class RadarRow:
    symbol: str
    color: Color
    days_in_state: int
    flipped_at: Optional[str]
    pct_since_flip: float
    price: float
    adx: float
    plus_di: float
    minus_di: float
    coil_width_pct: Optional[float]
    coil_high: Optional[float]
    coil_low: Optional[float]
    breakout: Optional[Breakout]
    is_fresh_flip: bool
    is_tight_coil: bool
    is_late_stage: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RadarSnapshot:
    as_of: str
    timeframe: str
    count: int
    green: int
    grey: int
    red: int
    fresh_green: list[dict[str, Any]] = field(default_factory=list)
    fresh_red: list[dict[str, Any]] = field(default_factory=list)
    tight_coils: list[dict[str, Any]] = field(default_factory=list)
    breakouts: list[dict[str, Any]] = field(default_factory=list)
    late_stage_green: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _raw_color(adx_v: float, pdi: float, mdi: float, *, grey_adx: float) -> Color:
    """Instantaneous color without hysteresis (used as seed / candidate)."""
    if not np.isfinite(adx_v) or adx_v < grey_adx:
        return "GREY"
    if pdi > mdi:
        return "GREEN"
    if mdi > pdi:
        return "RED"
    return "GREY"


def classify_rgg_series(
    plus_di: pd.Series,
    minus_di: pd.Series,
    adx_s: pd.Series,
    *,
    enter_adx: float = 25.0,
    exit_adx: float = 18.0,
) -> pd.Series:
    """
    Walk ADX/DMI bar-by-bar applying hysteresis.

    Grey band: ADX < enter_adx keeps / enters consolidation.
    From GREY, need ADX >= enter_adx AND clear DI side to flip GREEN/RED.
    From GREEN/RED, drop to GREY when ADX < exit_adx; flip opposite side
    when ADX still strong and DI crosses.
    """
    if exit_adx > enter_adx:
        raise ValueError("exit_adx must be <= enter_adx")

    n = len(adx_s)
    out: list[Optional[str]] = [None] * n
    state: Optional[Color] = None

    for i in range(n):
        a = float(adx_s.iloc[i])
        p = float(plus_di.iloc[i])
        m = float(minus_di.iloc[i])
        if not np.isfinite(a):
            out[i] = state or "GREY"
            continue

        if state is None:
            # Seed with a soft grey threshold halfway between exit/enter
            mid = (enter_adx + exit_adx) / 2.0
            state = _raw_color(a, p, m, grey_adx=mid)
            out[i] = state
            continue

        if state == "GREY":
            if a >= enter_adx:
                if p > m:
                    state = "GREEN"
                elif m > p:
                    state = "RED"
                # else stay GREY (DI tied)
        elif state == "GREEN":
            if a < exit_adx:
                state = "GREY"
            elif m > p and a >= enter_adx:
                state = "RED"
        elif state == "RED":
            if a < exit_adx:
                state = "GREY"
            elif p > m and a >= enter_adx:
                state = "GREEN"

        out[i] = state

    return pd.Series(out, index=adx_s.index, dtype="object")


def _coil_metrics(
    df: pd.DataFrame,
    *,
    lookback: int,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (width_pct, high, low) over the last `lookback` closed bars."""
    if len(df) < lookback:
        return None, None, None
    window = df.iloc[-lookback:]
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    close = float(df["close"].iloc[-1])
    if close <= 0 or not np.isfinite(close):
        return None, hi, lo
    width = (hi - lo) / close * 100.0
    return round(width, 3), hi, lo


def _detect_breakout(
    df: pd.DataFrame,
    *,
    lookback: int,
    coil_max_width_pct: float,
) -> Optional[Breakout]:
    """
    Breakout on the latest closed bar: the *prior* lookback window was a
    tight coil, and today's close is outside that prior range.
    """
    if len(df) < lookback + 1:
        return None
    prior = df.iloc[-(lookback + 1):-1]
    hi = float(prior["high"].max())
    lo = float(prior["low"].min())
    prior_close = float(prior["close"].iloc[-1])
    if prior_close <= 0:
        return None
    width = (hi - lo) / prior_close * 100.0
    if width > coil_max_width_pct:
        return None
    close = float(df["close"].iloc[-1])
    if close > hi:
        return "UP"
    if close < lo:
        return "DOWN"
    return None


def classify_symbol(
    df: pd.DataFrame,
    symbol: str,
    *,
    cfg: Optional[RadarConfig] = None,
) -> Optional[RadarRow]:
    """Classify one symbol's daily OHLCV into a RadarRow. None if too short."""
    cfg = cfg or RadarConfig()
    if df is None or len(df) < cfg.min_bars:
        return None

    plus_di, minus_di, adx_s = adx(df, cfg.adx_length)
    colors = classify_rgg_series(
        plus_di, minus_di, adx_s,
        enter_adx=cfg.enter_adx,
        exit_adx=cfg.exit_adx,
    )
    color = str(colors.iloc[-1])
    if color not in ("GREEN", "GREY", "RED"):
        color = "GREY"

    # days_in_state: walk backward while color matches
    days = 1
    for i in range(len(colors) - 2, -1, -1):
        if colors.iloc[i] == color:
            days += 1
        else:
            break

    flip_idx = len(colors) - days
    flipped_at: Optional[str] = None
    pct_since = 0.0
    price = float(df["close"].iloc[-1])
    if flip_idx > 0:
        flipped_at = pd.Timestamp(df.index[flip_idx]).isoformat()
        entry = float(df["close"].iloc[flip_idx])
        if entry > 0:
            pct_since = round((price - entry) / entry * 100.0, 2)
    elif len(df) > 0:
        flipped_at = pd.Timestamp(df.index[0]).isoformat()

    width, coil_hi, coil_lo = _coil_metrics(df, lookback=cfg.coil_lookback)
    brk = _detect_breakout(
        df, lookback=cfg.coil_lookback, coil_max_width_pct=cfg.coil_max_width_pct,
    )
    is_tight = width is not None and width <= cfg.coil_max_width_pct
    is_fresh = days <= cfg.fresh_flip_days and color in ("GREEN", "RED")
    is_late = (
        color == "GREEN"
        and days >= cfg.late_stage_days
        and abs(pct_since) >= cfg.late_stage_move_pct
    )

    return RadarRow(
        symbol=symbol.upper(),
        color=color,  # type: ignore[arg-type]
        days_in_state=days,
        flipped_at=flipped_at,
        pct_since_flip=pct_since,
        price=price,
        adx=round(float(adx_s.iloc[-1]), 2),
        plus_di=round(float(plus_di.iloc[-1]), 2),
        minus_di=round(float(minus_di.iloc[-1]), 2),
        coil_width_pct=width,
        coil_high=coil_hi,
        coil_low=coil_lo,
        breakout=brk,
        is_fresh_flip=is_fresh,
        is_tight_coil=bool(is_tight),
        is_late_stage=bool(is_late),
    )


def build_snapshot(
    rows: list[RadarRow],
    *,
    timeframe: str = "1d",
    as_of: Optional[str] = None,
) -> RadarSnapshot:
    as_of = as_of or datetime.now(timezone.utc).isoformat()
    green = [r for r in rows if r.color == "GREEN"]
    grey = [r for r in rows if r.color == "GREY"]
    red = [r for r in rows if r.color == "RED"]

    def _sort_fresh(rs: list[RadarRow]) -> list[dict[str, Any]]:
        return [
            r.as_dict() for r in sorted(rs, key=lambda x: (x.days_in_state, -abs(x.pct_since_flip)))
        ]

    fresh_g = _sort_fresh([r for r in green if r.is_fresh_flip])
    fresh_r = _sort_fresh([r for r in red if r.is_fresh_flip])
    coils = [
        r.as_dict()
        for r in sorted(
            [r for r in rows if r.is_tight_coil],
            key=lambda x: (x.coil_width_pct if x.coil_width_pct is not None else 999.0),
        )
    ]
    brks = [
        r.as_dict()
        for r in sorted(
            [r for r in rows if r.breakout],
            key=lambda x: x.symbol,
        )
    ]
    late = _sort_fresh([r for r in green if r.is_late_stage])

    return RadarSnapshot(
        as_of=as_of,
        timeframe=timeframe,
        count=len(rows),
        green=len(green),
        grey=len(grey),
        red=len(red),
        fresh_green=fresh_g,
        fresh_red=fresh_r,
        tight_coils=coils,
        breakouts=brks,
        late_stage_green=late,
        rows=[r.as_dict() for r in sorted(rows, key=lambda x: x.symbol)],
    )


def format_radar_digest(snap: RadarSnapshot, *, max_items: int = 8) -> str:
    """Plain-text digest for Discord/Telegram (manual-only; no orders)."""
    lines = [
        f"**QMIE Trend Radar** ({snap.timeframe}) · {snap.as_of[:19]}Z",
        f"Universe {snap.count}: 🟢{snap.green}  ⚪{snap.grey}  🔴{snap.red}",
        "_Signal only — manual entry. No orders._",
    ]

    def _fmt_row(r: dict[str, Any]) -> str:
        pct = r.get("pct_since_flip")
        days = r.get("days_in_state")
        return f"`{r['symbol']}` d{days} {pct:+.1f}%"

    if snap.fresh_green:
        items = ", ".join(_fmt_row(r) for r in snap.fresh_green[:max_items])
        lines.append(f"**Fresh GREEN flips:** {items}")
    if snap.fresh_red:
        items = ", ".join(_fmt_row(r) for r in snap.fresh_red[:max_items])
        lines.append(f"**Fresh RED flips:** {items}")
    if snap.breakouts:
        items = ", ".join(
            f"`{r['symbol']}` {r['breakout']}" for r in snap.breakouts[:max_items]
        )
        lines.append(f"**Breakouts:** {items}")
    if snap.tight_coils:
        items = ", ".join(
            f"`{r['symbol']}` {r['coil_width_pct']:.1f}%"
            for r in snap.tight_coils[:max_items]
            if r.get("coil_width_pct") is not None
        )
        lines.append(f"**Tight coils:** {items}")
    if snap.late_stage_green:
        items = ", ".join(_fmt_row(r) for r in snap.late_stage_green[:max_items])
        lines.append(f"**Late-stage GREEN (caution):** {items}")

    return "\n".join(lines)
