"""US100 (QQQ proxy) bull canary for gating equity momentum books."""
from __future__ import annotations

import pandas as pd


def donchian_upper(close: pd.Series, n_entry: int) -> pd.Series:
    return close.shift(1).rolling(n_entry, min_periods=n_entry).max()


def us100_bull_canary(
    close: pd.Series,
    *,
    sma_days: int = 200,
    don_entry: int = 55,
    mode: str = "both",
) -> pd.Series:
    """Daily 0/1 regime: index bull suitable for stock momentum sleeve.

    ``mode``:
      - ``sma200``: close > SMA200
      - ``donchian``: close > prior ``don_entry``-day high
      - ``both``: SMA200 AND Donchian breakout (default)
      - ``either``: SMA200 OR Donchian
    """
    c = close.astype(float)
    sma = c.rolling(sma_days, min_periods=sma_days).mean()
    upper = donchian_upper(c, don_entry)
    above_ma = c > sma
    breakout = c > upper
    if mode == "sma200":
        on = above_ma
    elif mode == "donchian":
        on = breakout
    elif mode == "either":
        on = above_ma | breakout
    else:
        on = above_ma & breakout
    return on.astype(float).rename("us100_canary")
