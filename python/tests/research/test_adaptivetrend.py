"""AdaptiveTrend replication tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.trend_lab.adaptivetrend import AdaptiveTrendParams, backtest_adaptivetrend_symbol, momentum_series


def _ohlcv(n: int = 400) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    close = np.linspace(100, 200, n)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.005,
            "low": np.minimum(open_, close) * 0.995,
            "close": close,
            "volume": 1e6,
        },
        index=idx,
    )


def test_momentum_lookback_is_causal():
    c = pd.Series(np.arange(100, 200, dtype=float), index=pd.date_range("2020-01-01", periods=100, freq="6h", tz="UTC"))
    m = momentum_series(c, 10)
    assert pd.isna(m.iloc[9])
    assert np.isfinite(m.iloc[10])


def test_backtest_runs_on_trend():
    df = _ohlcv(500)
    from backtest.data_loader import resample_ohlcv

    df6 = resample_ohlcv(df, "6h")
    _, trades = backtest_adaptivetrend_symbol(
        df6, "TEST", AdaptiveTrendParams(theta_entry=0.001, theta_short=0.001, lookback=5)
    )
    assert isinstance(trades, list)


def test_load_6h_from_synthetic_path():
    df = _ohlcv(300)
    df6 = __import__("backtest.data_loader", fromlist=["resample_ohlcv"]).resample_ohlcv(df, "6h")
    assert len(df6) < len(df)
