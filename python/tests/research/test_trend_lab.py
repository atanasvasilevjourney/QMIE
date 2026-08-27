"""Trend-lab protocol: no lookahead, isolated 10x cap, IS/OOS split, Donchian prior-window."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.trend_lab.allocation import blend_weights, chop_gate, ranked_spot_book
from research.trend_lab.carver import dd_circuit_breaker
from research.trend_lab.features import donchian, feature_frame, kama
from research.trend_lab.metrics import kpis, max_dd
from research.trend_lab.optimize import neighbor_set, trend_label
from research.trend_lab.protocol import (
    SPLIT,
    WARMUP_BARS,
    ProtocolError,
    assert_no_lookahead,
    inner_validation_start,
    split_frame,
)
from research.trend_lab.spot_system import SpotParams, spot_signal
from research.trend_lab.tema_system import TemaParams, tema_bar_equity, tema_trades


def _ohlcv(n: int, *, start: str, freq: str, close: np.ndarray) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.002
    low = np.minimum(open_, close) * 0.998
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1_000.0},
        index=idx,
    )


def _bull(n: int = 800, start: str = "2019-09-01", freq: str = "1D") -> pd.DataFrame:
    close = np.linspace(100.0, 280.0, n) + 0.15 * np.sin(np.linspace(0, 12, n))
    return _ohlcv(n, start=start, freq=freq, close=close)


def test_split_is_before_oos_and_warmup_seeded():
    df = _bull(1400)
    parts = split_frame(df)
    assert parts["is"].index.max() < parts["oos"].index.min()
    assert parts["is"].index.min() >= pd.Timestamp(SPLIT.is_start, tz="UTC")
    assert len(parts["is"]) > WARMUP_BARS
    seed = parts["oos_seeded"].iloc[:WARMUP_BARS]
    assert seed.index.max() <= parts["is"].index.max()
    assert seed.index.min() >= parts["is"].index.min()


def test_requested_split_is_inverted_and_rejected_as_fit():
    assert SPLIT.is_end < SPLIT.oos_start
    assert "future" in SPLIT.requested_note.lower() or "chronological" in SPLIT.requested_note.lower()


def test_inner_validation_is_inside_is():
    df = _bull(900)
    parts = split_frame(df)
    cut = inner_validation_start(parts["is"].index, frac=0.2)
    assert parts["is"].index[0] < cut <= parts["is"].index[-1]
    assert cut < pd.Timestamp(SPLIT.oos_start, tz="UTC")


def test_held_is_signal_shifted():
    fr = spot_signal(_bull(), SpotParams(min_adx=0.0, rsi_max=100.0, donchian=10))
    assert_no_lookahead(fr["signal"], fr["held"])
    bad = fr["held"].copy()
    # force a same-bar leak on a bar that exists
    i = min(30, len(bad) - 1)
    bad.iloc[i] = 1.0 - float(bad.iloc[i])
    with pytest.raises(ProtocolError):
        assert_no_lookahead(fr["signal"], bad)


def test_donchian_excludes_current_bar():
    df = _bull(80).copy()
    df.iloc[-1, df.columns.get_loc("high")] = df["high"].iloc[-2] * 5
    don = donchian(df, 20)
    assert don["donch_high"].iloc[-1] == pytest.approx(float(df["high"].iloc[-21:-1].max()))
    assert don["donch_high"].iloc[-1] < df["high"].iloc[-1]


def test_kama_does_not_use_future_bars():
    s = pd.Series(np.linspace(1, 2, 80), index=pd.date_range("2020-01-01", periods=80, freq="D", tz="UTC"))
    k1, _ = kama(s, n=10)
    s2 = s.copy()
    s2.iloc[-1] = 9.0
    k2, _ = kama(s2, n=10)
    assert k1.iloc[:-1].equals(k2.iloc[:-1])
    assert k1.iloc[-1] != k2.iloc[-1]


def test_feature_frame_causal_columns():
    df = _bull(400)
    feats = feature_frame(df)
    assert "tma_agree" in feats and "macd_hist" in feats and "kama_cross" in feats
    assert "fwd" not in feats.columns
    y = trend_label(df["close"], horizon=10)
    assert pd.isna(y.iloc[-1])


def test_isolated_10x_caps_loss_at_stake():
    n = 280
    up = np.linspace(100.0, 160.0, n - 4)
    crash = np.array([160.0, 150.0, 130.0, 120.0])
    close = np.concatenate([up, crash])
    df = _ohlcv(n, start="2020-01-01", freq="4h", close=close)
    df.iloc[-3:, df.columns.get_loc("low")] = df["close"].iloc[-3:].to_numpy() * 0.90
    p = TemaParams(
        leverage=10.0, stake=100.0, min_adx=0.0, min_atr_pct=0.0,
        max_atr_pct=50.0, sl_atr=1.5, tp_atr=9.0,
    )
    trades = tema_trades(df, p)
    assert not trades.empty
    assert (trades["pnl"] >= -p.stake - 1e-6).all()
    assert (trades["outcome"].isin(["SL", "TIME"]) | trades["liquidated"]).any()


def test_tema_bar_equity_books_pnl_at_exit():
    idx = pd.date_range("2021-01-01", periods=5, freq="D", tz="UTC")
    trades = pd.DataFrame({"exit_time": [idx[2]], "pnl": [50.0], "liquidated": [False]})
    bar = tema_bar_equity(idx, trades, start_eq=10_000)
    assert bar["equity"].iloc[1] == 10_000
    assert bar["equity"].iloc[2] == 10_050
    assert bar["equity"].iloc[-1] == 10_050


def test_dd_circuit_breaker_is_causal():
    idx = pd.date_range("2021-01-01", periods=6, freq="D", tz="UTC")
    eq = pd.Series([100, 110, 90, 91, 95, 96], index=idx)
    w = pd.Series(1.0, index=idx)
    out = dd_circuit_breaker(w, eq, trip=-0.12, recover=-0.06, cut=0.25)
    assert out.iloc[0] == 1.0
    assert out.iloc[3] == pytest.approx(0.25)


def test_ranked_book_lags_weights():
    idx = pd.date_range("2021-01-01", periods=80, freq="D", tz="UTC")
    close = pd.DataFrame({
        "BTCUSDT": np.linspace(100, 200, 80),
        "ETHUSDT": np.linspace(50, 80, 80),
        "SOLUSDT": np.linspace(10, 40, 80),
    }, index=idx)
    held = pd.DataFrame(1.0, index=idx, columns=close.columns)
    book = ranked_spot_book(close, held, lookback=10, top_n=2, exec_lag=1)
    assert float(book["n_names"].iloc[0]) == 0.0
    assert book["equity"].iloc[-1] > 1.0


def test_blend_and_chop_shapes():
    df = _bull(300)
    gate = chop_gate(df, min_adx=10.0)
    assert gate.between(0, 1).all()
    mix = blend_weights(pd.Series(0.4, index=df.index), pd.Series(1.0, index=df.index), mix=0.5)
    assert mix.iloc[-1] == pytest.approx(0.7)


def test_neighbor_set_includes_center():
    c = {"ema_fast": 9.0, "ema_slow": 199.0}
    ns = neighbor_set(c, {"ema_fast": [8.0, 10.0], "ema_slow": [199.0]})
    assert c in ns
    assert len(ns) == 3


def test_kpis_empty_safe():
    empty = pd.Series(dtype=float)
    k = kpis(empty, empty)
    assert k["bars"] == 0 or np.isnan(k["sharpe"])
    assert np.isnan(max_dd(empty))
