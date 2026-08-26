"""
QMIE — Daily Trend Radar (RGG + coil breakouts)
===============================================
Signal-only market map on **daily** candles. Inspired by Signum-style
Trend Radar, implemented with QMIE's Pine-compatible ADX/DMI.

Does **not** place orders. Does **not** retune W_* scoring weights.
Optional Discord/Telegram digest only — this is **unranked daily
context**, not a QMIE A/A+ entry signal.

RGG (Red / Grey / Green):
  * GREEN — ADX strong and +DI > −DI (uptrend)
  * RED   — ADX strong and −DI > +DI (downtrend)
  * GREY  — ADX weak / consolidating (coil / chop)

Hysteresis avoids daily color flicker:
  leave GREY only when ADX >= enter_adx;
  enter GREY from a trend only when ADX < exit_adx.

Coil / breakout (Signum-style):
  Width = (high-low)/low * 100 over lookback closed bars.
  Tight coil arms only while GREY and width <= coil_max_width_pct.
  Breakout = close outside the prior GREY tight-coil range (one-shot).
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
    exit_adx: float = 20.0        # trend → GREY (Signum-style band [20, 25))
    coil_lookback: int = 20
    coil_max_width_pct: float = 15.0
    fresh_flip_days: int = 3
    late_stage_days: int = 30
    late_stage_move_pct: float = 50.0
    kline_limit: int = 250
    min_bars: int = 60            # need enough history for ADX + coil
    notify: bool = False          # opt-in digests (data still collected)
    min_coverage_pct: float = 50.0  # suppress notify below this success rate

    def validate(self) -> None:
        """Fail-fast for bad knobs (raises ValueError)."""
        if self.adx_length <= 0:
            raise ValueError("radar adx_length must be > 0")
        if not np.isfinite(self.enter_adx) or not np.isfinite(self.exit_adx):
            raise ValueError("radar enter/exit ADX must be finite")
        if self.exit_adx > self.enter_adx:
            raise ValueError("radar exit_adx must be <= enter_adx")
        if self.coil_lookback <= 1:
            raise ValueError("radar coil_lookback must be > 1")
        if self.coil_max_width_pct <= 0:
            raise ValueError("radar coil_max_width_pct must be > 0")
        if self.fresh_flip_days < 1:
            raise ValueError("radar fresh_flip_days must be >= 1")
        if self.late_stage_days < 1:
            raise ValueError("radar late_stage_days must be >= 1")
        # Clients drop the live candle → need lookback+1 closed bars + ADX warm-up headroom
        min_limit = max(self.min_bars, self.coil_lookback + 2, self.adx_length * 2 + 5)
        if self.kline_limit < min_limit:
            raise ValueError(
                f"radar kline_limit={self.kline_limit} too small; need >= {min_limit}"
            )


@dataclass
class RadarRow:
    symbol: str
    color: Color
    days_in_state: int
    state_censored: bool          # True if state likely predates the window
    flipped_at: Optional[str]
    pct_since_flip: Optional[float]
    price: float
    bar_time: Optional[str]       # closed daily bar timestamp
    adx: float
    plus_di: float
    minus_di: float
    coil_width_pct: Optional[float]
    coil_high: Optional[float]
    coil_low: Optional[float]
    breakout: Optional[Breakout]
    breakout_level: Optional[float]
    breakout_excess_pct: Optional[float]
    is_fresh_flip: bool
    is_tight_coil: bool
    is_late_stage: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RadarSnapshot:
    as_of: Optional[str]          # closed-through date (candle), not wall clock
    timeframe: str
    status: str                   # ready | incomplete | empty
    count: int                    # classified symbols
    requested: int
    succeeded: int
    failed: int
    green: int
    grey: int
    red: int
    fresh_green: list[dict[str, Any]] = field(default_factory=list)
    fresh_red: list[dict[str, Any]] = field(default_factory=list)
    tight_coils: list[dict[str, Any]] = field(default_factory=list)
    breakouts: list[dict[str, Any]] = field(default_factory=list)
    late_stage_green: list[dict[str, Any]] = field(default_factory=list)
    late_stage_red: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    failed_symbols: list[str] = field(default_factory=list)
    note: Optional[str] = None
    enabled: bool = True
    has_actionable: bool = False  # flips / coils / breakouts / late-stage

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _raw_color(adx_v: float, pdi: float, mdi: float, *, grey_adx: float) -> Color:
    """Instantaneous color without hysteresis."""
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
    exit_adx: float = 20.0,
) -> pd.Series:
    """
    Walk ADX/DMI bar-by-bar applying hysteresis.

    Unknown / weak history seeds as GREY (conservative). Leave GREY only
    when ADX >= enter_adx with a clear DI side. Re-enter GREY when
    ADX < exit_adx.
    """
    if exit_adx > enter_adx:
        raise ValueError("exit_adx must be <= enter_adx")

    n = len(adx_s)
    out: list[str] = ["GREY"] * n
    state: Color = "GREY"

    for i in range(n):
        a = float(adx_s.iloc[i])
        p = float(plus_di.iloc[i])
        m = float(minus_di.iloc[i])
        if not np.isfinite(a):
            out[i] = state
            continue

        if state == "GREY":
            if a >= enter_adx:
                if p > m:
                    state = "GREEN"
                elif m > p:
                    state = "RED"
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
    """Return (width_pct, high, low). Width = (hi-lo)/lo * 100 (raw, unrounded)."""
    if len(df) < lookback:
        return None, None, None
    window = df.iloc[-lookback:]
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    if lo <= 0 or not np.isfinite(lo):
        return None, hi, lo
    width = (hi - lo) / lo * 100.0
    return width, hi, lo


def _detect_breakout(
    df: pd.DataFrame,
    colors: pd.Series,
    *,
    lookback: int,
    coil_max_width_pct: float,
) -> tuple[Optional[Breakout], Optional[float], Optional[float]]:
    """
    One-shot breakout: prior lookback window was a GREY tight coil, and
    today's close is outside that prior range.
    Returns (side, broken_level, excess_pct).
    """
    if len(df) < lookback + 1 or len(colors) < lookback + 1:
        return None, None, None
    prior = df.iloc[-(lookback + 1):-1]
    prior_colors = colors.iloc[-(lookback + 1):-1]
    # Require the bar immediately before the breakout to be GREY (armed coil)
    if str(prior_colors.iloc[-1]) != "GREY":
        return None, None, None
    hi = float(prior["high"].max())
    lo = float(prior["low"].min())
    if lo <= 0:
        return None, None, None
    width = (hi - lo) / lo * 100.0
    if width > coil_max_width_pct:
        return None, None, None
    close = float(df["close"].iloc[-1])
    if close > hi:
        excess = (close - hi) / hi * 100.0 if hi > 0 else 0.0
        return "UP", hi, round(excess, 3)
    if close < lo:
        excess = (lo - close) / lo * 100.0 if lo > 0 else 0.0
        return "DOWN", lo, round(excess, 3)
    return None, None, None


def classify_symbol(
    df: pd.DataFrame,
    symbol: str,
    *,
    cfg: Optional[RadarConfig] = None,
) -> Optional[RadarRow]:
    """Classify one symbol's daily OHLCV into a RadarRow. None if too short."""
    cfg = cfg or RadarConfig()
    cfg.validate()
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
    state_censored = flip_idx == 0  # state may predate the fetched window
    flipped_at: Optional[str] = None
    pct_since: Optional[float] = None
    price = float(df["close"].iloc[-1])
    if not state_censored:
        flipped_at = pd.Timestamp(df.index[flip_idx]).isoformat()
        entry = float(df["close"].iloc[flip_idx])
        if entry > 0:
            pct_since = round((price - entry) / entry * 100.0, 2)

    width, coil_hi, coil_lo = _coil_metrics(df, lookback=cfg.coil_lookback)
    brk, brk_level, brk_excess = _detect_breakout(
        df, colors,
        lookback=cfg.coil_lookback,
        coil_max_width_pct=cfg.coil_max_width_pct,
    )
    # Coil watchlist: GREY + tight only (and not already broken out today)
    is_tight = (
        color == "GREY"
        and brk is None
        and width is not None
        and width <= cfg.coil_max_width_pct
    )
    is_fresh = (
        (not state_censored)
        and days <= cfg.fresh_flip_days
        and color in ("GREEN", "RED")
    )
    # Late-stage: directional extension only (not abs)
    is_late = False
    if (
        not state_censored
        and pct_since is not None
        and days >= cfg.late_stage_days
    ):
        if color == "GREEN" and pct_since >= cfg.late_stage_move_pct:
            is_late = True
        elif color == "RED" and pct_since <= -cfg.late_stage_move_pct:
            is_late = True

    bar_time = pd.Timestamp(df.index[-1]).isoformat()
    width_out = round(width, 3) if width is not None else None

    return RadarRow(
        symbol=symbol.upper(),
        color=color,  # type: ignore[arg-type]
        days_in_state=days,
        state_censored=state_censored,
        flipped_at=flipped_at,
        pct_since_flip=pct_since,
        price=price,
        bar_time=bar_time,
        adx=round(float(adx_s.iloc[-1]), 2),
        plus_di=round(float(plus_di.iloc[-1]), 2),
        minus_di=round(float(minus_di.iloc[-1]), 2),
        coil_width_pct=width_out,
        coil_high=coil_hi,
        coil_low=coil_lo,
        breakout=brk,
        breakout_level=brk_level,
        breakout_excess_pct=brk_excess,
        is_fresh_flip=is_fresh,
        is_tight_coil=bool(is_tight),
        is_late_stage=bool(is_late),
    )


