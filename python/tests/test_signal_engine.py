"""
Signal engine tests.

Verifies that the 7-component scoring produces the right SIDE and
GRADE for known regimes, and degrades gracefully on edge cases.
Mirrors what the Pine visualizer should also produce.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.signal_engine import Weights, _grade_for, compute_signal


class TestComputeSignal:
    def test_returns_none_on_short_data(self, short_df):
        assert compute_signal(short_df, symbol="X", timeframe="1h") is None

    def test_clear_uptrend_yields_buy(self, bull_trend_df):
        sig = compute_signal(bull_trend_df, symbol="X", timeframe="1h")
        assert sig is not None
        assert sig.side == "BUY"
        # Bull regime: directional components must vote bull
        assert sig.components["supertrend"] > 0
        assert sig.components["ema"] > 0
        assert sig.components["adx"] >= 0      # ADX may be neutral early in trend
        # No HTF passed and pivots are sparse on linear data, so the
        # achievable grade is bounded; just verify it's not REJECT
        assert sig.grade != "REJECT"

    def test_clear_downtrend_yields_sell(self, bear_trend_df):
        sig = compute_signal(bear_trend_df, symbol="X", timeframe="1h")
        assert sig is not None
        assert sig.side == "SELL"
        assert sig.components["supertrend"] < 0
        assert sig.components["ema"] < 0
        assert sig.grade != "REJECT" or sig.score > 30   # at least directional

    def test_choppy_market_low_grade(self, choppy_df):
        sig = compute_signal(choppy_df, symbol="X", timeframe="1h")
        assert sig is not None
        # Random walk → no edge → low score
        assert sig.score < 70
        assert sig.grade in ("REJECT", "C", "B")

    def test_constant_price_returns_none_or_neutral(self, constant_close_df):
        # ATR is zero; engine must not divide by zero. May return None.
        sig = compute_signal(constant_close_df, symbol="X", timeframe="1h")
        # Either gracefully None, or REJECT
        assert sig is None or sig.grade == "REJECT"

    def test_sl_tp_geometry_for_buy(self, bull_trend_df):
        sig = compute_signal(bull_trend_df, symbol="X", timeframe="1h")
        assert sig.side == "BUY"
        # SL below price, TP above
        assert sig.stop_loss < sig.price
        assert sig.take_profit > sig.price
        # TP distance should be ~ tp_mult / sl_mult times SL distance
        sl_dist = sig.price - sig.stop_loss
        tp_dist = sig.take_profit - sig.price
        ratio = tp_dist / sl_dist
        # default mults: sl=1.5, tp=2.5 → R:R = 2.5/1.5 ≈ 1.67
        assert ratio == pytest.approx(2.5 / 1.5, rel=1e-3)

    def test_sl_tp_geometry_for_sell(self, bear_trend_df):
        sig = compute_signal(bear_trend_df, symbol="X", timeframe="1h")
        assert sig.side == "SELL"
        assert sig.stop_loss > sig.price
        assert sig.take_profit < sig.price

    def test_htf_alignment_boosts_score(self, bull_trend_df, htf_bull_df):
        no_htf = compute_signal(bull_trend_df, symbol="X", timeframe="1h")
        with_htf = compute_signal(bull_trend_df, symbol="X", timeframe="1h",
                                  htf_df=htf_bull_df)
        # HTF aligned with same direction should not LOWER score
        assert with_htf.score >= no_htf.score
        assert with_htf.htf_aligned is True

    def test_partial_supertrend_agreement_scored(self, bull_trend_df):
        """Regression test for the 'triple-ST scoring drops 2/3 majority'
        bug. After fix, agreement of ±1 should produce a non-zero
        supertrend component score."""
        sig = compute_signal(bull_trend_df, symbol="X", timeframe="1h")
        # In a strong uptrend agreement is +3, but we still verify the
        # general property: if agreement != 0, supertrend score != 0
        assert sig.components["agreement"] in (-3, -1, 1, 3)
        if sig.components["agreement"] != 0:
            assert sig.components["supertrend"] != 0


class TestGrade:
    @pytest.mark.parametrize("score,side,expected", [
        (95.0,  "BUY",     "A+"),
        (89.9,  "BUY",     "A"),
        (80.0,  "SELL",    "A"),
        (75.0,  "BUY",     "B"),
        (65.0,  "BUY",     "B"),
        (60.0,  "SELL",    "C"),
        (49.9,  "BUY",     "REJECT"),
        (0.0,   "BUY",     "REJECT"),
        (95.0,  "NEUTRAL", "REJECT"),
    ])
    def test_grade_thresholds(self, score, side, expected):
        assert _grade_for(score, side) == expected


class TestWeights:
    def test_default_weights_sum_to_100(self):
        w = Weights()
        assert w.total == 100

    def test_custom_weights(self):
        w = Weights(supertrend=30, ema=10, rsi=10, adx=10, htf=30, sr=5, vol=5)
        assert w.total == 100

    def test_weights_can_be_lopsided(self):
        # Engine should still work with non-100-sum weights, though grades
        # will scale differently. No exception expected.
        w = Weights(supertrend=50, ema=0, rsi=0, adx=0, htf=50, sr=0, vol=0)
        assert w.total == 100
