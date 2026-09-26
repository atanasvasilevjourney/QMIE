"""Donchian AVWAP path smoke tests (synthetic)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.trend_lab.donchian_avwap_util import avwap_from_anchor, seed_avwap_cum
from research.trend_lab.donchian_nb08 import Donchian08Params, donchian_nb08_weight_series


def _ohlcv(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.normal(0.2, 1.0, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    vol = rng.uniform(1e3, 5e3, n)
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


def test_avwap_anchor_monotonic_with_volume():
    df = _ohlcv(30)
    t0, t1 = df.index[5], df.index[15]
    av = avwap_from_anchor(df, t0, t1)
    pv, v = seed_avwap_cum(df, t0, t1)
    assert np.isfinite(av)
    assert abs(av - pv / v) < 1e-9


def test_donchian_avwap_gate_runs():
    df = _ohlcv(200)
    w0 = donchian_nb08_weight_series(df, Donchian08Params(use_avwap_gate=False))
    w1 = donchian_nb08_weight_series(
        df, Donchian08Params(use_avwap_gate=True, use_compression_gate=False),
    )
    assert w0.max() >= 0
    assert w1.max() >= 0
    assert len(w0) == len(df)
