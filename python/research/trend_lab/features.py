"""Feature math. Pine EMA/RSI/ADX via scanner.indicators. KAMA/ALMA/MACD/z-score here.

KAMA/ALMA are *research overlays* (KovaView map). They must not retune live W_*.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scanner.indicators import adx, atr, ema, rsi, triple_ema_dir


def kama(series: pd.Series, n: int = 10, fast: int = 2, slow: int = 30) -> tuple[pd.Series, pd.Series]:
    """Kaufman AMA + efficiency ratio. Seeded at bar n. No lookahead."""
    change = (series - series.shift(n)).abs()
    volatility = (series - series.shift(1)).abs().rolling(n).sum()
    er = change / (volatility + 1e-12)
    sc = (er * (2.0 / (fast + 1.0) - 2.0 / (slow + 1.0)) + 2.0 / (slow + 1.0)) ** 2
    arr = series.to_numpy(dtype=float)
    sc_a = sc.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    if len(arr) <= n:
        return pd.Series(out, index=series.index), er
    out[n] = arr[n]
    for i in range(n + 1, len(arr)):
        prev = out[i - 1]
        s = sc_a[i]
        x = arr[i]
        if np.isnan(prev) or np.isnan(s) or np.isnan(x):
            out[i] = prev
        else:
            out[i] = prev + s * (x - prev)
    return pd.Series(out, index=series.index, name="kama"), er


def alma(series: pd.Series, window: int = 9, sigma: float = 6.0, offset: float = 0.85) -> pd.Series:
    """Arnaud Legoux MA. Causal rolling window only."""
    if window < 2:
        raise ValueError("alma window must be >= 2")
    m = offset * (window - 1)
    s = window / sigma
    w = np.exp(-((np.arange(window) - m) ** 2) / (2.0 * s * s))
    w = w / w.sum()
    return series.rolling(window).apply(lambda x: float(np.dot(x, w)), raw=True).rename("alma")


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    hist = line - sig
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": hist})


def zscore(series: pd.Series, window: int = 20) -> pd.Series:
    mu = series.rolling(window).mean()
    sd = series.rolling(window).std(ddof=0)
    return ((series - mu) / (sd + 1e-12)).rename("zscore")


def donchian(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Prior-window channel (shift 1) so today's high is not in the breakout level."""
    hi = df["high"].shift(1).rolling(n).max()
    lo = df["low"].shift(1).rolling(n).min()
    mid = (hi + lo) / 2.0
    width = (hi - lo) / (df["close"] + 1e-12)
    return pd.DataFrame({"donch_high": hi, "donch_low": lo, "donch_mid": mid, "coil_width": width})


def tma_agreement(close: pd.Series, fast: int = 9, mid: int = 90, slow: int = 199) -> pd.Series:
    e_f, e_m, e_s = ema(close, fast), ema(close, mid), ema(close, slow)
    d1 = np.sign(e_f - e_m)
    d2 = np.sign(e_f - e_s)
    d3 = np.sign(e_m - e_s)
    return (d1 + d2 + d3).rename("tma_agree")


def feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Closed-bar features for Boruta. All causal."""
    c = df["close"]
    out = pd.DataFrame(index=df.index)
    out["ret1"] = c.pct_change()
    out["tma_agree"] = tma_agreement(c)
    e9, e90, e199 = ema(c, 9), ema(c, 90), ema(c, 199)
    out["ema_fast_slow"] = (e9 - e199) / (c + 1e-12)
    out["ema_stack"] = ((e9 > e90) & (e90 > e199)).astype(float)
    out["rsi"] = rsi(c, 14)
    pdi, mdi, adx_s = adx(df, 14)
    out["adx"] = adx_s
    out["di_spread"] = pdi - mdi
    out["atr_pct"] = 100.0 * atr(df, 14) / c
    mac = macd(c)
    out["macd_hist"] = mac["macd_hist"]
    out["zscore_20"] = zscore(c, 20)
    k_s, er = kama(c, n=10)
    k_l, _ = kama(c, n=60)
    out["kama_er"] = er
    out["kama_cross"] = (k_s - k_l) / (c + 1e-12)
    out["alma_slope"] = alma(c, 9).pct_change(5)
    don = donchian(df, 20)
    out["coil_width"] = don["coil_width"]
    out["donch_excess"] = (c - don["donch_high"]) / (c + 1e-12)
    out["vol_20"] = out["ret1"].rolling(20).std()
    return out
