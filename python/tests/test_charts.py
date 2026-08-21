"""Chart payload builders — synthetic OHLCV, no network."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from charts import (
    align_trades,
    bars_payload,
    equity_payload,
    snap_entry_index,
    snap_exit_index,
    trades_payload,
    ts_ms,
)
from db import Database
from journal import create_fill
from models import EventType, Grade, JournalCreate, Side, TVSignal


def _sig(**kw) -> TVSignal:
    defaults = dict(
        strategy="QMIE-Scanner",
        event=EventType.ENTRY,
        symbol="BTCUSDT",
        side=Side.BUY,
        timeframe="1h",
        signal_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        score=85.0,
        grade=Grade.A,
        bar_time=1_700_000_000_000,
        daily_trend="bullish",
    )
    defaults.update(kw)
    return TVSignal(**defaults)


def test_ts_ms_seconds_and_millis():
    assert ts_ms(1_700_000_000) == 1_700_000_000_000
    assert ts_ms(1_700_000_000_000) == 1_700_000_000_000
    assert ts_ms("2024-01-01T00:00:00+00:00") == 1_704_067_200_000
    assert ts_ms(None) is None
    assert ts_ms("") is None


def test_bars_payload_closed_ohlcv():
    idx = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0],
            "close": [101.0, 102.0, 103.0],
            "volume": [1.0, 2.0, 3.0],
        },
        index=idx,
    )
    bars = bars_payload(df)
    assert len(bars) == 3
    assert bars[0]["t"] == int(idx[0].value // 1_000_000)
    assert bars[0]["o"] == 100.0
    assert bars[-1]["c"] == 103.0
    assert bars_payload(pd.DataFrame()) == []


def test_trades_payload_entry_exit_levels():
    fills = [
        {
            "id": 1,
            "symbol": "ETHUSDT",
            "side": "BUY",
            "grade": "A",
            "source": "paper",
            "outcome": "LOSS",
            "size": 1.0,
            "fill_price": 100.0,
            "exit_price": 95.0,
            "pnl": -5.0,
            "exit_reason": "paper_stop_loss",
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "bar_time": 1_700_000_000_000,
            "created_at": "2023-11-14T22:13:20+00:00",
            "updated_at": "2023-11-15T00:00:00+00:00",
        }
    ]
    trades = trades_payload(fills)
    assert len(trades) == 1
    t = trades[0]
    assert t["entry"]["price"] == 100.0
    assert t["exit"]["price"] == 95.0
    assert t["exit"]["pnl"] == -5.0
    assert t["stop_loss"] == 95.0
    assert t["take_profit"] == 110.0
    assert t["side"] == "BUY"
    assert t["timeframe"] is None


def _hourly_bars(*, start_ms: int, n: int, close0: float = 100.0) -> list[dict]:
    bars = []
    for i in range(n):
        c = close0 + i
        bars.append({
            "t": start_ms + i * 3_600_000,
            "o": c - 0.4,
            "h": c + 1.0,
            "l": c - 1.0,
            "c": c,
            "v": 1.0,
        })
    return bars


def test_snap_1h_fill_lands_on_same_candle():
    bars = _hourly_bars(start_ms=1_700_000_000_000, n=6, close0=100.0)
    i = snap_entry_index(bars, t=bars[2]["t"], price=bars[2]["c"], window_ms=3_600_000)
    assert i == 2


def test_snap_4h_close_onto_last_1h_of_window():
    """4h open at bar 0, close printed on the 4th 1h candle (index 3)."""
    bars = _hourly_bars(start_ms=1_700_000_000_000, n=8, close0=100.0)
    htf_open = bars[0]["t"]
    htf_close = bars[3]["c"]
    i = snap_entry_index(bars, t=htf_open, price=htf_close, window_ms=14_400_000)
    assert i == 3


def test_snap_exit_skips_signal_bar():
    bars = _hourly_bars(start_ms=1_700_000_000_000, n=6, close0=100.0)
    # SL 100.5 is inside bar 0 AND bar 1 ranges (bar0: 99-102, bar1: 100-103)
    i = snap_exit_index(bars, after_i=0, price=100.5)
    assert i == 1


def test_align_trades_stamps_bar_index():
    bars = _hourly_bars(start_ms=1_700_000_000_000, n=8, close0=100.0)
    trades = trades_payload([
        {
            "id": 9,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "source": "paper",
            "outcome": "OPEN",
            "fill_price": bars[3]["c"],
            "bar_time": bars[0]["t"],
            "timeframe": "4h",
            "stop_loss": 95.0,
            "take_profit": 110.0,
        }
    ])
    aligned = align_trades(bars, trades, chart_tf="1h")
    assert aligned[0]["aligned"] is True
    assert aligned[0]["entry"]["i"] == 3
    assert aligned[0]["entry"]["t"] == bars[3]["t"]


def test_equity_payload_cumulative_and_no_orders():
    fills = [
        {
            "id": 1,
            "symbol": "BTCUSDT",
            "exit_price": 101.0,
            "pnl": 10.0,
            "outcome": "WIN",
            "updated_at": "2024-01-01T01:00:00+00:00",
            "created_at": "2024-01-01T00:00:00+00:00",
            "timeframe": "1h",
        },
        {
            "id": 2,
            "symbol": "ETHUSDT",
            "exit_price": 90.0,
            "pnl": -4.0,
            "outcome": "LOSS",
            "updated_at": "2024-01-01T02:00:00+00:00",
            "created_at": "2024-01-01T00:30:00+00:00",
            "timeframe": "1h",
        },
        {
            "id": 3,
            "symbol": "BTCUSDT",
            "exit_price": None,
            "pnl": None,
            "outcome": "OPEN",
            "created_at": "2024-01-01T03:00:00+00:00",
            "timeframe": "4h",
        },
    ]
    book = equity_payload(fills)
    assert book["places_orders"] is False
    assert book["starting_eq"] == 0.0
    assert book["closed"] == 2
    assert book["open"] == 1
    assert book["sum_pnl"] == pytest.approx(6.0)
    assert book["points"][0]["equity"] == 0.0
    assert book["points"][-1]["equity"] == pytest.approx(6.0)
    symbols = {s["symbol"]: s["fills"] for s in book["symbols"]}
    assert symbols["BTCUSDT"] == 2
    assert symbols["ETHUSDT"] == 1


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    await d.init()
    return d


async def test_fills_for_symbol_isolates(db: Database):
    btc = await db.insert_signal(_sig(symbol="BTCUSDT", bar_time=1))
    eth = await db.insert_signal(_sig(symbol="ETHUSDT", bar_time=2))
    await create_fill(db, JournalCreate(signal_id=btc, fill_price=100.0, size=1.0, exit_price=110.0))
    await create_fill(db, JournalCreate(signal_id=eth, fill_price=50.0, size=2.0))
    btc_fills = await db.fills_for_symbol("BTCUSDT")
    eth_fills = await db.fills_for_symbol("ethusdt")
    assert len(btc_fills) == 1
    assert btc_fills[0]["symbol"] == "BTCUSDT"
    assert btc_fills[0]["exit_price"] == pytest.approx(110.0)
    assert len(eth_fills) == 1
    assert eth_fills[0]["outcome"] == "OPEN"
    none = await db.fills_for_symbol("SOLUSDT")
    assert none == []
    trades = trades_payload(btc_fills)
    assert trades[0]["entry"]["price"] == pytest.approx(100.0)
    assert trades[0]["exit"]["price"] == pytest.approx(110.0)
