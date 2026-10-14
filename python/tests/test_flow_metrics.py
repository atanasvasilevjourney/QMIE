"""Flow screener helpers — mocked REST, no network."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.flow_ideas import flow_ideas
from scanner.flow_metrics import _cvd_slope, _ohlc_proxy_delta
from scanner.flow_profile import tpo_profile, volume_profile


def test_ohlc_proxy_delta_balanced_bar_near_zero():
    df = pd.DataFrame(
        {"open": [100.0], "high": [110.0], "low": [90.0], "close": [100.0], "volume": [1000.0]},
        index=pd.DatetimeIndex(["2026-01-01"], tz="UTC"),
    )
    d = _ohlc_proxy_delta(df)
    assert d.iloc[0] == pytest.approx(0.0, abs=1e-6)


def test_cvd_slope_positive_when_buy_pressure():
    delta = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert _cvd_slope(delta, lookback=3) == pytest.approx(11.0)


def _trend_df() -> pd.DataFrame:
    n = 12
    close = np.linspace(100, 112, n)
    return pd.DataFrame(
        {
            "open": close - 0.4,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    )


def test_volume_profile_poc_inside_range():
    df = _trend_df()
    vp = volume_profile(df)
    assert vp is not None
    assert df["low"].min() <= vp["poc"] <= df["high"].max()
    assert vp["val"] <= vp["poc"] <= vp["vah"]


def test_tpo_profile_flags_shape():
    df = _trend_df()
    tpo = tpo_profile(df)
    assert tpo is not None
    assert "poor_high" in tpo and "poor_low" in tpo


def test_ideas_long_when_oi_and_cvd_agree():
    ideas = flow_ideas({
        "symbol": "SOLUSDT",
        "close": 150.0,
        "oi_change_pct": 4.0,
        "cvd_slope": 1200.0,
        "price_change_pct": 2.1,
        "funding_rate": 0.0001,
        "poc": 148.0,
        "vah": 152.0,
        "val": 146.0,
    })
    assert ideas[0]["bias"] == "LONG"
    assert ideas[0]["places_orders"] is False
    assert len(ideas) <= 3


def test_ideas_use_poc_when_oi_missing():
    ideas = flow_ideas({
        "symbol": "BTCUSDT",
        "close": 100.0,
        "price_change_pct": -1.2,
        "cvd_slope": -400.0,
        "poc": 102.0,
        "vah": 104.0,
        "val": 98.0,
    })
    assert ideas[0]["bias"] == "SHORT"
    assert ideas[0]["setup"] == "Aggressive sell below POC"
    assert ideas[0]["places_orders"] is False


def test_ideas_wait_when_nothing_aligns():
    ideas = flow_ideas({"symbol": "ADAUSDT", "close": 0.4})
    assert ideas[0]["bias"] == "WAIT"
    assert ideas[0]["places_orders"] is False
