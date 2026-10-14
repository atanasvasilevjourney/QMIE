"""Volume profile and TPO-lite from closed OHLCV bars. No new dependencies."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _bins(lo: float, hi: float, n: int = 40) -> np.ndarray | None:
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return None
    return np.linspace(lo, hi, n + 1)


def _value_area(weights: np.ndarray, poc_i: int, frac: float = 0.70) -> tuple[int, int]:
    total = float(weights.sum())
    if total <= 0:
        return poc_i, poc_i
    target = total * frac
    acc = float(weights[poc_i])
    lo = hi = poc_i
    last = len(weights) - 1
    while acc < target and (lo > 0 or hi < last):
        left = float(weights[lo - 1]) if lo > 0 else -1.0
        right = float(weights[hi + 1]) if hi < last else -1.0
        if right >= left and hi < last:
            hi += 1
            acc += float(weights[hi])
        elif lo > 0:
            lo -= 1
            acc += float(weights[lo])
        else:
            break
    return lo, hi


def _mid(edges: np.ndarray, i: int) -> float:
    return float((edges[i] + edges[i + 1]) / 2.0)


def volume_profile(df: pd.DataFrame, *, bins: int = 40) -> dict[str, Any] | None:
    """Distribute each bar's volume uniformly across bins it spans."""
    if df is None or df.empty:
        return None
    lo = float(df["low"].min())
    hi = float(df["high"].max())
    edges = _bins(lo, hi, bins)
    if edges is None:
        return None
    weights = np.zeros(bins, dtype=float)
    for row in df.itertuples(index=False):
        span_lo = float(row.low)
        span_hi = float(row.high)
        vol = float(row.volume)
        if vol <= 0 or span_hi < span_lo:
            continue
        if span_hi == span_lo:
            i = int(np.clip(np.searchsorted(edges, span_lo, side="right") - 1, 0, bins - 1))
            weights[i] += vol
            continue
        touched = 0
        marks = []
        for i in range(bins):
            if edges[i + 1] < span_lo or edges[i] > span_hi:
                continue
            marks.append(i)
            touched += 1
        if touched:
            share = vol / touched
            for i in marks:
                weights[i] += share
    if weights.sum() <= 0:
        return None
    poc_i = int(weights.argmax())
    va_lo, va_hi = _value_area(weights, poc_i)
    close = float(df["close"].iloc[-1])
    poc = _mid(edges, poc_i)
    return {
        "poc": poc,
        "vah": _mid(edges, va_hi),
        "val": _mid(edges, va_lo),
        "dist_to_poc_pct": ((close - poc) / close * 100.0) if close else None,
    }


def tpo_profile(df: pd.DataFrame, *, bins: int = 40) -> dict[str, Any] | None:
    """Each closed bar is one time period. Count periods that overlap a price bin."""
    if df is None or df.empty:
        return None
    lo = float(df["low"].min())
    hi = float(df["high"].max())
    edges = _bins(lo, hi, bins)
    if edges is None:
        return None
    counts = np.zeros(bins, dtype=float)
    for row in df.itertuples(index=False):
        span_lo = float(row.low)
        span_hi = float(row.high)
        for i in range(bins):
            if edges[i + 1] < span_lo or edges[i] > span_hi:
                continue
            counts[i] += 1.0
    if counts.sum() <= 0:
        return None
    poc_i = int(counts.argmax())
    va_lo, va_hi = _value_area(counts, poc_i)
    close = float(df["close"].iloc[-1])
    poc = _mid(edges, poc_i)
    poor_high = bool(counts[-1] <= 1 and counts[-1] > 0)
    poor_low = bool(counts[0] <= 1 and counts[0] > 0)
    return {
        "tpo_poc": poc,
        "tpo_vah": _mid(edges, va_hi),
        "tpo_val": _mid(edges, va_lo),
        "dist_to_tpo_poc_pct": ((close - poc) / close * 100.0) if close else None,
        "poor_high": poor_high,
        "poor_low": poor_low,
    }
