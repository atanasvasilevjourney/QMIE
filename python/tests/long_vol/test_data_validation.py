from __future__ import annotations

import pandas as pd
import pytest

from long_vol.data.validate import validate_ohlcv


def _ohlcv(idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
        },
        index=idx,
    )


def test_validate_rejects_duplicate_timestamps():
    idx = pd.date_range("2024-01-01", periods=4, freq="15min", tz="UTC")
    df = _ohlcv(idx)
    df = pd.concat([df, df.iloc[[1]]])
    rep = validate_ohlcv(df, timeframe="15m")
    assert rep.duplicate_timestamps >= 1
    assert rep.ok is False
    assert rep.blocked_mask.any()


def test_validate_flags_gap():
    idx = pd.DatetimeIndex(
        [
            "2024-01-01 00:00:00+00:00",
            "2024-01-01 00:15:00+00:00",
            "2024-01-01 01:00:00+00:00",
        ],
        tz="UTC",
    )
    df = _ohlcv(idx)
    rep = validate_ohlcv(df, timeframe="15m")
    assert rep.gap_count >= 1
    assert rep.ok is False


def test_validate_zero_volume_blocked():
    idx = pd.date_range("2024-01-01", periods=8, freq="15min", tz="UTC")
    df = _ohlcv(idx)
    df.loc[df.index[3], "volume"] = 0
    rep = validate_ohlcv(df, timeframe="15m")
    assert rep.zero_volume_bars == 1
    assert bool(rep.blocked_mask.iloc[3])
