"""Anchored VWAP helpers for Donchian research paths."""
from __future__ import annotations

import numpy as np
import pandas as pd


def avwap_from_anchor(df: pd.DataFrame, anchor_ts: pd.Timestamp, end_ts: pd.Timestamp) -> float:
    sl = df.loc[anchor_ts:end_ts]
    if sl.empty:
        return float("nan")
    tp = (sl["high"] + sl["low"] + sl["close"]) / 3.0
    vol = sl["volume"].replace(0, np.nan)
    if vol.notna().sum() == 0:
        return float(sl["close"].iloc[-1])
    return float((tp * vol).sum() / vol.sum())


def swing_low_ts(df: pd.DataFrame, before: pd.Timestamp, lookback: int = 20) -> pd.Timestamp:
    sl = df.loc[:before].tail(lookback + 1)
    if sl.empty:
        return before
    return pd.Timestamp(sl["low"].idxmin())


def seed_avwap_cum(df: pd.DataFrame, anchor_ts: pd.Timestamp, end_ts: pd.Timestamp) -> tuple[float, float]:
    sl = df.loc[anchor_ts:end_ts]
    tp = (sl["high"] + sl["low"] + sl["close"]) / 3.0
    vol = sl["volume"].astype(float)
    return float((tp * vol).sum()), float(vol.sum())
