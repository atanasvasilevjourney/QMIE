"""Carver as a *sizer* on frozen TEMA entries. Research only. No orders.

TEMA is event-driven (one isolated 10× ticket, SL/TP). Carver is a
continuous daily (or 4h) weight. Honest overlay:

* Same frozen 9/90/199 trade list. Carver does **not** retune periods.
* Size at ``entry_time`` uses Carver **held** (weight lagged once).
* Isolated cap is reapplied to the scaled stake.
* Scale reference is fit on **IS entries only** so average OOS size is
  comparable to binary TEMA — otherwise a 12% mean weight silently
  shrinks DD and looks like "control".

Modes
-----
``daily``     Carver on UTC daily last 4h close; ffill onto 4h bars.
``bar``       Carver on the 4h close itself (``ann_days=365*6``).
``inv_vol``   Inverse-vol only (forecast pinned at +10). Tests whether
              the *forecast* adds anything vs vol targeting.

Hypothesis from BTC-only Carver: sizing may tighten DD; forecast timing
likely does not add OOS edge vs binary TEMA.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .carver import FC_TARGET, VOL_TARGET, full_carver, position_from_forecast, vol_stack
from .protocol import ANN_DAYS
from .tema_system import ANN_4H, BARS_PER_DAY_4H, rescale_trades


def daily_last_close(ohlcv: pd.DataFrame) -> pd.Series:
    """Last 4h close of each UTC day, indexed at that bar's timestamp (no midnight leak)."""
    if ohlcv.empty:
        return pd.Series(dtype=float, name="close")
    return ohlcv.groupby(ohlcv.index.normalize()).tail(1)["close"].rename("close")


def _ffill_to_bars(daily: pd.Series, bar_index: pd.DatetimeIndex) -> pd.Series:
    s = daily.sort_index().reindex(bar_index.union(daily.index)).sort_index().ffill()
    return s.reindex(bar_index).fillna(0.0)


def carver_held_daily(
    ohlcv: pd.DataFrame,
    *,
    vol_target: float = VOL_TARGET,
    exec_lag: int = 1,
) -> tuple[pd.Series, pd.Series, float]:
    """Daily Carver weight, lagged, then ffilled onto the 4h index.

    The daily close at day T is only visible on bars *after* that day's last
    4h print. ``exec_lag=1`` then waits one more daily step.
    """
    daily = daily_last_close(ohlcv)
    if len(daily) < 80:
        z = pd.Series(0.0, index=ohlcv.index, name="held")
        return z, z.rename("fc"), 1.0
    panel = daily.to_frame("x")
    w, fc, fdm = full_carver(panel, "x", use_cs=False, vol_target=vol_target, ann_days=ANN_DAYS)
    held = w.shift(exec_lag).fillna(0.0).rename("held")
    return _ffill_to_bars(held, ohlcv.index).rename("held"), _ffill_to_bars(fc, ohlcv.index).rename("fc"), fdm


def carver_held_4h(
    ohlcv: pd.DataFrame,
    *,
    vol_target: float = VOL_TARGET,
    exec_lag: int = 1,
) -> tuple[pd.Series, pd.Series, float]:
    """Same-timescale Carver on 4h bars. EWMAC spans are *bars*, not days."""
    close = ohlcv["close"].dropna()
    if len(close) < 80:
        z = pd.Series(0.0, index=ohlcv.index, name="held")
        return z, z.rename("fc"), 1.0
    panel = close.to_frame("x")
    w, fc, fdm = full_carver(panel, "x", use_cs=False, vol_target=vol_target, ann_days=ANN_4H)
    held = w.shift(exec_lag).reindex(ohlcv.index).fillna(0.0).rename("held")
    return held, fc.reindex(ohlcv.index).fillna(0.0).rename("fc"), fdm


def inv_vol_held(
    ohlcv: pd.DataFrame,
    *,
    vol_target: float = VOL_TARGET,
    exec_lag: int = 1,
    bar: bool = False,
) -> pd.Series:
    """Always-long vol target (forecast = +10). Lagged."""
    if bar:
        close = ohlcv["close"]
        vs = vol_stack(close, ann_days=ANN_4H)
        w = position_from_forecast(pd.Series(FC_TARGET, index=close.index), vs["vol"], vol_target=vol_target)
        return w.shift(exec_lag).reindex(ohlcv.index).fillna(0.0).rename("held")
    daily = daily_last_close(ohlcv)
    vs = vol_stack(daily, ann_days=ANN_DAYS)
    w = position_from_forecast(pd.Series(FC_TARGET, index=daily.index), vs["vol"], vol_target=vol_target)
    held = w.shift(exec_lag).fillna(0.0)
    return _ffill_to_bars(held, ohlcv.index).rename("held")


