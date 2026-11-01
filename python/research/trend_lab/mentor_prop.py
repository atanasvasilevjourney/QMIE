"""Mentor prop deployment model (research): flag → Carver, canaries, FTMO helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import max_dd


def mentor_gated_weights(
    w_carver: pd.DataFrame,
    flag: pd.DataFrame,
    *,
    min_flag: float = 0.5,
) -> pd.DataFrame:
    """Carver sizes only when ``flag`` is on (ensemble or Donchian). Same index/columns."""
    f = flag.reindex(w_carver.index).reindex(columns=w_carver.columns).fillna(0.0)
    return w_carver.mul((f >= min_flag).astype(float))


def apply_gross_multiplier(w: pd.DataFrame, mult: pd.Series) -> pd.DataFrame:
    m = mult.reindex(w.index).ffill().fillna(1.0)
    return w.mul(m, axis=0)


def canary_defensive_multiplier(
    spy: pd.Series,
    qqq: pd.Series,
    xlu: pd.Series,
    *,
    lookback: int = 60,
    step: float = 0.25,
) -> pd.Series:
    """Simplified Bootcamp canaries: XLU/SPY and QQQ/SPY vs rolling mean.

    Each active risk-off vote reduces gross by ``step`` (floor 0.25). Research only.
    """
    idx = spy.index.intersection(qqq.index).intersection(xlu.index)
    spy, qqq, xlu = spy.reindex(idx), qqq.reindex(idx), xlu.reindex(idx)
    r_xlu = (xlu / spy).replace([np.inf, -np.inf], np.nan)
    r_qqq = (qqq / spy).replace([np.inf, -np.inf], np.nan)
    xlu_hot = (r_xlu > r_xlu.rolling(lookback, min_periods=lookback // 2).mean()).astype(float)
    qqq_cold = (r_qqq < r_qqq.rolling(lookback, min_periods=lookback // 2).mean()).astype(float)
    votes = xlu_hot + qqq_cold
    mult = (1.0 - step * votes).clip(0.25, 1.0)
    return mult.rename("canary_gross_mult")


def dial_return_scale_is(
    net: pd.Series,
    is_end: pd.Timestamp,
    *,
    max_dd_floor: float = -0.08,
) -> tuple[float, pd.Series]:
    """Largest return scale on IS with max DD no worse than ``max_dd_floor``."""
    is_net = net.loc[:is_end].fillna(0.0)
    chosen = 0.08
    for sc in np.arange(0.08, 1.51, 0.02):
        dd = max_dd((1.0 + is_net * sc).cumprod())
        if dd >= max_dd_floor:
            chosen = float(sc)
        else:
            break
    return chosen, net.fillna(0.0) * chosen


def days_to_profit_pct(net: pd.Series, pct: float = 0.10) -> int | None:
    """Calendar bars from series start until cumulative return >= ``pct``."""
    net = net.fillna(0.0)
    eq = (1.0 + net).cumprod()
    target = 1.0 + pct
    hit = np.where(eq.values >= target)[0]
    return int(hit[0] + 1) if len(hit) else None


def ftmo_daily_stats(
    net: pd.Series,
    *,
    start_cap: float = 100_000.0,
    daily_loss_pct: float = 0.05,
) -> dict[str, float]:
    net = net.fillna(0.0)
    eq = start_cap * (1.0 + net).cumprod()
    bal = eq.shift(1).fillna(start_cap)
    day_pnl = bal * net
    day_loss_pct = day_pnl / bal
    return {
        "worst_daily_loss_pct": float(day_loss_pct.min()),
        "days_breach_5pct": int((day_loss_pct < -daily_loss_pct).sum()),
    }
