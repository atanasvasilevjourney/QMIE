"""
Tests for scanner.radar — daily RGG + coil breakouts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.radar import (
    RadarConfig,
    build_snapshot,
    classify_rgg_series,
    classify_symbol,
    format_radar_digest,
    _detect_breakout,
    _coil_metrics,
)


def _ohlcv_from_close(close: np.ndarray, *, freq: str = "1D",
                      start: str = "2024-01-01") -> pd.DataFrame:
    n = len(close)
    open_ = np.concatenate([[close[0]], close[:-1]])
    # Deterministic high/low so ADX/DMI has directional pressure
    high = np.maximum(open_, close) * 1.002
    low = np.minimum(open_, close) * 0.998
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": np.full(n, 1_000_000.0),
    }, index=pd.date_range(start, periods=n, freq=freq, tz="UTC"))


# ════════════════════════════════════════════════════════════════════════
class TestClassifyRggSeries:
    def test_hysteresis_stays_grey_below_enter(self):
        # ADX stuck at 20 — between exit(18) and enter(25) → seed GREY, stay
        n = 40
        adx_s = pd.Series([20.0] * n)
        pdi = pd.Series([30.0] * n)
        mdi = pd.Series([10.0] * n)
        colors = classify_rgg_series(pdi, mdi, adx_s, enter_adx=25, exit_adx=18)
        assert (colors == "GREY").all()

    def test_leaves_grey_when_adx_crosses_enter(self):
        n = 50
        adx_s = pd.Series([15.0] * 20 + [30.0] * 30)
        pdi = pd.Series([35.0] * n)
        mdi = pd.Series([10.0] * n)
        colors = classify_rgg_series(pdi, mdi, adx_s, enter_adx=25, exit_adx=18)
        assert colors.iloc[0] == "GREY"
        assert colors.iloc[-1] == "GREEN"
        # First GREEN appears at index 20
        assert colors.iloc[19] == "GREY"
        assert colors.iloc[20] == "GREEN"

    def test_trend_to_grey_on_exit(self):
        n = 60
        adx_s = pd.Series([30.0] * 30 + [10.0] * 30)
        pdi = pd.Series([10.0] * n)
        mdi = pd.Series([35.0] * n)
        colors = classify_rgg_series(pdi, mdi, adx_s, enter_adx=25, exit_adx=18)
        assert colors.iloc[0] == "RED"
        assert colors.iloc[-1] == "GREY"

    def test_green_to_red_flip_while_strong(self):
        n = 60
        adx_s = pd.Series([30.0] * n)
        pdi = pd.Series([35.0] * 30 + [10.0] * 30)
        mdi = pd.Series([10.0] * 30 + [35.0] * 30)
        colors = classify_rgg_series(pdi, mdi, adx_s, enter_adx=25, exit_adx=18)
        assert colors.iloc[0] == "GREEN"
        assert colors.iloc[-1] == "RED"

    def test_exit_gt_enter_raises(self):
        with pytest.raises(ValueError):
            classify_rgg_series(
                pd.Series([1.0]), pd.Series([1.0]), pd.Series([1.0]),
                enter_adx=18, exit_adx=25,
            )


# ════════════════════════════════════════════════════════════════════════
class TestCoilAndBreakout:
    def test_coil_width_pct(self):
        # Flat range 100–110 → width 10% of close 105
        n = 30
        close = np.full(n, 105.0)
        df = _ohlcv_from_close(close)
        df["high"] = 110.0
        df["low"] = 100.0
        width, hi, lo = _coil_metrics(df, lookback=20)
        assert hi == 110.0 and lo == 100.0
        assert width == pytest.approx(10.0 / 105.0 * 100.0, rel=1e-3)

    def test_breakout_up_after_tight_coil(self):
        n = 40
        close = np.full(n, 100.0)
        df = _ohlcv_from_close(close)
        # Prior 20 bars: tight 98–102 range
        df.iloc[:-1, df.columns.get_loc("high")] = 102.0
        df.iloc[:-1, df.columns.get_loc("low")] = 98.0
        df.iloc[:-1, df.columns.get_loc("close")] = 100.0
        # Last bar breaks up
        df.iloc[-1, df.columns.get_loc("high")] = 108.0
        df.iloc[-1, df.columns.get_loc("low")] = 101.0
        df.iloc[-1, df.columns.get_loc("close")] = 107.0
        assert _detect_breakout(df, lookback=20, coil_max_width_pct=15.0) == "UP"

    def test_no_breakout_when_prior_not_tight(self):
        n = 40
        close = np.linspace(80, 120, n)
        df = _ohlcv_from_close(close)
        # Wide prior range → no breakout flag even if last close is high
        assert _detect_breakout(df, lookback=20, coil_max_width_pct=5.0) is None


# ════════════════════════════════════════════════════════════════════════
class TestClassifySymbol:
    def test_strong_uptrend_is_green(self, bull_trend_df):
        # Resample-ish: use 1h bull fixture as if daily (same shape)
        df = bull_trend_df.copy()
        df.index = pd.date_range("2024-01-01", periods=len(df), freq="1D", tz="UTC")
        row = classify_symbol(df, "BTCUSDT", cfg=RadarConfig(min_bars=50))
        assert row is not None
        assert row.symbol == "BTCUSDT"
        assert row.color == "GREEN"
        assert row.plus_di >= row.minus_di
        assert row.days_in_state >= 1

    def test_strong_downtrend_is_red(self, bear_trend_df):
        df = bear_trend_df.copy()
        df.index = pd.date_range("2024-01-01", periods=len(df), freq="1D", tz="UTC")
        row = classify_symbol(df, "ETHUSDT", cfg=RadarConfig(min_bars=50))
        assert row is not None
        assert row.color == "RED"
        assert row.minus_di >= row.plus_di

    def test_too_short_returns_none(self):
        df = _ohlcv_from_close(np.linspace(100, 110, 20))
        assert classify_symbol(df, "SOLUSDT", cfg=RadarConfig(min_bars=60)) is None


# ════════════════════════════════════════════════════════════════════════
class TestSnapshotAndDigest:
    def test_build_snapshot_buckets(self, bull_trend_df, bear_trend_df, choppy_df):
        cfg = RadarConfig(min_bars=50)
        rows = []
        for sym, raw in [("BTCUSDT", bull_trend_df), ("ETHUSDT", bear_trend_df),
                         ("SOLUSDT", choppy_df)]:
            df = raw.copy()
            df.index = pd.date_range("2024-01-01", periods=len(df), freq="1D", tz="UTC")
            r = classify_symbol(df, sym, cfg=cfg)
            if r:
                rows.append(r)
        snap = build_snapshot(rows)
        assert snap.count == len(rows)
        assert snap.green + snap.grey + snap.red == snap.count
        assert snap.timeframe == "1d"
        digest = format_radar_digest(snap)
        assert "Trend Radar" in digest
        assert "Signal only" in digest
        assert "manual" in digest.lower()
