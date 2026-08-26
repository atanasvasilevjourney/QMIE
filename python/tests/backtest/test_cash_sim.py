"""Paper cash replay of 4h A/A+ (no network, no W_*)."""
from __future__ import annotations

import pandas as pd

from backtest.cash_sim import first_per_symbol_day, simulate


def _trades() -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=4, freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "symbol": ["BTCUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"],
            "timestamp": idx,
            "exit_ts": idx + pd.Timedelta(hours=12),
            "entry": [100.0, 100.0, 100.0, 100.0],
            "stop_loss": [98.5, 98.5, 98.5, 98.5],
            "realized_r": [1.667, -1.0, 1.667, -1.0],
            "outcome": ["WIN", "LOSS", "WIN", "LOSS"],
            "risk_pct": [0.015, 0.015, 0.015, 0.015],
            "grade": ["A", "A", "A+", "A"],
            "score": [80.0, 82.0, 91.0, 70.0],
            "atr_pct": [1.0, 1.0, 1.0, 1.0],
            "adx_value": [25.0, 25.0, 25.0, 25.0],
            "bars_to_outcome": [3, 3, 3, 3],
        }
    )


def test_fifo_takes_while_cash_lasts():
    t = _trades()
    sim = simulate(t, start_cash=200.0, stake=100.0, one_per_symbol=False, max_slots=2)
    assert sim["taken"] >= 2
    assert sim["open_left"] == 0
    assert abs(sim["final"] - (sim["start"] + sim["pnl"])) < 1e-9


def test_one_per_symbol_skips_second_btc():
    t = _trades()
    sim = simulate(t, start_cash=1000.0, stake=100.0, one_per_symbol=True)
    taken = sim["taken_rows"]
    assert (taken["symbol"] == "BTCUSDT").sum() == 1
    assert sim["skipped"] >= 1


def test_pnl_matches_formula():
    t = _trades().iloc[[0]].copy()
    sim = simulate(t, start_cash=1000.0, stake=100.0)
    expect = 100.0 * 1.667 * 0.015
    assert sim["taken"] == 1
    assert abs(sim["pnl"] - expect) < 1e-9
    assert abs(sim["final"] - (1000.0 + expect)) < 1e-9


def test_max_slots_caps_concurrent():
    t = _trades()
    sim = simulate(t, start_cash=1000.0, stake=100.0, max_slots=1)
    assert sim["max_open"] <= 1
    assert sim["skipped"] >= 1


def test_first_per_symbol_day_keeps_one():
    t = _trades()
    t.loc[2, "timestamp"] = t.loc[0, "timestamp"] + pd.Timedelta(hours=4)
    t.loc[2, "exit_ts"] = t.loc[2, "timestamp"] + pd.Timedelta(hours=12)
    out = first_per_symbol_day(t)
    assert (out["symbol"] == "BTCUSDT").sum() == 1


def test_isolated_25x_caps_loss_at_margin():
    t = _trades().iloc[[1]].copy()
    t["risk_pct"] = 0.06  # 1R = 6% of notional > $100 at 25x
    t["realized_r"] = -1.0
    sim = simulate(t, start_cash=1000.0, stake=100.0, leverage=25.0)
    assert sim["taken"] == 1
    assert sim["liquidations"] == 1
    assert abs(sim["pnl"] + 100.0) < 1e-9


def test_25x_win_scales_notional():
    t = _trades().iloc[[0]].copy()
    sim = simulate(t, start_cash=1000.0, stake=100.0, leverage=25.0)
    expect = 100.0 * 25.0 * 1.667 * 0.015
    assert abs(sim["pnl"] - expect) < 1e-6


def test_rank_score_fills_best_when_slots_are_3():
    ts = pd.Timestamp("2025-06-01", tz="UTC")
    t = pd.DataFrame(
        {
            "symbol": [f"S{i}USDT" for i in range(5)],
            "timestamp": [ts] * 5,
            "exit_ts": [ts + pd.Timedelta(hours=8)] * 5,
            "entry": [100.0] * 5,
            "stop_loss": [98.5] * 5,
            "realized_r": [1.667] * 5,
            "outcome": ["WIN"] * 5,
            "risk_pct": [0.015] * 5,
            "grade": ["A", "A", "A+", "A", "A"],
            "score": [80.0, 84.0, 93.0, 70.0, 88.0],
            "atr_pct": [1.0] * 5,
            "adx_value": [25.0] * 5,
            "bars_to_outcome": [2] * 5,
        }
    )
    sim = simulate(
        t, start_cash=1000.0, stake=100.0, max_slots=3, rank_by_score=True
    )
    assert sim["max_open"] == 3
    assert sim["taken"] == 3
    assert sim["skipped"] == 2
    taken_scores = sorted(sim["taken_rows"]["score"].tolist(), reverse=True)
    assert taken_scores == [93.0, 88.0, 84.0]


def test_cannot_open_fourth_until_one_closes():
    ts = pd.Timestamp("2025-06-01", tz="UTC")
    t = pd.DataFrame(
        {
            "symbol": ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"],
            "timestamp": [ts, ts, ts, ts + pd.Timedelta(hours=4)],
            "exit_ts": [ts + pd.Timedelta(hours=12)] * 3 + [ts + pd.Timedelta(hours=16)],
            "entry": [100.0] * 4,
            "stop_loss": [98.5] * 4,
            "realized_r": [1.667] * 4,
            "outcome": ["WIN"] * 4,
            "risk_pct": [0.015] * 4,
            "grade": ["A"] * 4,
            "score": [90.0, 89.0, 88.0, 99.0],
            "atr_pct": [1.0] * 4,
            "adx_value": [25.0] * 4,
            "bars_to_outcome": [3] * 4,
        }
    )
    sim = simulate(
        t, start_cash=1000.0, stake=100.0, max_slots=3, rank_by_score=True
    )
    assert sim["max_open"] <= 3
    # 4th fires while 3 still open (exit at +12h, 4th open at +4h)
    assert sim["taken"] == 3
    assert sim["skipped"] == 1
