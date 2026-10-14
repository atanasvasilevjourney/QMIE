from __future__ import annotations

import numpy as np
import pandas as pd

from research.trend_lab.tema_macd_prop import (
    TemaMacdParams,
    brute_force_calmar_is,
    close_to_ohlcv,
    tema_macd_trades,
)


def _ohlcv(n: int = 400) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=n, tz="UTC")
    close = 100 + np.cumsum(np.random.default_rng(0).normal(0.05, 1.0, n))
    return close_to_ohlcv(pd.Series(close, index=idx))


def test_macd_gate_reduces_or_equal_trades():
    df = _ohlcv(500)
    p0 = TemaMacdParams(use_macd=False, min_adx=0.0, min_atr_pct=0.0, max_atr_pct=50.0, leverage=1.0)
    p1 = TemaMacdParams(use_macd=True, min_adx=0.0, min_atr_pct=0.0, max_atr_pct=50.0, leverage=1.0)
    assert len(tema_macd_trades(df, p1)) <= len(tema_macd_trades(df, p0))


def test_brute_force_returns_best():
    df = _ohlcv(600)
    is_end = df.index[400]
    table, best = brute_force_calmar_is(df, is_end=is_end, quick=True, min_trades=1, max_dd_floor=-0.99)
    assert best is not None
    assert not table.empty
    assert table.iloc[0]["calmar"] >= table.iloc[-1]["calmar"]
