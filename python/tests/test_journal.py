"""Journal math, SQLite fills, and signal-column persistence."""
from __future__ import annotations

from pathlib import Path

import pytest

from db import Database
from journal import (
    JournalError,
    cash_pnl,
    close_fill,
    create_fill,
    drift_message,
    outcome_from_close,
    outcome_from_r,
    realized_r,
)
from models import EventType, Grade, JournalClose, JournalCreate, Side, TVSignal


def test_realized_r_buy_win():
    assert realized_r("BUY", 100.0, 110.0, 95.0) == pytest.approx(2.0)


def test_realized_r_sell_loss():
    # SELL fill 100, stop 105, exit 110 → against us 10 / risk 5 = -2R
    assert realized_r("SELL", 100.0, 110.0, 105.0) == pytest.approx(-2.0)


def test_realized_r_none_without_stop():
    assert realized_r("BUY", 100.0, 110.0, None) is None


def test_cash_pnl_buy():
    assert cash_pnl("BUY", 100.0, 110.0, 0.5) == pytest.approx(5.0)


def test_outcome_from_close_pnl_fallback():
    assert outcome_from_close(r=None, pnl=1.0, has_exit=True) == "WIN"


def test_outcome_from_r():
    assert outcome_from_r(None, False) == "OPEN"
    assert outcome_from_r(1.5, True) == "WIN"
    assert outcome_from_r(-1.0, True) == "LOSS"
    assert outcome_from_r(0.0, True) == "LOSS"


def test_drift_message_below_min_fills():
    assert drift_message(
        live_win_pct=40.0, baseline=52.0, closed=10, min_fills=30, pts=5.0,
    ) is None


def test_drift_message_within_band():
    assert drift_message(
        live_win_pct=50.0, baseline=52.0, closed=40, min_fills=30, pts=5.0,
    ) is None


def test_drift_message_fires():
    msg = drift_message(
        live_win_pct=40.0, baseline=52.0, closed=40, min_fills=30, pts=5.0,
    )
    assert msg is not None
    assert "40.0%" in msg
    assert "52.0%" in msg


def _sig(**kw) -> TVSignal:
    defaults = dict(
        strategy="QMIE-Scanner",
        event=EventType.ENTRY,
        symbol="BTCUSDT",
        side=Side.BUY,
        signal_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        score=85.0,
        grade=Grade.A,
        bar_time=1,
        daily_trend="bullish",
        funding_rate=0.0001,
    )
    defaults.update(kw)
    return TVSignal(**defaults)


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    await d.init()
    return d


class TestDatabaseJournal:
    async def test_persists_daily_trend_and_funding(self, db: Database):
        sid = await db.insert_signal(_sig())
        row = await db.get_signal(sid)
        assert row is not None
        assert row["daily_trend"] == "bullish"
        assert row["funding_rate"] == pytest.approx(0.0001)

    async def test_migrates_existing_signals_table(self, tmp_path: Path):
        path = tmp_path / "old.db"
        import aiosqlite
        async with aiosqlite.connect(path) as raw:
            await raw.execute(
                """CREATE TABLE signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    received_at TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    strategy TEXT NOT NULL,
                    event TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT, grade TEXT, score REAL,
                    signal_price REAL, stop_loss REAL, take_profit REAL,
                    raw TEXT NOT NULL
                )"""
            )
            await raw.commit()
        d = Database(f"sqlite+aiosqlite:///{path}")
        await d.init()
        sid = await d.insert_signal(_sig(bar_time=99))
        row = await d.get_signal(sid)
        assert row["daily_trend"] == "bullish"

    async def test_create_fill_open_then_close(self, db: Database):
        sid = await db.insert_signal(_sig())
        opened = await create_fill(db, JournalCreate(
            signal_id=sid, fill_price=100.0, size=0.1, notes="took it",
        ))
        assert opened["outcome"] == "OPEN"
        assert opened["exit_price"] is None
        closed = await close_fill(db, opened["id"], JournalClose(exit_price=110.0))
        assert closed["outcome"] == "WIN"
        assert closed["realized_r"] == pytest.approx(2.0)

    async def test_create_fill_with_exit(self, db: Database):
        sid = await db.insert_signal(_sig())
        row = await create_fill(db, JournalCreate(
            signal_id=sid, fill_price=100.0, size=1.0, exit_price=90.0,
        ))
        assert row["outcome"] == "LOSS"
        assert row["realized_r"] == pytest.approx(-2.0)

    async def test_unknown_signal_404(self, db: Database):
        with pytest.raises(JournalError) as ei:
            await create_fill(db, JournalCreate(
                signal_id=999, fill_price=100.0, size=1.0,
            ))
        assert ei.value.status == 404

    async def test_journal_stats_filters_grade(self, db: Database):
        a = await db.insert_signal(_sig(bar_time=1, grade=Grade.A))
        b = await db.insert_signal(_sig(bar_time=2, symbol="ETHUSDT", grade=Grade.B))
        await create_fill(db, JournalCreate(
            signal_id=a, fill_price=100.0, size=1.0, exit_price=110.0,
        ))
        await create_fill(db, JournalCreate(
            signal_id=b, fill_price=100.0, size=1.0, exit_price=90.0,
        ))
        a_stats = await db.journal_stats(grades=("A+", "A"))
        assert a_stats["closed"] == 1
        assert a_stats["wins"] == 1
        assert a_stats["win_pct"] == 100.0
        all_stats = await db.journal_stats()
        assert all_stats["closed"] == 2
        assert all_stats["wins"] == 1
        assert all_stats["win_pct"] == 50.0
