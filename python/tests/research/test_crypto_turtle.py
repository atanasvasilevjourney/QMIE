"""crypto-turtle style 20/10 Donchian research tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.trend_lab.crypto_turtle import (
    TurtleCryptoParams,
    backtest_turtle_crypto,
    turtle_signal_frame,
)


def _df(n: int = 120) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    close = np.linspace(100, 130, n)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.01,
            "low": np.minimum(open_, close) * 0.99,
            "close": close,
            "volume": 1e6,
        },
        index=idx,
    )


def test_prev_20_high_excludes_current_bar():
    df = _df(80)
    df.iloc[-1, df.columns.get_loc("high")] = 500.0
    sig = turtle_signal_frame(df, TurtleCryptoParams())
    # prev 20 high at last bar must not include today's 500 wick in the breakout level
    assert float(sig["prev_20d_high"].iloc[-1]) < 500.0


def test_long_entry_requires_rsi_and_atr_pct():
    df = _df(60)
    p = TurtleCryptoParams(min_atr_pct=0.5)  # impossible threshold
    sig = turtle_signal_frame(df, p)
    assert not sig["long_entry"].any()


def test_backtest_runs_and_channels_are_finite():
    df = _df(100)
    p = TurtleCryptoParams(min_atr_pct=0.0, rsi_long_min=0, rsi_short_max=100)
    sig = turtle_signal_frame(df, p)
    assert sig["prev_20d_high"].iloc[-1] == sig["prev_20d_high"].iloc[-1]
    _, trades = backtest_turtle_crypto(df, p)
    assert isinstance(trades, list)