def is_scale_ref(held: pd.Series, entry_times: pd.Series | pd.Index, *, floor: float = 0.05) -> float:
    """Mean lagged weight at IS entries. Keeps OOS average size ≈ binary stake."""
    if isinstance(entry_times, pd.Series):
        times = pd.DatetimeIndex(entry_times)
    else:
        times = pd.DatetimeIndex(entry_times)
    if len(times) == 0:
        return 1.0
    vals = []
    h = held.sort_index()
    for ts in times:
        v = h.asof(ts)
        if v is not None and np.isfinite(v) and not pd.isna(v):
            vals.append(float(v))
    if not vals:
        return 1.0
    mu = float(np.mean(vals))
    return max(mu, floor)


def sized_trades(
    trades: pd.DataFrame,
    held: pd.Series,
    *,
    base_stake: float,
    leverage: float,
    cost_bps: float,
    ref: float,
    min_scale: float = 0.0,
    max_scale: float = 2.5,
) -> pd.DataFrame:
    """``stake = base_stake * clip(held / ref, min, max)`` at entry."""
    if ref <= 0:
        ref = 1.0
    scale = (held / ref).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return rescale_trades(
        trades, scale, base_stake=base_stake, leverage=leverage, cost_bps=cost_bps,
        min_scale=min_scale, max_scale=max_scale,
    )


def filter_trades(trades: pd.DataFrame, held: pd.Series, *, min_held: float) -> pd.DataFrame:
    """Drop entries whose lagged Carver weight is below ``min_held``. Changes the list."""
    if trades.empty:
        return trades.copy()
    keep = []
    h = held.sort_index()
    for ts in trades["entry_time"]:
        v = h.asof(ts)
        keep.append(bool(v is not None and np.isfinite(v) and float(v) >= min_held))
    return trades.loc[np.asarray(keep)].reset_index(drop=True)


def overlay_pack(
    ohlcv: pd.DataFrame,
    trades: pd.DataFrame,
    is_entry_times: pd.Series | pd.Index,
    *,
    base_stake: float,
    leverage: float,
    cost_bps: float,
    vol_target: float = VOL_TARGET,
) -> dict[str, Any]:
    """Binary + daily-Carver size + 4h-Carver size + inv-vol + Carver filter."""
    held_d, fc_d, fdm_d = carver_held_daily(ohlcv, vol_target=vol_target)
    held_b, fc_b, fdm_b = carver_held_4h(ohlcv, vol_target=vol_target)
    held_v = inv_vol_held(ohlcv, vol_target=vol_target, bar=False)
    ref_d = is_scale_ref(held_d, is_entry_times)
    ref_b = is_scale_ref(held_b, is_entry_times)
    ref_v = is_scale_ref(held_v, is_entry_times)
    binary = rescale_trades(trades, 1.0, base_stake=base_stake, leverage=leverage, cost_bps=cost_bps)
    return {
        "binary": binary,
        "carver_daily": sized_trades(
            trades, held_d, base_stake=base_stake, leverage=leverage, cost_bps=cost_bps, ref=ref_d,
        ),
        "carver_4h": sized_trades(
            trades, held_b, base_stake=base_stake, leverage=leverage, cost_bps=cost_bps, ref=ref_b,
        ),
        "inv_vol": sized_trades(
            trades, held_v, base_stake=base_stake, leverage=leverage, cost_bps=cost_bps, ref=ref_v,
        ),
        "carver_filter": filter_trades(trades, held_d, min_held=0.05),
        "held_daily": held_d,
        "held_4h": held_b,
        "fc_daily": fc_d,
        "refs": {"daily": ref_d, "bar": ref_b, "inv_vol": ref_v},
        "fdm": {"daily": fdm_d, "bar": fdm_b},
        "bars_per_day": BARS_PER_DAY_4H,
    }
