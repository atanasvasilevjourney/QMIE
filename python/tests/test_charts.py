"""Chart payload builders — synthetic OHLCV, no network."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from charts import bars_payload, equity_payload, trades_payload, ts_ms
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
