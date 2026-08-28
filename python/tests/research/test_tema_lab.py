"""TEMA lab: daily marks, isolated rescale, lagged Carver sizer, window seed."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.trend_lab.protocol import SPLIT, WARMUP_BARS, split_frame
from research.trend_lab.tema_carver import (
    carver_held_daily,
    daily_last_close,
    filter_trades,
    is_scale_ref,
    sized_trades,
)
from research.trend_lab.tema_robust import seed_window, trades_in_window
from research.trend_lab.tema_system import (
    TemaParams,
    compound_trades,
    daily_equity,
    rescale_trades,
    tema_bar_equity,
    tema_trades,
)


def _ohlcv(n: int, *, start: str, freq: str, close: np.ndarray) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.002
    low = np.minimum(open_, close) * 0.998
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1_000.0},
        index=idx,
    )


def _trend_4h(n: int = 900) -> pd.DataFrame:
    close = np.linspace(100.0, 220.0, n) + 0.4 * np.sin(np.linspace(0, 18, n))
    return _ohlcv(n, start="2020-01-01", freq="4h", close=close)


def test_rescale_linear_and_isolated_cap():
    n = 400
    up = np.linspace(100.0, 180.0, n - 6)
    crash = np.array([180.0, 170.0, 140.0, 130.0, 125.0, 120.0])
    df = _ohlcv(n, start="2020-06-01", freq="4h", close=np.concatenate([up, crash]))
    df.iloc[-4:, df.columns.get_loc("low")] = df["close"].iloc[-4:].to_numpy() * 0.88
    p = TemaParams(leverage=10.0, stake=100.0, min_adx=0.0, min_atr_pct=0.0, max_atr_pct=50.0, tp_atr=9.0)
    tr = tema_trades(df, p)
    assert not tr.empty
    doubled = rescale_trades(tr, 2.0, base_stake=p.stake, leverage=p.leverage, cost_bps=p.cost_bps)
    # winners scale ~2x; losers still capped at the new stake
    assert (doubled["pnl"] >= -2.0 * p.stake - 1e-6).all()
    assert float(doubled["stake"].iloc[0]) == pytest.approx(200.0)


def test_compound_first_stake_is_risk_frac():
    idx = pd.date_range("2021-01-01", periods=3, freq="D", tz="UTC")
    trades = pd.DataFrame({
        "entry_time": idx,
        "exit_time": idx,
        "ret": [0.01, -0.02, 0.00],
        "pnl": [10.0, -20.0, 0.0],
        "outcome": ["TP", "SL", "TIME"],
        "liquidated": [False, False, False],
        "r": [0.5, -1.0, 0.0],
        "bars": [2, 2, 2],
    })
    out = compound_trades(trades, start_eq=10_000.0, risk_frac=0.01, leverage=10.0, cost_bps=0.0)
    assert float(out["stake"].iloc[0]) == pytest.approx(100.0)
    # 10x * 1% ret on $100 stake = +$10, no costs
    assert float(out["pnl"].iloc[0]) == pytest.approx(10.0)
    assert float(out["equity"].iloc[0]) == pytest.approx(10_010.0)


def test_daily_equity_is_last_of_day():
    idx = pd.date_range("2021-06-01", periods=12, freq="4h", tz="UTC")
    eq = pd.Series(np.arange(12, dtype=float) + 100.0, index=idx)
    d = daily_equity(eq)
    assert len(d) >= 2
    # first day last 4h bar is the day's mark
    day0 = idx[0].normalize()
    last0 = eq.loc[eq.index.normalize() == day0].iloc[-1]
    assert float(d.iloc[0]) == pytest.approx(float(last0))


def test_daily_last_close_uses_bar_timestamp_not_midnight():
    df = _trend_4h(48)
    last = daily_last_close(df)
    assert len(last)
    # midnight-only labels would all have hour==0; last-bar labels are the 4h print
    assert int((last.index.hour != 0).sum()) >= 1 or int((df.index.hour == 0).all())


def test_carver_held_is_lagged_and_causal():
    df = _trend_4h(1200)
    h1, _, _ = carver_held_daily(df)
    assert float(h1.iloc[0]) == 0.0
    df2 = df.copy()
    df2.iloc[-1, df2.columns.get_loc("close")] = float(df2["close"].iloc[-1]) * 1.8
    h2, _, _ = carver_held_daily(df2)
    # last 4h close cannot affect lagged daily held on earlier days
    cut = df.index[-48]  # ~8 days before last print
    a = h1.loc[:cut]
    b = h2.loc[:cut]
    pd.testing.assert_series_equal(a, b, check_names=False)


def test_sized_trades_lookup_is_asof_not_future():
    idx = pd.date_range("2021-01-01", periods=6, freq="D", tz="UTC")
    trades = pd.DataFrame({
        "entry_time": [idx[3]],
        "exit_time": [idx[4]],
        "ret": [0.01],
        "pnl": [10.0],
        "outcome": ["TP"],
        "liquidated": [False],
        "r": [0.4],
        "bars": [2],
    })
    held = pd.Series([0.0, 0.0, 0.4, 0.8, 1.0, 1.0], index=idx)
    # asof at idx[3] sees 0.8; a future 1.0 must not leak
    out = sized_trades(
        trades, held, base_stake=100.0, leverage=10.0, cost_bps=0.0, ref=0.4, max_scale=5.0,
    )
    assert float(out["scale"].iloc[0]) == pytest.approx(2.0)  # 0.8 / 0.4


def test_is_scale_ref_ignores_oos_entries():
    idx = pd.date_range("2021-01-01", periods=10, freq="D", tz="UTC")
    held = pd.Series(np.linspace(0.1, 1.0, 10), index=idx)
    ref = is_scale_ref(held, idx[:3], floor=0.01)
    assert ref == pytest.approx(float(held.iloc[:3].mean()))
    ref2 = is_scale_ref(held, idx, floor=0.01)
    assert ref2 > ref


def test_filter_trades_uses_lagged_held():
    idx = pd.date_range("2021-01-01", periods=4, freq="D", tz="UTC")
    trades = pd.DataFrame({
        "entry_time": idx,
        "exit_time": idx,
        "ret": [0.0] * 4,
        "pnl": [0.0] * 4,
        "outcome": ["TIME"] * 4,
        "liquidated": [False] * 4,
        "r": [0.0] * 4,
        "bars": [1] * 4,
    })
    held = pd.Series([0.0, 0.02, 0.2, 0.3], index=idx)
    kept = filter_trades(trades, held, min_held=0.1)
    assert len(kept) == 2
    assert list(kept["entry_time"]) == [idx[2], idx[3]]


def test_seed_window_does_not_include_future_bars():
    df = _trend_4h(2000)
    start = pd.Timestamp("2020-06-01", tz="UTC")
    end = pd.Timestamp("2020-06-30", tz="UTC")
    seeded, idx = seed_window(df, start, end)
    assert seeded.index.max() <= end + pd.Timedelta(days=1)
    assert idx.max() <= df.loc[start:end].index.max()
    assert len(seeded) >= WARMUP_BARS
    # prefix is strictly before start
    prefix = seeded.loc[: start - pd.Timedelta(milliseconds=1)]
    assert prefix.index.max() < start


def test_trades_in_window_entries_inside_oos_only():
    df = _trend_4h(2500)
    p = TemaParams(min_adx=0.0, min_atr_pct=0.0, max_atr_pct=50.0)
    tr, idx = trades_in_window(df, "2020-04-01", "2020-06-01", p)
    if tr.empty:
        pytest.skip("synthetic path produced no TEMA trades")
    assert (tr["entry_time"] >= pd.Timestamp("2020-04-01", tz="UTC")).all()
    assert (tr["entry_time"] <= pd.Timestamp("2020-06-02", tz="UTC")).all()
    assert idx.min() >= pd.Timestamp("2020-04-01", tz="UTC")
