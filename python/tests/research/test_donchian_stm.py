"""Donchian STM research: prior window, exec lag, pessimistic stops."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.trend_lab.donchian_stm import (
    DonchianStmParams,
    Side,
    backtest_donchian_stm,
    breakeven_win_rate,
    donchian_signals,
    trade_attribution,
    wilson_ci,
)
from research.trend_lab.features import donchian


def _ohlcv(closes: np.ndarray) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=len(closes), freq="D", tz="UTC")
    open_ = np.concatenate([[closes[0]], closes[:-1]])
    high = np.maximum(open_, closes) * 1.01
    low = np.minimum(open_, closes) * 0.99
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": closes, "volume": 1e3},
        index=idx,
    )


def test_donchian_signals_use_prior_window():
    closes = np.linspace(100, 150, 80)
    df = _ohlcv(closes)
    df.iloc[-1, df.columns.get_loc("high")] = 500.0
    sig = donchian_signals(df, DonchianStmParams(entry_lookback=10))
    don = donchian(df, 10)
    assert sig["donch_high"].iloc[-1] == pytest.approx(float(don["donch_high"].iloc[-1]))
    assert float(sig["close"].iloc[-1]) <= float(sig["donch_high"].iloc[-1]) or sig["signal"].iloc[-1] != 1


def test_entry_happens_after_signal_bar():
    closes = np.full(40, 100.0)
    closes[-1] = 120.0
    df = _ohlcv(closes)
    p = DonchianStmParams(entry_lookback=5, atr_stop_mult=5.0, trail_atr_mult=None, max_hold_bars=5)
    _, trades = backtest_donchian_stm(df, p)
    if trades:
        assert trades[0].entry_time > df.index[-2]


def test_gap_through_stop_fills_worse_than_stop_level():
    # Breakout on signal bar; enter next open; following bar gaps through stop.
    n = 35
    closes = np.linspace(100, 104, n)
    df = _ohlcv(closes)
    sig_i = n - 3
    ent_i = n - 2
    gap_i = n - 1
    df.iloc[sig_i, df.columns.get_loc("close")] = 200.0
    df.iloc[ent_i, df.columns.get_loc("open")] = 100.0
    df.iloc[ent_i, df.columns.get_loc("high")] = 102.0
    df.iloc[ent_i, df.columns.get_loc("low")] = 99.0
    df.iloc[ent_i, df.columns.get_loc("close")] = 101.0
    df.iloc[gap_i, df.columns.get_loc("open")] = 40.0
    df.iloc[gap_i, df.columns.get_loc("low")] = 35.0
    df.iloc[gap_i, df.columns.get_loc("high")] = 45.0
    df.iloc[gap_i, df.columns.get_loc("close")] = 42.0
    p = DonchianStmParams(entry_lookback=5, atr_stop_mult=2.0, trail_atr_mult=None, max_hold_bars=10)
    _, trades = backtest_donchian_stm(df, p)
    assert trades, "expected a stopped trade"
    t = trades[-1]
    assert t.side is Side.LONG
    assert t.exit_reason == "gap_stop"
    assert t.exit_fill <= float(df["open"].iloc[gap_i]) * 1.001


def test_qmie_coil_mode_blocks_wide_box_breakout():
    closes = np.linspace(100, 110, 50)
    df = _ohlcv(closes)
    df.iloc[-1, df.columns.get_loc("close")] = 200.0
    turtle = donchian_signals(df, DonchianStmParams(entry_lookback=10, mode="turtle"))
    coil = donchian_signals(
        df, DonchianStmParams(entry_lookback=10, mode="qmie_coil", coil_max_width_pct=1.0)
    )
    assert int(turtle["signal"].iloc[-1]) != 0
    assert int(coil["signal"].iloc[-1]) == 0


def test_attribution_and_wilson():
    from research.trend_lab.donchian_stm import StmTrade

    ts = pd.Timestamp("2023-01-05", tz="UTC")
    trades = [
        StmTrade(Side.LONG, ts, ts, 100, 110, 95, "stop", 2.0, 0.1, 3, 0.5),
        StmTrade(Side.SHORT, ts, ts, 100, 105, 110, "stop", -1.0, -0.05, 2, 0.5),
    ]
    att = trade_attribution(trades)
    assert att["long"]["n"] == 1
    assert att["short"]["n"] == 1
    lo, hi = wilson_ci(1, 2)
    assert 0 <= lo <= hi <= 1
    be = breakeven_win_rate(np.array([2.0, -1.0]))
    assert 0 < be < 1
