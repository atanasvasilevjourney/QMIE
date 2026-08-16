"""
Indicator math correctness tests.

Each test pins behaviour against either:
  * a hand-computed reference value
  * a known monotonic / structural property
  * direct Pine-equivalent recurrence

Float tolerances are tight (1e-6 for math, 1e-3 for ATR/RSI/ADX
because those involve Wilders smoothing on noisy inputs).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.indicators import (
    SRZones, adx, atr, ema, nearest_sr_distance, pivots,
    recent_sr_zones, rma, rsi, supertrend, triple_supertrend_dir,
    true_range,
)


# ════════════════════════════════════════════════════════════════════════
#  RMA — must match Pine's SMA-seeded recurrence exactly
# ════════════════════════════════════════════════════════════════════════
class TestRMA:
    def test_pine_seed_is_sma_of_first_window(self):
        x = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
        out = rma(x, 3)
        # First two values must be NaN (warmup)
        assert pd.isna(out.iloc[0])
        assert pd.isna(out.iloc[1])
        # Index 2 = SMA of [10, 12, 14] = 12.0
        assert out.iloc[2] == pytest.approx(12.0, abs=1e-9)

    def test_recurrence_matches_pine(self):
        # alpha = 1/3, so y[3] = (1/3)*16 + (2/3)*12 = 5.333 + 8 = 13.333
        x = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
        out = rma(x, 3)
        assert out.iloc[3] == pytest.approx(13.3333333, abs=1e-6)
        # y[4] = (1/3)*18 + (2/3)*13.333 = 6 + 8.889 = 14.889
        assert out.iloc[4] == pytest.approx(14.88888889, abs=1e-6)

    def test_short_input_returns_all_nan(self):
        out = rma(pd.Series([1.0, 2.0]), 14)
        assert out.isna().all()

    def test_invalid_length_raises(self):
        with pytest.raises(ValueError):
            rma(pd.Series([1.0]), 0)
        with pytest.raises(ValueError):
            rma(pd.Series([1.0]), -3)


# ════════════════════════════════════════════════════════════════════════
#  EMA — uses pandas span, alpha = 2/(n+1)
# ════════════════════════════════════════════════════════════════════════
class TestEMA:
    def test_constant_series_yields_constant(self):
        out = ema(pd.Series([100.0] * 50), 10)
        # After warmup, all values must equal the constant
        assert out.iloc[10:].dropna().eq(100.0).all()

    def test_ema_responds_faster_than_rma(self):
        # EMA alpha = 2/15 ≈ 0.133 ; RMA alpha = 1/14 ≈ 0.071
        # Step input → EMA should be closer to new value.
        x = pd.Series([0.0] * 30 + [100.0] * 30)
        ema_out = ema(x, 14)
        rma_out = rma(x, 14)
        # 5 bars after the step
        assert ema_out.iloc[35] > rma_out.iloc[35]


# ════════════════════════════════════════════════════════════════════════
#  ATR — RMA(true_range)
# ════════════════════════════════════════════════════════════════════════
class TestATR:
    def test_zero_volatility_zero_atr(self):
        n = 50
        df = pd.DataFrame({
            "open": [100.0] * n, "high": [100.0] * n,
            "low": [100.0] * n, "close": [100.0] * n,
            "volume": [1.0] * n,
        }, index=pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"))
        a = atr(df, 14)
        assert a.iloc[14:].fillna(0).eq(0.0).all()

    def test_atr_positive_on_real_movement(self, bull_trend_df):
        a = atr(bull_trend_df, 14)
        last = a.iloc[-1]
        assert last > 0
        # Reasonable magnitude: ATR should be small relative to price
        last_close = bull_trend_df["close"].iloc[-1]
        assert last / last_close < 0.10           # ATR < 10% of price

    def test_true_range_handles_gap(self):
        # Bar with previous close 100, current low 90, current high 95:
        # TR = max(95-90, |95-100|, |90-100|) = 10
        df = pd.DataFrame({
            "open": [100.0, 95.0], "high": [100.0, 95.0],
            "low": [100.0, 90.0], "close": [100.0, 92.0],
            "volume": [1.0, 1.0],
        }, index=pd.date_range("2024-01-01", periods=2, freq="1h", tz="UTC"))
        tr = true_range(df)
        assert tr.iloc[1] == pytest.approx(10.0, abs=1e-9)


# ════════════════════════════════════════════════════════════════════════
#  RSI
# ════════════════════════════════════════════════════════════════════════
class TestRSI:
    def test_rsi_in_range_0_100(self, choppy_df):
        r = rsi(choppy_df["close"], 14).dropna()
        assert (r >= 0).all() and (r <= 100).all()

    def test_rsi_high_in_uptrend(self, bull_trend_df):
        # Pure uptrend → RSI should be above 50 most of the time after warmup
        r = rsi(bull_trend_df["close"], 14).dropna()
        last_quarter = r.iloc[-100:]
        assert last_quarter.mean() > 50

    def test_rsi_low_in_downtrend(self, bear_trend_df):
        r = rsi(bear_trend_df["close"], 14).dropna()
        last_quarter = r.iloc[-100:]
        assert last_quarter.mean() < 50


# ════════════════════════════════════════════════════════════════════════
#  ADX
# ════════════════════════════════════════════════════════════════════════
class TestADX:
    def test_adx_low_in_chop(self, choppy_df):
        _, _, ax = adx(choppy_df, 14)
        assert ax.iloc[-1] < 30      # chop should be sub-30 most of the time

    def test_adx_high_in_strong_trend(self, bull_trend_df):
        plus, minus, ax = adx(bull_trend_df, 14)
        # In a strong uptrend, ADX should rise > 20 and +DI > -DI
        assert ax.iloc[-1] > 20
        assert plus.iloc[-1] > minus.iloc[-1]

    def test_di_directionality(self, bear_trend_df):
        plus, minus, _ = adx(bear_trend_df, 14)
        assert minus.iloc[-1] > plus.iloc[-1]


# ════════════════════════════════════════════════════════════════════════
#  Supertrend
# ════════════════════════════════════════════════════════════════════════
class TestSupertrend:
    def test_uptrend_direction_is_plus_one(self, bull_trend_df):
        line, direction = supertrend(bull_trend_df, 3.0, 10)
        # In a clean uptrend, last 100 bars should mostly be direction=+1
        d = direction.iloc[-100:]
        assert (d == 1).sum() > 80

    def test_downtrend_direction_is_minus_one(self, bear_trend_df):
        line, direction = supertrend(bear_trend_df, 3.0, 10)
        d = direction.iloc[-100:]
        assert (d == -1).sum() > 80

    def test_st_line_below_price_in_uptrend(self, bull_trend_df):
        line, direction = supertrend(bull_trend_df, 3.0, 10)
        # Take the last 100 confirmed-uptrend bars
        bull_mask = direction.iloc[-100:] == 1
        bull_lines = line.iloc[-100:][bull_mask]
        bull_closes = bull_trend_df["close"].iloc[-100:][bull_mask]
        # ST line must always be below close in uptrend
        assert (bull_lines < bull_closes).all()


# ════════════════════════════════════════════════════════════════════════
#  Triple Supertrend
# ════════════════════════════════════════════════════════════════════════
class TestTripleSupertrend:
    def test_returns_six_values(self, bull_trend_df):
        out = triple_supertrend_dir(bull_trend_df)
        assert len(out) == 6
        d1, d2, d3, agree, line, dir_series = out
        assert d1 in (-1, 0, 1)
        assert agree in (-3, -1, 0, 1, 3)

    def test_agreement_matches_sum(self, bull_trend_df):
        d1, d2, d3, agree, _, _ = triple_supertrend_dir(bull_trend_df)
        assert agree == d1 + d2 + d3

    def test_strong_uptrend_full_agreement(self, bull_trend_df):
        _, _, _, agree, _, _ = triple_supertrend_dir(bull_trend_df)
        assert agree == 3

    def test_short_input_zeros(self, short_df):
        d1, d2, d3, agree, line, dir_s = triple_supertrend_dir(short_df)
        assert (d1, d2, d3, agree) == (0, 0, 0, 0)
        assert len(line) == 0


# ════════════════════════════════════════════════════════════════════════
#  Pivots & S/R
# ════════════════════════════════════════════════════════════════════════
class TestPivots:
    def test_finds_obvious_pivot_high(self):
        # A peak surrounded by lower values
        prices = [10, 11, 12, 11, 10] + [9] * 20
        s = pd.Series(prices, dtype=float)
        out = pivots(s, left=2, right=2, kind="high")
        # Pivot at index 2 (value=12, with 2 lower bars on each side)
        assert out.iloc[2] == 12.0
        # No other pivots
        assert out.dropna().count() == 1

    def test_finds_obvious_pivot_low(self):
        prices = [10, 9, 8, 9, 10] + [11] * 20
        s = pd.Series(prices, dtype=float)
        out = pivots(s, left=2, right=2, kind="low")
        assert out.iloc[2] == 8.0


class TestSRZones:
    def test_recent_sr_returns_at_most_keep(self, choppy_df):
        zones = recent_sr_zones(choppy_df, left=8, right=8, keep=6)
        assert len(zones.resistances) <= 6
        assert len(zones.supports) <= 6

    def test_nearest_distance_basic(self):
        zones = SRZones(supports=[95.0, 90.0], resistances=[105.0, 110.0])
        d_res, d_sup = nearest_sr_distance(price=100.0, zones=zones, atr_value=2.0)
        # Nearest resistance is 105 → 5/2 = 2.5 ATR
        assert d_res == pytest.approx(2.5)
        # Nearest support is 95 → 5/2 = 2.5 ATR
        assert d_sup == pytest.approx(2.5)

    def test_empty_zones_return_inf(self):
        d_res, d_sup = nearest_sr_distance(100.0, SRZones([], []), 2.0)
        assert d_res == float("inf")
        assert d_sup == float("inf")

    def test_zero_atr_returns_inf(self):
        zones = SRZones(supports=[95.0], resistances=[105.0])
        d_res, d_sup = nearest_sr_distance(100.0, zones, 0.0)
        assert d_res == float("inf")
        assert d_sup == float("inf")

    def test_price_above_all_resistance_returns_inf_res(self):
        zones = SRZones(supports=[95.0], resistances=[105.0])
        d_res, d_sup = nearest_sr_distance(price=200.0, zones=zones, atr_value=2.0)
        assert d_res == float("inf")
        # All supports below: nearest is 95
        assert d_sup == pytest.approx((200.0 - 95.0) / 2.0)
