"""OHLCV validation — gaps and bad bars block downstream signals."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from scanner.indicators import atr

logger = logging.getLogger(__name__)

_REQUIRED = ("open", "high", "low", "close", "volume")


@dataclass
class ValidationReport:
    ok: bool
    n_bars: int
    duplicate_timestamps: int = 0
    gap_count: int = 0
    zero_volume_bars: int = 0
    invalid_hl_bars: int = 0
    outlier_wick_bars: int = 0
    blocked_mask: pd.Series = field(default_factory=lambda: pd.Series(dtype=bool))
    messages: list[str] = field(default_factory=list)


def _expected_delta(tf: str) -> pd.Timedelta:
    tf = tf.lower()
    mapping = {
        "1m": "1min",
        "3m": "3min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1D",
    }
    if tf not in mapping:
        raise ValueError(f"unsupported timeframe for gap detection: {tf}")
    return pd.Timedelta(mapping[tf])


def _blocked_to_input_index(
    input_index: pd.Index,
    work_index: pd.Index,
    blocked: pd.Series,
) -> pd.Series:
    out = pd.Series(False, index=input_index)
    for ts in work_index[blocked.fillna(False)]:
        out.loc[ts] = True
    return out


def validate_ohlcv(
    df: pd.DataFrame,
    *,
    timeframe: str,
    wick_atr_mult: float = 15.0,
) -> ValidationReport:
    """
    Validate monotonic UTC index, duplicates, gaps, bad bars, outlier wicks.

    Returns ``blocked_mask`` (True = do not trade / signal on this bar).
    Does not forward-fill prices.
    """
    messages: list[str] = []
    if df.empty:
        return ValidationReport(ok=False, n_bars=0, messages=["empty frame"])

    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        return ValidationReport(ok=False, n_bars=0, messages=[f"missing columns: {missing}"])

    work = df.sort_index()
    idx = pd.DatetimeIndex(work.index)
    if idx.tz is None:
        messages.append("index not timezone-aware; treating as UTC")
        idx = idx.tz_localize("UTC")
        work = work.copy()
        work.index = idx
    else:
        work.index = idx.tz_convert("UTC")

    n = len(work)
    dup_mask = work.index.duplicated(keep=False)
    dup = int(dup_mask.sum())
    if dup:
        messages.append(f"duplicate timestamps: {dup}")

    if not work.index.is_monotonic_increasing:
        messages.append("index not monotonic increasing")
        work = work.sort_index()

    delta = _expected_delta(timeframe)
    diffs = work.index.to_series().diff().iloc[1:]
    gaps = diffs[diffs > delta * 1.5]
    gap_count = int(len(gaps))
    if gap_count:
        messages.append(f"detected {gap_count} timestamp gaps > 1.5× bar size")

    zero_vol = int((work["volume"] <= 0).sum())
    invalid_hl = int((work["high"] < work["low"]).sum())
    if zero_vol:
        messages.append(f"zero-volume bars: {zero_vol}")
    if invalid_hl:
        messages.append(f"high < low bars: {invalid_hl}")

    a15 = atr(work, 14)
    body_top = work[["open", "close"]].max(axis=1)
    body_bot = work[["open", "close"]].min(axis=1)
    upper_wick = work["high"] - body_top
    lower_wick = body_bot - work["low"]
    max_wick = pd.concat([upper_wick, lower_wick], axis=1).max(axis=1)
    outlier = (max_wick > wick_atr_mult * a15) & a15.notna() & (a15 > 0)
    outlier_count = int(outlier.sum())
    if outlier_count:
        messages.append(f"outlier wick bars (>{wick_atr_mult} ATR): {outlier_count}")

    blocked = pd.Series(False, index=work.index)
    blocked |= dup_mask
    blocked |= work["volume"] <= 0
    blocked |= work["high"] < work["low"]
    blocked |= outlier.fillna(False)

    if gap_count:
        for ts in gaps.index:
            if ts in blocked.index:
                blocked.loc[ts] = True

    ok = dup == 0 and invalid_hl == 0 and gap_count == 0
    return ValidationReport(
        ok=ok,
        n_bars=n,
        duplicate_timestamps=int(work.index.duplicated(keep="first").sum()),
        gap_count=gap_count,
        zero_volume_bars=zero_vol,
        invalid_hl_bars=invalid_hl,
        outlier_wick_bars=outlier_count,
        blocked_mask=_blocked_to_input_index(df.index, work.index, blocked),
        messages=messages,
    )
