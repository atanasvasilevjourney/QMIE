"""30m tape features — Pine-parity Wilder indicators."""
from __future__ import annotations

import numpy as np
import pandas as pd

from scanner.indicators import adx, atr, rsi


def rolling_vwap(df: pd.DataFrame, window: int) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    num = (tp * df["volume"]).rolling(window, min_periods=window).sum()
    den = df["volume"].rolling(window, min_periods=window).sum()
    return num / den.replace(0, np.nan)


def compute_tape_row(
    df: pd.DataFrame,
    *,
    vwap_bars: int = 48,
    atr_len: int = 14,
    rsi_len: int = 14,
    adx_len: int = 14,
    prev_rsi: float | None = None,
) -> dict:
    """Metrics on the last **closed** bar of a 30m frame."""
    work = df.sort_index()
    if len(work) < vwap_bars + 5:
        return {"ok": False, "reason": "insufficient_bars"}

    vwap = rolling_vwap(work, vwap_bars)
    atr_s = atr(work, atr_len)
    rsi_s = rsi(work["close"], rsi_len)
    _, _, adx_s = adx(work, adx_len)

    tail = work.tail(vwap_bars)
    quote_vol = float((tail["close"] * tail["volume"]).sum())

    i = -1
    close = float(work["close"].iloc[i])
    v = float(vwap.iloc[i])
    dist = close - v
    dist_pct = (close / v - 1.0) * 100.0 if v > 0 else float("nan")
    atr_val = float(atr_s.iloc[i])
    atr_pct = (atr_val / close * 100.0) if close > 0 else float("nan")
    rsi_val = float(rsi_s.iloc[i])
    adx_val = float(adx_s.iloc[i])
    rsi_delta = None if prev_rsi is None else round(rsi_val - prev_rsi, 0)

    return {
        "ok": True,
        "price": close,
        "vwap24": v,
        "dist": dist,
        "dist_pct": dist_pct,
        "atr_pct": atr_pct,
        "quote_vol_24h": quote_vol,
        "rsi": rsi_val,
        "rsi_delta": rsi_delta,
        "adx": adx_val,
        "timestamp": work.index[i],
    }


def tape_label(dist_pct: float, rsi: float, adx: float) -> str:
    """Community-style tape read (NFA, not a trade instruction)."""
    if rsi >= 82 or (rsi >= 78 and dist_pct >= 8):
        return "EUPHORIA_OVERLOAD"
    if rsi >= 75 and dist_pct >= 5:
        return "FOMO_RICH_TAKE_PARTIAL"
    if adx < 18 and dist_pct >= 4:
        return "COILED_HOT_BREAKOUT_TEASE"
    if adx >= 35 and rsi >= 70:
        return "TREND_HEAT_EXTEND_CAUTIOUS"
    if dist_pct >= 3 and rsi >= 65:
        return "BULLISH_TRENDING"
    if dist_pct <= -3:
        return "BELOW_VWAP_WEAK"
    return "NEUTRAL_TAPE"
