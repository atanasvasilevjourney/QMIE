"""Donchian turtle module — prior-window channels and portfolio helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.donchian_turtle import (
    TurtleParams,
    build_donchian_snapshot,
    donchian_turtle_frame,
    donchian_watch_from_df,
    min_warmup_bars,
)


def _ohlcv(n: int = 120, *, trend: float = 0.002) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = 100.0 * (1.0 + trend) ** np.arange(n)
    high = close * 1.01
    low = close * 0.99
    vol = np.full(n, 1e6)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def test_donchian_entry_excludes_current_bar_high():
    df = _ohlcv(80, trend=0.0)
    spike = df.copy()
    spike.loc[spike.index[-1], "high"] = 500.0
    spike.loc[spike.index[-1], "close"] = 105.0
    frame = donchian_turtle_frame(spike, TurtleParams(entry_channel=10, exit_channel=5, use_vwap_filter=False))
    # Today's 500 high must not lower the entry threshold for today's close.
    assert float(frame["entry_high"].iloc[-1]) < 500.0


def test_breakout_after_flat_base():
    n = 70
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = np.full(n, 100.0)
    close[-1] = 120.0
    high = close + 1.0
    low = close - 1.0
    df = pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1e6),
        },
        index=idx,
    )
    frame = donchian_turtle_frame(
        df, TurtleParams(entry_channel=20, exit_channel=10, use_vwap_filter=False)
    )
    assert bool(frame["entry_long"].iloc[-1]) is True


def test_min_warmup_bars():
    p = TurtleParams(entry_channel=55, exit_channel=20, vwap_window=20)
    assert min_warmup_bars(p) >= 58


def test_watch_row_flags_new_entry():
    df = _ohlcv(70, trend=0.0)
    df.loc[df.index[-1], "close"] = 200.0
    df.loc[df.index[-1], "high"] = 205.0
    row = donchian_watch_from_df(
        df, "TESTUSDT", TurtleParams(entry_channel=20, exit_channel=10, use_vwap_filter=False)
    )
    assert row is not None
    assert row["symbol"] == "TESTUSDT"
    assert row["is_new_entry"] is True
    assert row["setup_type"] == "turtle"


def test_build_snapshot_sorts_by_strength():
    snap = build_donchian_snapshot(
        [
            {"symbol": "A", "strength": 0.01, "is_new_entry": False},
            {"symbol": "B", "strength": 0.05, "is_new_entry": True},
        ],
        as_of="2026-01-01",
        enabled=True,
        requested=10,
    )
    assert snap["watchlist"][0]["symbol"] == "B"
    assert snap["new_entries"] == 1
    assert snap["strategy"] == "QMIE-DonchianTurtle"


def test_portfolio_backtest_runs_on_tiny_universe():
    from datetime import date

    from backtest.donchian_turtle import run_turtle_portfolio

    result = run_turtle_portfolio(
        ["BTCUSDT", "ETHUSDT"],
        date(2024, 6, 1),
        date(2024, 9, 1),
        params=TurtleParams(entry_channel=20, exit_channel=10, use_vwap_filter=False),
        max_positions=2,
    )
    assert result.metrics["days"] >= 0
