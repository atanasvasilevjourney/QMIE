"""Paper book: auto-fill entries, SL/TP exits, EXIT rows with PnL."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from db import Database
from journal import cash_pnl, outcome_from_close
from models import EventType, Grade, Side, TVSignal
from paper import PaperBook, first_bar_exit, hit_exit, paper_size


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


def _bars(*, lows, highs, start="2024-01-01 00:00:00") -> pd.DataFrame:
    n = len(lows)
    idx = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    close = [(h + lo) / 2 for h, lo in zip(highs, lows)]
    return pd.DataFrame(
        {"open": close, "high": highs, "low": lows, "close": close, "volume": [1.0] * n},
        index=idx,
    )


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    await d.init()
    return d


def test_paper_size():
    assert paper_size(100.0, 1000.0) == pytest.approx(10.0)


def test_cash_pnl_buy_and_sell():
    assert cash_pnl("BUY", 100.0, 110.0, 2.0) == pytest.approx(20.0)
    assert cash_pnl("SELL", 100.0, 90.0, 2.0) == pytest.approx(20.0)


def test_hit_exit_same_bar_prefers_stop():
    reason, px = hit_exit("BUY", 95.0, 110.0, high=120.0, low=90.0)
    assert reason == "stop_loss"
    assert px == pytest.approx(95.0)


def test_outcome_from_close_uses_pnl_without_r():
    assert outcome_from_close(r=None, pnl=12.0, has_exit=True) == "WIN"
    assert outcome_from_close(r=None, pnl=-3.0, has_exit=True) == "LOSS"


def test_first_bar_exit_skips_signal_bar():
    df = _bars(lows=[99, 90], highs=[101, 102], start="2024-01-01 00:00:00")
    after = df.index[0]
    hit = first_bar_exit(df, side="BUY", stop_loss=95.0, take_profit=110.0, after=after)
    assert hit is not None
    reason, px, ts = hit
    assert reason == "stop_loss"
    assert ts == df.index[1]


class TestPaperBook:
    async def test_opens_one_fill_per_entry(self, db: Database):
        book = PaperBook(db, notional_usdt=1000.0)
        sid = await db.insert_signal(_sig())
        row = await book.open_entry(sid)
        assert row is not None
        assert row["outcome"] == "OPEN"
        assert row["source"] == "paper"
        assert row["size"] == pytest.approx(10.0)
        again = await book.open_entry(sid)
        assert again is None

    async def test_skips_exit_events(self, db: Database):
        book = PaperBook(db)
        sid = await db.insert_signal(_sig(event=EventType.EXIT, strategy="QMIE-Paper", bar_time=2))
        assert await book.open_entry(sid) is None

    async def test_sync_fills_all_entries(self, db: Database):
        book = PaperBook(db, notional_usdt=1000.0)
        await db.insert_signal(_sig(bar_time=1, symbol="BTCUSDT"))
        await db.insert_signal(_sig(bar_time=2, symbol="ETHUSDT", signal_price=200.0))
        n = await book.sync_entries()
        assert n == 2
        assert (await book.snapshot())["open"] == 2

    async def test_marks_take_profit_and_writes_exit_signal(self, db: Database):
        book = PaperBook(db, notional_usdt=1000.0)
        sid = await db.insert_signal(_sig(bar_time=int(pd.Timestamp("2024-01-01", tz="UTC").value // 1_000_000)))
        opened = await book.open_entry(sid)
        assert opened is not None
        df = _bars(
            lows=[99, 100, 108],
            highs=[101, 102, 111],
            start="2024-01-01 00:00:00",
        )
        closed_rows = await book.mark_from_bars(df, symbol="BTCUSDT", timeframe="1h")
        assert len(closed_rows) == 1
        closed = closed_rows[0]
        assert closed["outcome"] == "WIN"
        assert closed["exit_reason"] == "take_profit"
        assert closed["exit_price"] == pytest.approx(110.0)
        assert closed["pnl"] == pytest.approx(100.0)
        exits = [s for s in await db.recent_signals(20) if s.get("event") == "exit"]
        assert len(exits) == 1
        assert exits[0]["strategy"] == "QMIE-Paper"
        raw = exits[0]
        # pnl lives on raw JSON
        from improve.checklist import flatten_signal
        flat = flatten_signal(raw)
        assert float(flat["pnl"]) == pytest.approx(100.0)

    async def test_marks_stop_loss(self, db: Database):
        book = PaperBook(db, notional_usdt=1000.0)
        sid = await db.insert_signal(_sig(bar_time=int(pd.Timestamp("2024-01-01", tz="UTC").value // 1_000_000)))
        await book.open_entry(sid)
        df = _bars(lows=[99, 94], highs=[101, 100], start="2024-01-01 00:00:00")
        closed_rows = await book.mark_from_bars(df, symbol="BTCUSDT", timeframe="1h")
        assert closed_rows[0]["outcome"] == "LOSS"
        assert closed_rows[0]["exit_reason"] == "stop_loss"
        assert closed_rows[0]["pnl"] == pytest.approx(-50.0)
