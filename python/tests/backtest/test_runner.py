"""Tests for backtest.runner outcome evaluation."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backtest.runner import _evaluate_outcome, run_backtest, results_to_dataframe


def _make_flat_df(n: int, price: float = 100.0, freq: str = "1h") -> pd.DataFrame:
    """Flat OHLCV: all bars same price, high+0.5, low-0.5."""
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({
        "open": price, "high": price + 0.5, "low": price - 0.5,
        "close": price, "volume": 1000.0,
    }, index=idx)


class TestEvaluateOutcome:
    def test_buy_win_when_high_hits_tp_first(self):
        df = _make_flat_df(20)
        df.iloc[5, df.columns.get_loc("high")] = 110.0
        outcome, bars, mae_r, mfe_r = _evaluate_outcome(df, signal_idx=0, side="BUY",
                                                        entry=100.0, take_profit=105.0, stop_loss=95.0)
        assert outcome == "WIN"
        assert bars == 5

    def test_buy_loss_when_low_hits_sl_first(self):
        df = _make_flat_df(20)
        df.iloc[3, df.columns.get_loc("low")] = 90.0
        outcome, bars, mae_r, mfe_r = _evaluate_outcome(df, signal_idx=0, side="BUY",
                                                        entry=100.0, take_profit=105.0, stop_loss=95.0)
        assert outcome == "LOSS"
        assert bars == 3

    def test_buy_open_when_neither_hit(self):
        df = _make_flat_df(20)
        outcome, bars, mae_r, mfe_r = _evaluate_outcome(df, signal_idx=0, side="BUY",
                                                        entry=100.0, take_profit=200.0, stop_loss=1.0,
                                                        max_lookahead=10)
        assert outcome == "OPEN"
        assert bars is None

    def test_sell_win_when_low_hits_tp_first(self):
        df = _make_flat_df(20)
        df.iloc[4, df.columns.get_loc("low")] = 85.0
        outcome, bars, mae_r, mfe_r = _evaluate_outcome(df, signal_idx=0, side="SELL",
                                                        entry=100.0, take_profit=90.0, stop_loss=110.0)
        assert outcome == "WIN"
        assert bars == 4

    def test_sell_loss_when_high_hits_sl_first(self):
        df = _make_flat_df(20)
        df.iloc[2, df.columns.get_loc("high")] = 115.0
        outcome, bars, mae_r, mfe_r = _evaluate_outcome(df, signal_idx=0, side="SELL",
                                                        entry=100.0, take_profit=90.0, stop_loss=110.0)
        assert outcome == "LOSS"
        assert bars == 2

    def test_both_hit_same_bar_is_loss(self):
        df = _make_flat_df(20)
        df.iloc[1, df.columns.get_loc("high")] = 200.0
        df.iloc[1, df.columns.get_loc("low")] = 1.0
        outcome, bars, mae_r, mfe_r = _evaluate_outcome(df, signal_idx=0, side="BUY",
                                                        entry=100.0, take_profit=150.0, stop_loss=50.0)
        assert outcome == "LOSS"
        assert bars == 1

    def test_respects_max_lookahead(self):
        df = _make_flat_df(200)
        outcome, bars, mae_r, mfe_r = _evaluate_outcome(df, signal_idx=0, side="BUY",
                                                        entry=100.0, take_profit=200.0, stop_loss=1.0,
                                                        max_lookahead=5)
        assert outcome == "OPEN"
        assert bars is None

    def test_signal_at_end_of_df_returns_open(self):
        df = _make_flat_df(5)
        outcome, bars, mae_r, mfe_r = _evaluate_outcome(df, signal_idx=4, side="BUY",
                                                        entry=100.0, take_profit=200.0, stop_loss=1.0)
        assert outcome == "OPEN"
        assert bars is None


def test_results_to_dataframe_empty():
    df = results_to_dataframe([])
    assert isinstance(df, pd.DataFrame)
    assert "outcome" in df.columns
    assert len(df) == 0


def test_results_to_dataframe_schema():
    from backtest.runner import BacktestResult
    r = BacktestResult(
        symbol="BTCUSDT", timeframe="1h",
        timestamp=pd.Timestamp("2024-01-01", tz="UTC"),
        side="BUY", grade="A", score=85.0, daily_trend="bullish",
        entry=100.0, stop_loss=95.0, take_profit=110.0, atr_pct=1.5, adx_value=28.0,
        outcome="WIN", bars_to_outcome=3,
        rr_ratio=1.5, realized_r=1.5, mae_r=-0.2, mfe_r=1.8,
    )
    df = results_to_dataframe([r])
    assert len(df) == 1
    assert df["outcome"].iloc[0] == "WIN"
    assert df["bars_to_outcome"].iloc[0] == 3
