"""Donchian trend system with SUPER_TRADEMAN-inspired validation hooks.

Research only — does not dispatch QMIE alerts or retune ``W_*``.

Enhancements borrowed from SUPER_TRADEMAN (ideas, not a code import):
  * prior-window Donchian entry (long + short)
  * trailing ATR stop as the primary exit
  * pessimistic bar replay (gap-through-stop, stop-before-target ambiguity)
  * long/short attribution and Wilson win-rate CI vs breakeven
  * optional QMIE-style tight-coil gate (prior-box width <= pct)

Fills enter on the bar **after** the signal close (``signal.shift(1)`` discipline).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

import numpy as np
import pandas as pd

from scanner.indicators import atr as wilder_atr

from .features import donchian


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class DonchianStmParams:
    entry_lookback: int = 55
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    trail_atr_mult: float | None = 2.0
    max_hold_bars: int = 120
    slippage_pct: float = 0.001
    commission_pct: float = 0.001
    mode: Literal["turtle", "qmie_coil"] = "turtle"
    coil_max_width_pct: float = 15.0
    min_excursion_atr: float = 0.0  # require close beyond channel by N x ATR (0 = any break)


@dataclass
class StmTrade:
    side: Side
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_fill: float
    exit_fill: float
    initial_stop: float
    exit_reason: str
    r_multiple: float
    net_pnl_pct: float
    bars_held: int
    confidence: float


def _apply_slippage(price: float, side: Side, *, entering: bool, slip: float) -> float:
    is_buy = (side is Side.LONG) == entering
    return price * (1 + slip) if is_buy else price * (1 - slip)


def _commission(notional: float, commission_pct: float) -> float:
    return abs(notional) * commission_pct


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return float("nan"), float("nan")
    p = wins / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)
    low = (centre - margin) / denom
    high = (centre + margin) / denom
    return float(low), float(high)


def breakeven_win_rate(r_multiples: np.ndarray) -> float:
    """Win rate needed for zero expectancy given realized R payoffs."""
    wins = r_multiples[r_multiples > 0]
    losses = r_multiples[r_multiples <= 0]
    if len(wins) == 0 or len(losses) == 0:
        return float("nan")
    avg_win = float(wins.mean())
    avg_loss = float(abs(losses.mean()))
    if avg_win + avg_loss == 0:
        return float("nan")
    return avg_loss / (avg_win + avg_loss)


def donchian_signals(df: pd.DataFrame, p: DonchianStmParams) -> pd.DataFrame:
    """Bar-close breakout signals. Prior-window channel via ``features.donchian``."""
    don = donchian(df, p.entry_lookback)
    atr_s = wilder_atr(df, p.atr_period)
    c = df["close"]
    width_pct = don["coil_width"] * 100.0
    long_break = c > don["donch_high"]
    short_break = c < don["donch_low"]
    if p.mode == "qmie_coil":
        coil_ok = width_pct <= p.coil_max_width_pct
        long_break = long_break & coil_ok
        short_break = short_break & coil_ok
    excursion = np.where(
        long_break,
        (c - don["donch_high"]) / atr_s.replace(0, np.nan),
        np.where(short_break, (don["donch_low"] - c) / atr_s.replace(0, np.nan), 0.0),
    )
    excursion = pd.Series(excursion, index=df.index).fillna(0.0)
    if p.min_excursion_atr > 0:
        long_break = long_break & (excursion >= p.min_excursion_atr)
        short_break = short_break & (excursion >= p.min_excursion_atr)
    conf = excursion.clip(0, 1.0)
    sig = pd.Series(0, index=df.index, dtype=int)
    sig = sig.mask(long_break, 1).mask(short_break, -1)
    return pd.DataFrame(
        {
            "close": c,
            "donch_high": don["donch_high"],
            "donch_low": don["donch_low"],
            "coil_width_pct": width_pct,
            "atr": atr_s,
            "signal": sig,
            "confidence": conf,
        },
        index=df.index,
    )


def backtest_donchian_stm(df: pd.DataFrame, p: DonchianStmParams) -> tuple[pd.DataFrame, list[StmTrade]]:
    """Single-position replay with pessimistic intrabar rules."""
    if df.empty:
        return pd.DataFrame(), []
    sig_fr = donchian_signals(df, p)
    atr_s = sig_fr["atr"]
    net = pd.Series(0.0, index=df.index)
    mtm = pd.Series(0.0, index=df.index)
    trades: list[StmTrade] = []

    pos_side: Side | None = None
    entry_fill = 0.0
    initial_stop = 0.0
    stop = 0.0
    entry_i = -1
    entry_conf = 0.0
    entry_time: pd.Timestamp | None = None

    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)

    for i in range(1, len(df)):
        ts = df.index[i]
        if pos_side is None:
            raw = int(sig_fr["signal"].iloc[i - 1])
            if raw == 0:
                continue
            side = Side.LONG if raw > 0 else Side.SHORT
            atr_entry = float(atr_s.iloc[i - 1])
            if not np.isfinite(atr_entry) or atr_entry <= 0:
                continue
            entry_fill = _apply_slippage(float(o.iloc[i]), side, entering=True, slip=p.slippage_pct)
            entry_conf = float(sig_fr["confidence"].iloc[i - 1])
            if side is Side.LONG:
                initial_stop = entry_fill - p.atr_stop_mult * atr_entry
                stop = initial_stop
            else:
                initial_stop = entry_fill + p.atr_stop_mult * atr_entry
                stop = initial_stop
            pos_side = side
            entry_i = i
            entry_time = ts
            risk = abs(entry_fill - initial_stop)
            if risk <= 0:
                pos_side = None
            continue

        # mark-to-market daily return component
        prev_c = float(c.iloc[i - 1])
        cur_c = float(c.iloc[i])
        if pos_side is Side.LONG:
            mtm.iloc[i] = (cur_c - prev_c) / prev_c
        else:
            mtm.iloc[i] = (prev_c - cur_c) / prev_c

        atr_i = float(atr_s.iloc[i]) if np.isfinite(atr_s.iloc[i]) else float(atr_s.iloc[i - 1])
        if p.trail_atr_mult is not None and np.isfinite(atr_i) and atr_i > 0:
            if pos_side is Side.LONG:
                stop = max(stop, cur_c - p.trail_atr_mult * atr_i)
            else:
                stop = min(stop, cur_c + p.trail_atr_mult * atr_i)

        exit_fill: float | None = None
        reason = ""
        open_i = float(o.iloc[i])
        high_i = float(h.iloc[i])
        low_i = float(l.iloc[i])

        if pos_side is Side.LONG:
            if open_i < stop:
                exit_fill = _apply_slippage(open_i, Side.LONG, entering=False, slip=p.slippage_pct)
                reason = "gap_stop"
            elif low_i <= stop:
                exit_fill = _apply_slippage(stop, Side.LONG, entering=False, slip=p.slippage_pct)
                reason = "stop"
        else:
            if open_i > stop:
                exit_fill = _apply_slippage(open_i, Side.SHORT, entering=False, slip=p.slippage_pct)
                reason = "gap_stop"
            elif high_i >= stop:
                exit_fill = _apply_slippage(stop, Side.SHORT, entering=False, slip=p.slippage_pct)
                reason = "stop"

        if exit_fill is None and (i - entry_i) >= p.max_hold_bars:
            exit_fill = _apply_slippage(cur_c, pos_side, entering=False, slip=p.slippage_pct)
            reason = "time"

        if exit_fill is None:
            continue

        risk = abs(entry_fill - initial_stop)
        if pos_side is Side.LONG:
            gross = (exit_fill - entry_fill) / entry_fill
            r_mult = (exit_fill - entry_fill) / risk if risk > 0 else 0.0
        else:
            gross = (entry_fill - exit_fill) / entry_fill
            r_mult = (entry_fill - exit_fill) / risk if risk > 0 else 0.0
        comm = _commission(entry_fill, p.commission_pct) + _commission(exit_fill, p.commission_pct)
        net_pnl = gross - comm / max(entry_fill, 1e-12)
        net.iloc[i] = net_pnl
        trades.append(
            StmTrade(
                side=pos_side,
                entry_time=entry_time or ts,
                exit_time=ts,
                entry_fill=entry_fill,
                exit_fill=exit_fill,
                initial_stop=initial_stop,
                exit_reason=reason,
                r_multiple=float(r_mult),
                net_pnl_pct=float(net_pnl),
                bars_held=i - entry_i,
                confidence=entry_conf,
            )
        )
        pos_side = None

    out = sig_fr.copy()
    out["mtm"] = mtm
    out["trade_net"] = net
    out["held"] = (mtm != 0).astype(float)  # approximate exposure flag
    return out, trades


def net_series_from_trades(trades: list[StmTrade], index: pd.DatetimeIndex) -> pd.Series:
    """Daily net returns: P&L booked on exit bar (sparse)."""
    net = pd.Series(0.0, index=index)
    for t in trades:
        if t.exit_time in net.index:
            net.loc[t.exit_time] += t.net_pnl_pct
        else:
            # nearest index at or after exit
            pos = net.index.searchsorted(t.exit_time)
            if pos < len(net.index):
                net.iloc[pos] += t.net_pnl_pct
    return net


def trade_attribution(trades: list[StmTrade]) -> dict[str, Any]:
    if not trades:
        return {"n": 0, "long": {}, "short": {}, "all": {}}

    def _book(sub: list[StmTrade]) -> dict[str, float]:
        if not sub:
            return {"n": 0}
        rs = np.array([t.r_multiple for t in sub])
        wins = int((rs > 0).sum())
        n = len(sub)
        wl, wh = wilson_ci(wins, n)
        be = breakeven_win_rate(rs)
        return {
            "n": n,
            "win_rate": wins / n,
            "avg_r": float(rs.mean()),
            "total_r": float(rs.sum()),
            "wilson_lo": wl,
            "wilson_hi": wh,
            "breakeven_win_rate": be,
        }

    longs = [t for t in trades if t.side is Side.LONG]
    shorts = [t for t in trades if t.side is Side.SHORT]
    return {
        "n": len(trades),
        "long": _book(longs),
        "short": _book(shorts),
        "all": _book(trades),
    }


def trades_in_window(
    trades: list[StmTrade],
    start: pd.Timestamp,
    end: pd.Timestamp | None = None,
) -> list[StmTrade]:
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    out = []
    for t in trades:
        et = t.entry_time
        if et.tzinfo is None:
            et = et.tz_localize("UTC")
        if et < start:
            continue
        if end is not None:
            e = end if end.tzinfo else end.tz_localize("UTC")
            if et > e:
                continue
        out.append(t)
    return out


def eval_donchian_stm(full: pd.DataFrame, p: DonchianStmParams, *, warmup: int) -> dict[str, Any]:
    from .metrics import kpis
    from .protocol import SPLIT, split_frame

    parts = split_frame(full, warmup=warmup)
    is_fr, is_trades = backtest_donchian_stm(parts["is"], p)
    oos_fr, oos_trades = backtest_donchian_stm(parts["oos_seeded"], p)
    oos_start = pd.Timestamp(SPLIT.oos_start, tz="UTC")
    is_cut = parts["is"].index[min(warmup, len(parts["is"]) - 1)]
    is_tr = trades_in_window(is_trades, is_cut)
    oos_tr = trades_in_window(oos_trades, oos_start)

    is_ix = parts["is"].index[warmup:]
    is_net = net_series_from_trades(is_tr, is_ix)
    is_eq = (1.0 + is_net).cumprod()
    oos_only = oos_fr.reindex(parts["oos"].index)
    oos_net = net_series_from_trades(oos_tr, parts["oos"].index)
    oos_eq = (1.0 + oos_net).cumprod()

    return {
        "params": {**p.__dict__},
        "is": kpis(is_net, is_eq, trades=len(is_tr)),
        "oos": kpis(oos_net, oos_eq, trades=len(oos_tr)),
        "is_attribution": trade_attribution(is_tr),
        "oos_attribution": trade_attribution(oos_tr),
        "is_trades": is_tr,
        "oos_trades": oos_tr,
        "oos_frame": oos_only,
    }


def trail_sweep(
    full: pd.DataFrame,
    *,
    base: DonchianStmParams,
    trail_mults: tuple[float | None, ...] = (None, 1.5, 2.0, 2.5, 3.0),
    warmup: int,
) -> pd.DataFrame:
    rows = []
    for mult in trail_mults:
        p = DonchianStmParams(**{**base.__dict__, "trail_atr_mult": mult})
        ev = eval_donchian_stm(full, p, warmup=warmup)
        att = ev["oos_attribution"]["all"]
        rows.append(
            {
                "trail_atr_mult": mult,
                "oos_sharpe": ev["oos"]["sharpe"],
                "oos_max_dd": ev["oos"]["max_dd"],
                "oos_trades": att.get("n", 0),
                "oos_avg_r": att.get("avg_r", float("nan")),
                "long_total_r": ev["oos_attribution"]["long"].get("total_r", float("nan")),
                "short_total_r": ev["oos_attribution"]["short"].get("total_r", float("nan")),
            }
        )
    return pd.DataFrame(rows)