def build_snapshot(
    rows: list[RadarRow],
    *,
    timeframe: str = "1d",
    requested: int = 0,
    failed_symbols: Optional[list[str]] = None,
    enabled: bool = True,
) -> RadarSnapshot:
    failed_symbols = failed_symbols or []
    requested = requested or (len(rows) + len(failed_symbols))
    succeeded = len(rows)
    failed = len(failed_symbols)

    # Closed-through = latest bar_time among rows (not wall clock)
    as_of: Optional[str] = None
    if rows:
        times = [r.bar_time for r in rows if r.bar_time]
        as_of = max(times) if times else None

    green = [r for r in rows if r.color == "GREEN"]
    grey = [r for r in rows if r.color == "GREY"]
    red = [r for r in rows if r.color == "RED"]

    def _sort_fresh(rs: list[RadarRow]) -> list[dict[str, Any]]:
        return [
            r.as_dict()
            for r in sorted(
                rs,
                key=lambda x: (
                    x.days_in_state,
                    -(abs(x.pct_since_flip) if x.pct_since_flip is not None else 0.0),
                ),
            )
        ]

    fresh_g = _sort_fresh([r for r in green if r.is_fresh_flip])
    fresh_r = _sort_fresh([r for r in red if r.is_fresh_flip])
    # Coils and breakouts are mutually exclusive by construction
    coils = [
        r.as_dict()
        for r in sorted(
            [r for r in rows if r.is_tight_coil],
            key=lambda x: (x.coil_width_pct if x.coil_width_pct is not None else 999.0),
        )
    ]
    brks = [
        r.as_dict()
        for r in sorted([r for r in rows if r.breakout], key=lambda x: x.symbol)
    ]
    late_g = _sort_fresh([r for r in green if r.is_late_stage])
    late_r = _sort_fresh([r for r in red if r.is_late_stage])

    has_actionable = bool(fresh_g or fresh_r or coils or brks or late_g or late_r)

    if succeeded == 0:
        status = "empty"
        note = "no_symbols_classified"
    elif failed > 0:
        status = "incomplete"
        note = f"partial_coverage:{succeeded}/{requested}"
    else:
        status = "ready"
        note = None

    return RadarSnapshot(
        as_of=as_of,
        timeframe=timeframe,
        status=status,
        count=succeeded,
        requested=requested,
        succeeded=succeeded,
        failed=failed,
        green=len(green),
        grey=len(grey),
        red=len(red),
        fresh_green=fresh_g,
        fresh_red=fresh_r,
        tight_coils=coils,
        breakouts=brks,
        late_stage_green=late_g,
        late_stage_red=late_r,
        rows=[r.as_dict() for r in sorted(rows, key=lambda x: x.symbol)],
        failed_symbols=sorted(failed_symbols),
        note=note,
        enabled=enabled,
        has_actionable=has_actionable,
    )


