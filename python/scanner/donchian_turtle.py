"""
QMIE — Donchian turtle-style trend module (daily bars)
======================================================
Signal-only math for classic asymmetric channels (e.g. 55-day entry /
20-day exit). Prior-bar channels (``shift(1)``) so today's range is not
inside the breakout level.

Does **not** dispatch alerts or place orders. Use ``backtest.donchian_turtle``
for portfolio simulation and ``research/notebooks/08_*`` for validation.

Not part of TEMA ``W_*`` scoring or Pine ``quant_visualizer.pine``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

STRATEGY_ID = "QMIE-DonchianTurtle"


@dataclass(frozen=True)
class TurtleParams:
    entry_channel: int = 55
    exit_channel: int = 20
    vwap_window: int = 20
    use_vwap_filter: bool = True
    long_only: bool = True


def rolling_vwap(df: pd.DataFrame, window: int) -> pd.Series:
    """Rolling VWAP on typical price × volume (causal)."""
    tp = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3.0
    vol = df["volume"].astype(float).replace(0, np.nan)
    num = (tp * vol).rolling(window, min_periods=window).sum()
    den = vol.rolling(window, min_periods=window).sum()
    return num / den


def donchian_turtle_frame(df: pd.DataFrame, p: TurtleParams | None = None) -> pd.DataFrame:
    """
    Daily Donchian turtle channels + entry/exit flags aligned to ``df.index``.

    Entry long: close > prior ``entry_channel`` high AND (optional) close > VWAP.
    Exit long: close < prior ``exit_channel`` low.
    """
    p = p or TurtleParams()
    if p.entry_channel < 2 or p.exit_channel < 2:
        raise ValueError("channel lengths must be >= 2")
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    entry_hi = high.rolling(p.entry_channel, min_periods=p.entry_channel).max().shift(1)
    entry_lo = low.rolling(p.entry_channel, min_periods=p.entry_channel).min().shift(1)
    exit_hi = high.rolling(p.exit_channel, min_periods=p.exit_channel).max().shift(1)
    exit_lo = low.rolling(p.exit_channel, min_periods=p.exit_channel).min().shift(1)
    vwap = rolling_vwap(df, p.vwap_window) if p.use_vwap_filter else pd.Series(np.nan, index=df.index)
    above_vwap = close > vwap if p.use_vwap_filter else pd.Series(True, index=df.index)
    entry_long = (close > entry_hi) & above_vwap
    exit_long = close < exit_lo
    strength = (close / entry_hi.replace(0, np.nan) - 1.0).clip(lower=0).fillna(0.0)
    out = pd.DataFrame(
        {
            "close": close,
            "entry_high": entry_hi,
            "entry_low": entry_lo,
            "exit_high": exit_hi,
            "exit_low": exit_lo,
            "vwap": vwap,
            "entry_long": entry_long.fillna(False),
            "exit_long": exit_long.fillna(False),
            "strength": strength,
        },
        index=df.index,
    )
    if not p.long_only:
        below_vwap = close < vwap if p.use_vwap_filter else pd.Series(True, index=df.index)
        out["entry_short"] = (close < entry_lo) & below_vwap
        out["exit_short"] = close > exit_hi
    return out


def min_warmup_bars(p: TurtleParams | None = None) -> int:
    p = p or TurtleParams()
    return max(p.entry_channel, p.exit_channel, p.vwap_window if p.use_vwap_filter else 0) + 3
