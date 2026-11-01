"""Indicator parity for features layer (delegates to scanner.indicators)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from long_vol.features.long_vol_features import compute_1h_features, compute_long_vol_features
from long_vol.config import FeaturesConfig
from scanner.indicators import adx, atr, rsi


def _df(n: int = 200, freq: str = "1h") -> pd.DataFrame:
    idx = pd.date_range("2023-01-01", periods=n, freq=freq, tz="UTC")
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": rng.uniform(800, 1200, n),
        },
        index=idx,
    )


def test_atr_rsi_adx_match_scanner_on_1h():
    df = _df(120)
    f = compute_1h_features(df, FeaturesConfig())
    atr_direct = atr(df, 14)
    _, _, adx_direct = adx(df, 14)
    rsi_direct = rsi(df["close"], 14)
    pd.testing.assert_series_equal(f["atr1h"], atr_direct, check_names=False)
    pd.testing.assert_series_equal(f["rsi_1h"], rsi_direct, check_names=False)
    pd.testing.assert_series_equal(f["adx"], adx_direct, check_names=False)


def test_donchian_excludes_current_bar():
    df = _df(40)
    f = compute_1h_features(df, FeaturesConfig(donchian_entry=5))
    n = 5
    i = 10
    ts = df.index[i]
    expected = df["high"].iloc[i - n : i].max()
    assert f.loc[ts, "don_up_1h"] == pytest.approx(expected, rel=1e-9)


def test_vwap_nan_until_window_full():
    df15 = _df(120, freq="15min")
    out = compute_long_vol_features(df15, cfg=FeaturesConfig(vwap_bars=96))
    assert out.df15["vwap24"].iloc[95:96].notna().all()
    assert out.df15["vwap24"].iloc[:95].isna().all()