def empty_radar_snapshot(*, enabled: bool = True, note: str = "no_radar_yet") -> RadarSnapshot:
    """Stable empty response shape for GET /radar before the first pass."""
    return RadarSnapshot(
        as_of=None,
        timeframe="1d",
        status="empty",
        count=0,
        requested=0,
        succeeded=0,
        failed=0,
        green=0,
        grey=0,
        red=0,
        note=note,
        enabled=enabled,
        has_actionable=False,
    )


def format_radar_digest(snap: RadarSnapshot, *, max_items: int = 8) -> str:
    """Plain-text digest for Discord/Telegram — unranked context only."""
    closed = (snap.as_of or "?")[:10]
    cov = f"{snap.succeeded}/{snap.requested}" if snap.requested else str(snap.count)
    lines = [
        f"**QMIE Trend Radar — UNRANKED DAILY CONTEXT** (1D closed through {closed})",
        f"Coverage {cov}: 🟢{snap.green}  ⚪{snap.grey}  🔴{snap.red}",
        "_NOT an entry · NOT a QMIE A/A+ grade · MANUAL ONLY · NO ORDER PATH_",
        "_Wait for a separate ranked A/A+ alert before acting._",
    ]
    if snap.status == "incomplete":
        lines.insert(1, f"⚠️ INCOMPLETE DATA ({cov} classified)")

    def _fmt_flip(r: dict[str, Any]) -> str:
        pct = r.get("pct_since_flip")
        days = r.get("days_in_state")
        pct_s = f"{pct:+.1f}%" if pct is not None else "n/a"
        cens = "†" if r.get("state_censored") else ""
        return f"`{r['symbol']}` d{days}{cens} {pct_s}"

    def _cap(label: str, items: list[str], total: int) -> None:
        if not items:
            return
        shown = ", ".join(items)
        extra = f" (+{total - len(items)} via /radar)" if total > len(items) else ""
        lines.append(f"**{label}:** {shown}{extra}")

    if snap.fresh_green:
        items = [_fmt_flip(r) for r in snap.fresh_green[:max_items]]
        _cap("Fresh GREEN flips (watch)", items, len(snap.fresh_green))
    if snap.fresh_red:
        items = [_fmt_flip(r) for r in snap.fresh_red[:max_items]]
        _cap("Fresh RED flips (watch)", items, len(snap.fresh_red))
    if snap.breakouts:
        items = []
        for r in snap.breakouts[:max_items]:
            lvl = r.get("breakout_level")
            xs = r.get("breakout_excess_pct")
            adxv = r.get("adx")
            lvl_s = f"{lvl:.4g}" if isinstance(lvl, (int, float)) else "?"
            xs_s = f"{xs:.2f}" if isinstance(xs, (int, float)) else "?"
            items.append(
                f"`{r['symbol']}` {r['breakout']}@{lvl_s} +{xs_s}% "
                f"ADX{adxv} {r.get('color')}"
            )
        _cap("Breakouts (close-confirmed watch)", items, len(snap.breakouts))
    if snap.tight_coils:
        items = [
            f"`{r['symbol']}` {r['coil_width_pct']:.1f}%"
            for r in snap.tight_coils[:max_items]
            if r.get("coil_width_pct") is not None
        ]
        _cap("Tight GREY coils", items, len(snap.tight_coils))
    if snap.late_stage_green:
        items = [_fmt_flip(r) for r in snap.late_stage_green[:max_items]]
        _cap("Extended GREEN (chase risk)", items, len(snap.late_stage_green))
    if snap.late_stage_red:
        items = [_fmt_flip(r) for r in snap.late_stage_red[:max_items]]
        _cap("Extended RED (chase risk)", items, len(snap.late_stage_red))

    return "\n".join(lines)


