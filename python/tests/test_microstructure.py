"""Microstructure detectors — pure math, no network."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.microstructure import (
    funding_squeeze_score,
    oi_influx_score,
    range_breakout_score,
    run_detectors,
    vol_turnover_score,
    volume_velocity_score,
)


def _ohlcv_from_vol(volumes: np.ndarray, price: float = 100.0) -> pd.DataFrame:
    n = len(volumes)
    return pd.DataFrame({
        "open": np.full(n, price),
        "high": np.full(n, price * 1.01),
        "low": np.full(n, price * 0.99),
        "close": np.full(n, price),
        "volume": volumes,
    }, index=pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC"))


class TestVolumeVelocity:
    def test_spike_triggers(self):
        vol = np.concatenate([np.full(35, 100.0), [5000.0]])
        df = _ohlcv_from_vol(vol)
        hit = volume_velocity_score(df, window=30, z_threshold=4.0)
        assert hit is not None
        assert hit.tag == "vol_velocity"
        assert hit.score > 0.5

    def test_flat_volume_no_hit(self):
        vol = np.full(40, 100.0)
        df = _ohlcv_from_vol(vol)
        assert volume_velocity_score(df, window=30, z_threshold=4.0) is None


class TestDerivatives:
    def test_vol_turnover(self):
        hit = vol_turnover_score(50_000_000, 10_000_000, threshold=2.0)
        assert hit is not None
        assert hit.value == pytest.approx(5.0)

    def test_oi_influx(self):
        hit = oi_influx_score(3.0, 8.0, min_oi_pct=5.0, min_price_pct=1.0)
        assert hit is not None
        assert hit.tag == "oi_influx"

    def test_funding_squeeze(self):
        hit = funding_squeeze_score(-0.0002, 4.0, max_funding=-0.00005, min_price_pct=1.0)
        assert hit is not None
        assert hit.tag == "funding_squeeze"


class TestRangeBreakout:
    def test_up_break(self):
        n = 25
        close = np.full(n, 100.0)
        df = pd.DataFrame({
            "open": close, "high": close + 1, "low": close - 1, "close": close,
            "volume": np.full(n, 1e6),
        }, index=pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"))
        df.iloc[-1, df.columns.get_loc("close")] = 105.0
        df.iloc[-1, df.columns.get_loc("high")] = 106.0
        hit = range_breakout_score(df, lookback=20, max_width_pct=15.0)
        assert hit is not None
        assert "UP" in hit.detail


class TestRunDetectors:
    def test_ticker_only_hits(self):
        ticker = {
            "quote_volume_24h": 40_000_000,
            "open_interest_usd": 10_000_000,
            "price_change_pct_24h": 5.0,
            "funding_rate": -0.0003,
        }
        hits = run_detectors(
            ticker=ticker,
            oi_change_pct=10.0,
            df_1m=None,
            df_1h=None,
            liquidations=[],
            agg_trades=[],
        )
        tags = {h.tag for h in hits}
        assert "vol_turnover" in tags
        assert "oi_influx" in tags
        assert "funding_squeeze" in tags
