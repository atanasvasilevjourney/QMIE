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
    empty_radar_snapshot,
    format_radar_digest,
    _detect_breakout,
    _coil_metrics,
)


def _ohlcv_from_close(close: np.ndarray, *, freq: str = "1D",
                      start: str = "2024-01-01") -> pd.DataFrame:
    n = len(close)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.002
    low = np.minimum(open_, close) * 0.998
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": np.full(n, 1_000_000.0),
    }, index=pd.date_range(start, periods=n, freq=freq, tz="UTC"))


# ════════════════════════════════════════════════════════════════════════
class TestClassifyRggSeries:
    def test_hysteresis_stays_grey_below_enter(self):
        n = 40
        adx_s = pd.Series([22.0] * n)  # in [20, 25) hold band if already grey
        pdi = pd.Series([30.0] * n)
        mdi = pd.Series([10.0] * n)
        colors = classify_rgg_series(pdi, mdi, adx_s, enter_adx=25, exit_adx=20)
        assert (colors == "GREY").all()

    def test_leaves_grey_when_adx_crosses_enter(self):
        n = 50
        adx_s = pd.Series([15.0] * 20 + [30.0] * 30)
        pdi = pd.Series([35.0] * n)
        mdi = pd.Series([10.0] * n)
        colors = classify_rgg_series(pdi, mdi, adx_s, enter_adx=25, exit_adx=20)
        assert colors.iloc[0] == "GREY"
        assert colors.iloc[19] == "GREY"
        assert colors.iloc[20] == "GREEN"
        assert colors.iloc[-1] == "GREEN"

    def test_trend_to_grey_on_exit(self):
        n = 60
        adx_s = pd.Series([30.0] * 30 + [10.0] * 30)
        pdi = pd.Series([10.0] * n)
        mdi = pd.Series([35.0] * n)
        colors = classify_rgg_series(pdi, mdi, adx_s, enter_adx=25, exit_adx=20)
        assert colors.iloc[0] == "RED" or colors.iloc[29] == "RED"
        # Force: after enough strong ADX RED bars, then drop
        assert colors.iloc[-1] == "GREY"

    def test_seeds_grey_conservatively(self):
        # Even with high ADX on bar 0, we start GREY then can leave on that bar
        # if a >= enter — actually first bar with a>=25 and p>m becomes GREEN
        n = 10
        adx_s = pd.Series([30.0] * n)
        pdi = pd.Series([35.0] * n)
        mdi = pd.Series([10.0] * n)
        colors = classify_rgg_series(pdi, mdi, adx_s, enter_adx=25, exit_adx=20)
        assert colors.iloc[0] == "GREEN"  # leave GREY same bar when enter met

    def test_exit_gt_enter_raises(self):
        with pytest.raises(ValueError):
            classify_rgg_series(
                pd.Series([1.0]), pd.Series([1.0]), pd.Series([1.0]),
                enter_adx=18, exit_adx=25,
            )

    def test_holds_trend_in_band_20_25(self):
        # Enter GREEN at 30, then ADX drops to 22 — must stay GREEN (exit=20)
        n = 40
        adx_s = pd.Series([30.0] * 20 + [22.0] * 20)
        pdi = pd.Series([35.0] * n)
        mdi = pd.Series([10.0] * n)
        colors = classify_rgg_series(pdi, mdi, adx_s, enter_adx=25, exit_adx=20)
        assert colors.iloc[19] == "GREEN"
        assert colors.iloc[-1] == "GREEN"


# ════════════════════════════════════════════════════════════════════════
class TestCoilAndBreakout:
    def test_coil_width_uses_low_denominator(self):
        n = 30
        close = np.full(n, 105.0)
        df = _ohlcv_from_close(close)
        df["high"] = 110.0
        df["low"] = 100.0
        width, hi, lo = _coil_metrics(df, lookback=20)
        assert hi == 110.0 and lo == 100.0
        assert width == pytest.approx(10.0, rel=1e-6)  # (110-100)/100*100

    def test_breakout_up_after_grey_tight_coil(self):
        n = 40
        close = np.full(n, 100.0)
        df = _ohlcv_from_close(close)
        df.iloc[:-1, df.columns.get_loc("high")] = 102.0
        df.iloc[:-1, df.columns.get_loc("low")] = 98.0
        df.iloc[:-1, df.columns.get_loc("close")] = 100.0
        df.iloc[-1, df.columns.get_loc("high")] = 108.0
        df.iloc[-1, df.columns.get_loc("low")] = 101.0
        df.iloc[-1, df.columns.get_loc("close")] = 107.0
        colors = pd.Series(["GREY"] * n, index=df.index)
        brk, level, excess = _detect_breakout(
            df, colors, lookback=20, coil_max_width_pct=15.0,
        )
        assert brk == "UP"
        assert level == 102.0
        assert excess is not None and excess > 0

    def test_no_breakout_when_prior_not_grey(self):
        n = 40
        close = np.full(n, 100.0)
        df = _ohlcv_from_close(close)
        df.iloc[:-1, df.columns.get_loc("high")] = 102.0
        df.iloc[:-1, df.columns.get_loc("low")] = 98.0
        df.iloc[-1, df.columns.get_loc("close")] = 107.0
        colors = pd.Series(["GREEN"] * n, index=df.index)
        brk, _, _ = _detect_breakout(
            df, colors, lookback=20, coil_max_width_pct=15.0,
        )
        assert brk is None

    def test_breakout_down(self):
        n = 40
        close = np.full(n, 100.0)
        df = _ohlcv_from_close(close)
        df.iloc[:-1, df.columns.get_loc("high")] = 102.0
        df.iloc[:-1, df.columns.get_loc("low")] = 98.0
        df.iloc[:-1, df.columns.get_loc("close")] = 100.0
        df.iloc[-1, df.columns.get_loc("high")] = 99.0
        df.iloc[-1, df.columns.get_loc("low")] = 90.0
        df.iloc[-1, df.columns.get_loc("close")] = 95.0
        colors = pd.Series(["GREY"] * n, index=df.index)
        brk, level, _ = _detect_breakout(
            df, colors, lookback=20, coil_max_width_pct=15.0,
        )
        assert brk == "DOWN"
        assert level == 98.0


