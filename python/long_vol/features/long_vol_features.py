"""
Pure feature layer for long-vol breakout (§1.2).

All inputs are OHLCV DataFrames indexed by bar **open** time (UTC).
15m is the execution timeframe; 1h series are built via closed-bar resample
and aligned to 15m without look-ahead (value available after 1h bar closes).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.data_loader import resample_ohlcv
from scanner.indicators import adx, atr, rsi

from long_vol.config import FeaturesConfig


@dataclass(frozen=True)
class LongVolFeatureFrame:
    """15m-indexed feature columns plus aligned 1h Donchian fields."""

    df15: pd.DataFrame
    df1h: pd.DataFrame


def _rolling_vwap(tp: pd.Series, vol: pd.Series, window: int) -> pd.Series:
    num = (tp * vol).rolling(window, min_periods=window).sum()
    den = vol.rolling(window, min_periods=window).sum()
    return num / den.replace(0, np.nan)


def _percentile_rank_past_only(s: pd.Series, lookback: int) -> pd.Series:
    """Rolling percentile rank in [0, 100] using only past values (excludes current)."""

    def _rank(window: np.ndarray) -> float:
        if len(window) < 2 or np.isnan(window[-1]):
            return np.nan
        past = window[:-1]
        past = past[~np.isnan(past)]
        if len(past) == 0:
            return np.nan
        cur = window[-1]
        return 100.0 * float(np.sum(past <= cur) / len(past))

    return s.rolling(lookback + 1, min_periods=lookback + 1).apply(_rank, raw=True)


def _rvol_tod(vol15: pd.Series, n_days: int) -> pd.Series:
    """Volume / median same time-of-day over prior ``n_days`` (past-only)."""
    df = pd.DataFrame({"v": vol15})
    df["slot"] = df.index.hour * 4 + df.index.minute // 15
    df["day"] = df.index.normalize()
    out = pd.Series(np.nan, index=vol15.index, dtype=float)
    for ts in df.index:
        slot = int(df.at[ts, "slot"])
        day = df.at[ts, "day"]
        hist = df[(df["slot"] == slot) & (df["day"] < day)].tail(n_days)
        if len(hist) < max(3, n_days // 4):
            continue
        med = float(hist["v"].median())
        if med > 0:
            out.loc[ts] = float(df.at[ts, "v"]) / med
    return out


def compute_1h_features(df1h: pd.DataFrame, cfg: FeaturesConfig) -> pd.DataFrame:
    """Donchian, width, RSI, ADX on closed 1h bars."""
    h = df1h.copy()
    n = cfg.donchian_entry
    ex = cfg.donchian_exit
    atr1 = atr(h, 14)
    _, _, adx1 = adx(h, 14)
    rsi1 = rsi(h["close"], 14)

    don_up = h["high"].rolling(n, min_periods=n).max().shift(1)
    don_dn = h["low"].rolling(n, min_periods=n).min().shift(1)
    don_mid = (don_up + don_dn) / 2.0
    exit_don = h["low"].rolling(ex, min_periods=ex).min().shift(1)
    width_atr = (don_up - don_dn) / atr1.replace(0, np.nan)
    width_pct = _percentile_rank_past_only(width_atr, cfg.width_pct_lookback_1h_bars)

    out = pd.DataFrame(
        {
            "close_1h": h["close"],
            "don_up_1h": don_up,
            "don_dn_1h": don_dn,
            "don_mid_1h": don_mid,
            "exit_don_dn": exit_don,
            "width_atr": width_atr,
            "width_pct": width_pct,
            "atr1h": atr1,
            "rsi_1h": rsi1,
            "adx": adx1,
        },
        index=h.index,
    )
    out["adx_slope"] = out["adx"] - out["adx"].shift(3)
    return out


def align_1h_to_15m(f1h: pd.DataFrame, idx15: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Map each closed 1h bar to 15m bars in that hour without peeking.

    1h bar labeled at open T covers [T, T+1h). It is known only after T+1h close,
    i.e. first 15m index >= T + 1h.
    """
    shifted = f1h.copy()
    shifted.index = shifted.index + pd.Timedelta("1h")
    return shifted.reindex(idx15, method="ffill")


def compute_long_vol_features(
    df15: pd.DataFrame,
    *,
    cfg: FeaturesConfig | None = None,
    df1h: pd.DataFrame | None = None,
    blocked: pd.Series | None = None,
) -> LongVolFeatureFrame:
    cfg = cfg or FeaturesConfig()
    m15 = df15.sort_index()
    if df1h is None:
        df1h = resample_ohlcv(m15, "1h")
    f1h = compute_1h_features(df1h, cfg)

    tp = (m15["high"] + m15["low"] + m15["close"]) / 3.0
    vwap24 = _rolling_vwap(tp, m15["volume"], cfg.vwap_bars)
    atr15 = atr(m15, 14)
    dist_atr = (m15["close"] - vwap24) / atr15.replace(0, np.nan)
    rvol = _rvol_tod(m15["volume"], cfg.rvol_tod_days)

    aligned = align_1h_to_15m(f1h, m15.index)
    feat = pd.DataFrame(
        {
            "open": m15["open"],
            "high": m15["high"],
            "low": m15["low"],
            "close": m15["close"],
            "volume": m15["volume"],
            "tp": tp,
            "vwap24": vwap24,
            "atr15": atr15,
            "dist_atr": dist_atr,
            "rvol": rvol,
        },
        index=m15.index,
    )
    feat = pd.concat([feat, aligned], axis=1)

    comp_lb = cfg.compression_lookback_1h
    min_width = f1h["width_pct"].rolling(comp_lb, min_periods=comp_lb).min()
    feat["compression_ok"] = (
        align_1h_to_15m(min_width.to_frame("min_wp"), m15.index)["min_wp"]
        < cfg.compression_width_pct_max
    )

    if blocked is not None:
        feat.loc[blocked.reindex(feat.index, fill_value=True), :] = np.nan

    return LongVolFeatureFrame(df15=feat, df1h=f1h)


def btc_ok_series(btc15: pd.DataFrame, vwap_bars: int = 96) -> pd.Series:
    tp = (btc15["high"] + btc15["low"] + btc15["close"]) / 3.0
    vwap = _rolling_vwap(tp, btc15["volume"], vwap_bars)
    return btc15["close"] > vwap
