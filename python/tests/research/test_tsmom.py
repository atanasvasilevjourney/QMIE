"""SIGN TSMOM helpers — synthetic bars, no network."""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.trend_lab.protocol import assert_no_lookahead
from research.trend_lab.tsmom import (
    backtest_single,
    sign_weights_daily,
    sign_weights_monthly_lamberti,
)


def _close(n: int = 500, *, drift: float = 0.001) -> pd.Series:
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    r = drift + 0.02 * np.random.default_rng(0).standard_normal(n)
    px = 100.0 * np.cumprod(1.0 + r)
    return pd.Series(px, index=idx, name="close")


def test_sign_long_in_uptrend():
    close = _close(400, drift=0.002)
    w = sign_weights_daily(close, lookback=30, ewm_span=10, long_only=True)
    assert (w.iloc[-50:] > 0).mean() > 0.8


def test_backtest_respects_exec_lag():
    close = _close(200)
    w = sign_weights_daily(close, lookback=30, ewm_span=10)
    bt = backtest_single(close, w, exec_lag=1)
    assert_no_lookahead(w, bt["held"])


def test_monthly_weights_step_on_month_end():
    close = _close(400)
    w = sign_weights_monthly_lamberti(close, lookback=30, ewm_span=10)
    changes = w.diff().abs()
    # Most days flat; some month boundaries move
    assert (changes == 0).mean() > 0.9
    assert (changes > 0).sum() >= 3