DAILY_BREAKOUT_STRATEGY = "QMIE-DailyBreakout"


def iter_long_trend_starts(rows: list) -> list[dict[str, Any]]:
    """Closed daily longs: GREY→GREEN today (trend start) and/or coil breakout UP.

    Manual-entry candidates only — not a QMIE A/A+ grade.
    """
    out: list[dict[str, Any]] = []
    for r in rows:
        d = r.as_dict() if hasattr(r, "as_dict") else dict(r)
        reasons: list[str] = []
        days = int(d.get("days_in_state") or 0)
        if (
            d.get("color") == "GREEN"
            and days == 1
            and not d.get("state_censored")
        ):
            reasons.append("trend_start_long")
        if d.get("breakout") == "UP":
            reasons.append("coil_breakout_up")
        if not reasons:
            continue
        d["reason"] = "+".join(reasons)
        d["setup_type"] = "breakout"
        d["side"] = "BUY"
        out.append(d)
    return out


def iter_short_trend_starts(rows: list) -> list[dict[str, Any]]:
    """Closed daily shorts: GREY→RED today (trend start) and/or coil breakout DOWN.

    Manual-entry candidates only — not a QMIE A/A+ grade.
    """
    out: list[dict[str, Any]] = []
    for r in rows:
        d = r.as_dict() if hasattr(r, "as_dict") else dict(r)
        reasons: list[str] = []
        days = int(d.get("days_in_state") or 0)
        if (
            d.get("color") == "RED"
            and days == 1
            and not d.get("state_censored")
        ):
            reasons.append("trend_start_short")
        if d.get("breakout") == "DOWN":
            reasons.append("coil_breakout_down")
        if not reasons:
            continue
        d["reason"] = "+".join(reasons)
        d["setup_type"] = "breakout"
        d["side"] = "SELL"
        out.append(d)
    return out


def iter_trend_starts(rows: list) -> list[dict[str, Any]]:
    """Long and short daily trend-starts (unranked, signal-only)."""
    return iter_long_trend_starts(rows) + iter_short_trend_starts(rows)