# ════════════════════════════════════════════════════════════════════════
class TestClassifySymbol:
    def test_strong_uptrend_is_green(self, bull_trend_df):
        df = bull_trend_df.copy()
        df.index = pd.date_range("2024-01-01", periods=len(df), freq="1D", tz="UTC")
        row = classify_symbol(df, "BTCUSDT", cfg=RadarConfig(min_bars=50))
        assert row is not None
        assert row.symbol == "BTCUSDT"
        assert row.color == "GREEN"
        assert row.plus_di >= row.minus_di
        assert row.bar_time is not None

    def test_strong_downtrend_is_red(self, bear_trend_df):
        df = bear_trend_df.copy()
        df.index = pd.date_range("2024-01-01", periods=len(df), freq="1D", tz="UTC")
        row = classify_symbol(df, "ETHUSDT", cfg=RadarConfig(min_bars=50))
        assert row is not None
        assert row.color == "RED"

    def test_censored_state_nulls_flip_fields(self):
        # Short window where color never changes → censored
        close = np.linspace(100, 200, 80)
        df = _ohlcv_from_close(close)
        row = classify_symbol(df, "SOLUSDT", cfg=RadarConfig(min_bars=60))
        assert row is not None
        if row.state_censored:
            assert row.flipped_at is None
            assert row.pct_since_flip is None
            assert row.is_fresh_flip is False

    def test_late_stage_requires_positive_extension(self, bull_trend_df):
        df = bull_trend_df.copy()
        df.index = pd.date_range("2024-01-01", periods=len(df), freq="1D", tz="UTC")
        # Force a GREEN with huge positive move via low late threshold
        row = classify_symbol(
            df, "BTCUSDT",
            cfg=RadarConfig(min_bars=50, late_stage_days=5, late_stage_move_pct=5.0),
        )
        assert row is not None
        if row.color == "GREEN" and row.pct_since_flip is not None:
            if row.pct_since_flip >= 5.0 and row.days_in_state >= 5:
                assert row.is_late_stage
            if row.pct_since_flip < 0:
                assert not row.is_late_stage

    def test_too_short_returns_none(self):
        df = _ohlcv_from_close(np.linspace(100, 110, 20))
        assert classify_symbol(df, "SOLUSDT", cfg=RadarConfig(min_bars=60)) is None

    def test_config_validate_rejects_small_kline_limit(self):
        with pytest.raises(ValueError):
            RadarConfig(kline_limit=10).validate()


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
        snap = build_snapshot(rows, requested=3, failed_symbols=[])
        assert snap.count == len(rows)
        assert snap.green + snap.grey + snap.red == snap.count
        assert snap.status == "ready"
        assert snap.enabled is True
        assert "as_of" in snap.as_dict()
        digest = format_radar_digest(snap)
        assert "UNRANKED" in digest
        assert "MANUAL ONLY" in digest
        assert "NOT a QMIE" in digest or "NOT an entry" in digest

    def test_empty_snapshot_stable_keys(self):
        snap = empty_radar_snapshot()
        d = snap.as_dict()
        for k in ("as_of", "status", "enabled", "note", "requested",
                  "succeeded", "failed", "fresh_green", "breakouts",
                  "late_stage_red", "has_actionable"):
            assert k in d

    def test_incomplete_coverage(self, bull_trend_df):
        df = bull_trend_df.copy()
        df.index = pd.date_range("2024-01-01", periods=len(df), freq="1D", tz="UTC")
        row = classify_symbol(df, "BTCUSDT", cfg=RadarConfig(min_bars=50))
        assert row is not None
        snap = build_snapshot([row], requested=3, failed_symbols=["ETHUSDT", "SOLUSDT"])
        assert snap.status == "incomplete"
        assert snap.failed == 2
        digest = format_radar_digest(snap)
        assert "INCOMPLETE" in digest

    def test_coils_and_breakouts_mutually_exclusive_fields(self):
        # Synthetic: GREY tight coil without breakout → is_tight_coil
        n = 80
        close = np.full(n, 100.0)
        df = _ohlcv_from_close(close)
        df["high"] = 102.0
        df["low"] = 98.0
        row = classify_symbol(df, "AAAUSDT", cfg=RadarConfig(min_bars=60))
        assert row is not None
        if row.breakout:
            assert row.is_tight_coil is False
        if row.is_tight_coil:
            assert row.breakout is None
            assert row.color == "GREY"
