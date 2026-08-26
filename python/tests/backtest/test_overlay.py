"""KovaView overlay post-filters on backtest rows (no network, no W_*)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.overlay import (
    OVERLAY_GATES,
    annotate_closed,
    overlay_decision,
    radar_snapshot_at,
    radar_state_table,
    result_to_signal_row,
    summarize,
)
from scanner.radar import RadarConfig, classify_symbol


def _daily_ramp(n: int = 120, start: float = 100.0, end: float = 220.0) -> pd.DataFrame:
    close = np.linspace(start, end, n)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC"),
    )


def test_overlay_gates_empty():
    assert OVERLAY_GATES == ()


def test_radar_table_matches_classify_symbol_last_bar():
    df = _daily_ramp()
    cfg = RadarConfig(min_bars=50)
    table = radar_state_table(df, "BTCUSDT", cfg=cfg)
    row = classify_symbol(df, "BTCUSDT", cfg=cfg)
    assert row is not None
    last = table.iloc[-1]
    assert last["color"] == row.color
    assert int(last["days_in_state"]) == row.days_in_state
    assert bool(last["is_late_stage"]) == row.is_late_stage


def test_btc_red_does_not_skip_buy():
    idx = pd.date_range("2025-01-01", periods=5, freq="1D", tz="UTC")
    btc = pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "color": ["RED"] * 5,
            "is_late_stage": [False] * 5,
            "days_in_state": [3] * 5,
            "pct_since_flip": [-4.0] * 5,
        },
        index=idx,
    )
    eth = pd.DataFrame(
        {
            "symbol": "ETHUSDT",
            "color": ["GREEN"] * 5,
            "is_late_stage": [False] * 5,
            "days_in_state": [4] * 5,
            "pct_since_flip": [6.0] * 5,
        },
        index=idx,
    )
    tables = {"BTCUSDT": btc, "ETHUSDT": eth}
    ts = idx[-1]
    radar = radar_snapshot_at(tables, ts, ["ETHUSDT", "BTCUSDT"])
    buy = result_to_signal_row(
        {
            "symbol": "ETHUSDT",
            "side": "BUY",
            "grade": "A",
            "score": 80,
            "entry": 100.0,
            "stop_loss": 95.0,
            "daily_trend": "bullish",
            "timeframe": "4h",
            "adx_value": 28.0,
            "atr_pct": 1.2,
        },
        signal_id=1,
    )
    sell = dict(buy)
    sell["side"] = "SELL"
    sell["daily_trend"] = "bearish"
    d_buy = overlay_decision(buy, radar=radar)
    d_sell = overlay_decision(sell, radar=radar)
    assert d_buy.skip is False and d_buy.btc_regime is False
    assert d_sell.skip is False and d_sell.btc_regime is False


def test_two_losses_do_not_lock_next_setup():
    idx = pd.date_range("2025-06-01", periods=10, freq="4h", tz="UTC")
    green = pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "color": ["GREEN"] * 10,
            "is_late_stage": [False] * 10,
            "days_in_state": [4] * 10,
            "pct_since_flip": [3.0] * 10,
        },
        index=pd.date_range("2025-06-01", periods=10, freq="1D", tz="UTC"),
    )
    trades = []
    for ts, out in (
        (idx[1], "LOSS"),
        (idx[2], "LOSS"),
        (idx[3], "WIN"),
    ):
        trades.append({
            "timestamp": ts,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "grade": "A",
            "score": 82.0,
            "entry": 100.0,
            "stop_loss": 96.0,
            "daily_trend": "bullish",
            "timeframe": "4h",
            "adx_value": 30.0,
            "atr_pct": 1.1,
            "outcome": out,
            "realized_r": -1.0 if out == "LOSS" else 1.6,
            "rr_ratio": 1.6,
        })
    annotated = annotate_closed(trades, {"BTCUSDT": green})
    assert all(r["overlay_skip"] is False for r in annotated)
    assert all("cooldown" not in str(r.get("overlay_reasons") or "") for r in annotated)
    kept = summarize(annotated, kept_only=True)
    assert kept["n"] == 3
    assert kept["wins"] == 1


def test_too_late_green_chase_does_not_skip_buy():
    idx = pd.date_range("2025-03-01", periods=8, freq="1D", tz="UTC")
    btc = pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "color": ["GREEN"] * 8,
            "is_late_stage": [True] * 8,
            "days_in_state": [40] * 8,
            "pct_since_flip": [55.0] * 8,
        },
        index=idx,
    )
    radar = radar_snapshot_at({"BTCUSDT": btc}, idx[-1], ["BTCUSDT"])
    row = result_to_signal_row(
        {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "grade": "A+",
            "score": 90,
            "entry": 100.0,
            "stop_loss": 95.0,
            "daily_trend": "bullish",
            "timeframe": "4h",
            "adx_value": 35.0,
            "atr_pct": 1.0,
        },
        signal_id=1,
    )
    dec = overlay_decision(row, radar=radar)
    assert dec.skip is False
    assert dec.too_late is False
