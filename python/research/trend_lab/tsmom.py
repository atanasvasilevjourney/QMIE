"""Time-series momentum (SIGN) — Lamberti / Moskowitz-style baseline on crypto daily.

Reference: https://github.com/maxlamberti/time-series-momentum (Lim, Zohren, Roberts DMN).
This module implements the **SIGN** rule from ``Backtest_Baseline.ipynb`` only (no TensorFlow DMN).
Research-only; does not retune QMIE ``W_*`` or dispatch alerts.

Crypto conventions: ``ann_days=365``, lookback 365 calendar days, optional long-only clip.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .protocol import ANN_DAYS

SIGMA_TARGET = 0.15  # daily vol target in weight formula (Lamberti futures notebook)
EWM_SIGMA_SPAN = 60
LOOKBACK_DAYS = 365
COST_BPS = 3.25
EXEC_LAG = 1
WEIGHT_CAP = 1.0  # clip per-name forecast; futures notionals can exceed 1 — crypto book caps
GROSS_CAP = 1.0  # max sum |weight|/n across the top-N book

# Static top-10 USDT perps by typical 24h volume (matches scanner auto-top-N intent).
TOP10_CRYPTO = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
]


def daily_sigma(returns: pd.Series, *, span: int = EWM_SIGMA_SPAN) -> pd.Series:
    return returns.ewm(span=span, min_periods=span).std().rename("sigma")


def rolling_compound_return(returns: pd.Series, window: int) -> pd.Series:
    return (1.0 + returns).rolling(window).apply(np.prod, raw=True) - 1.0


def sign_direction(compound_ret: pd.Series, *, long_only: bool = False) -> pd.Series:
    sign = np.where(compound_ret >= 0.0, 1.0, -1.0)
    out = pd.Series(sign, index=compound_ret.index, dtype=float)
    if long_only:
        out = out.clip(lower=0.0)
    return out.rename("sign")


def sign_weights_daily(
    close: pd.Series,
    *,
    sigma_target: float = SIGMA_TARGET,
    lookback: int = LOOKBACK_DAYS,
    ewm_span: int = EWM_SIGMA_SPAN,
    long_only: bool = False,
) -> pd.Series:
    """Daily SIGN: direction from rolling compound return; vol-scale by EWM sigma."""
    ret = close.pct_change(fill_method=None).fillna(0.0)
    sig = daily_sigma(ret, span=ewm_span)
    mom = rolling_compound_return(ret, lookback)
    direction = sign_direction(mom, long_only=long_only)
    w = direction * (sigma_target / sig.replace(0.0, np.nan))
    w = w.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-WEIGHT_CAP, WEIGHT_CAP)
    return w.rename("weight")


def sign_weights_monthly_lamberti(
    close: pd.Series,
    *,
    sigma_target: float = SIGMA_TARGET,
    lookback: int = LOOKBACK_DAYS,
    ewm_span: int = EWM_SIGMA_SPAN,
    long_only: bool = False,
) -> pd.Series:
    """Month-end SIGN rule aligned to Lamberti ``Backtest_Baseline`` (weights on month-end, ffill daily)."""
    ret = close.pct_change(fill_method=None).fillna(0.0)
    sig = daily_sigma(ret, span=ewm_span)
    mom = rolling_compound_return(ret, lookback)
    direction = sign_direction(mom, long_only=long_only)
    raw = direction * (sigma_target / sig.replace(0.0, np.nan))
    raw = raw.replace([np.inf, -np.inf], np.nan).clip(-WEIGHT_CAP, WEIGHT_CAP)
    monthly = raw.resample("ME").last()
    daily = monthly.reindex(close.index, method="ffill").fillna(0.0)
    return daily.rename("weight")


def backtest_single(
    close: pd.Series,
    weight: pd.Series,
    *,
    cost_bps: float = COST_BPS,
    exec_lag: int = EXEC_LAG,
) -> pd.DataFrame:
    ret = close.pct_change(fill_method=None).fillna(0.0)
    held = weight.shift(exec_lag).fillna(0.0)
    turnover = held.diff().abs().fillna(held.abs())
    net = held * ret - turnover * (cost_bps / 1e4)
    return pd.DataFrame(
        {
            "ret": ret,
            "weight": weight,
            "held": held,
            "turnover": turnover,
            "net": net,
            "equity": (1.0 + net).cumprod(),
        }
    )


def equal_weight_portfolio(
    panel: pd.DataFrame,
    weight_panel: pd.DataFrame,
    *,
    cost_bps: float = COST_BPS,
    exec_lag: int = EXEC_LAG,
) -> pd.DataFrame:
    """Each name gets ``1/n`` of book; per-name weights are scaled forecasts."""
    rets = panel.pct_change(fill_method=None).fillna(0.0)
    n = len(panel.columns)
    if n == 0:
        raise ValueError("empty panel")
    frac = 1.0 / n
    held = weight_panel.shift(exec_lag).fillna(0.0) * frac
    gross = held.abs().sum(axis=1)
    cap_f = (GROSS_CAP / gross.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
    held = held.mul(cap_f, axis=0)
    gross_ret = (held * rets).sum(axis=1)
    turnover = held.diff().abs().fillna(held.abs()).sum(axis=1)
    net = gross_ret - turnover * (cost_bps / 1e4)
    return pd.DataFrame(
        {
            "net": net,
            "equity": (1.0 + net).cumprod(),
            "turnover": turnover,
            "gross": held.abs().sum(axis=1),
            "n_long": (held > 0).sum(axis=1),
            "n_short": (held < 0).sum(axis=1),
        }
    )


def buy_hold_portfolio(panel: pd.DataFrame, *, exec_lag: int = EXEC_LAG) -> pd.Series:
    rets = panel.pct_change(fill_method=None).fillna(0.0)
    n = len(panel.columns)
    w = pd.DataFrame(1.0 / n, index=panel.index, columns=panel.columns)
    held = w.shift(exec_lag).fillna(0.0)
    return (held * rets).sum(axis=1).rename("net")
