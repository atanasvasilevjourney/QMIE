"""
QMIE — Persistence Layer
========================
Async SQLite (via aiosqlite) for:
  - signals received
  - orders placed (intents)
  - broker responses
  - daily PnL snapshot (used by RiskManager)

Lightweight by design. Swap the URL to Postgres for prod scale.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from models import BrokerResponse, OrderIntent, TVSignal

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at     TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    strategy        TEXT NOT NULL,
    event           TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT,
    grade           TEXT,
    score           REAL,
    signal_price    REAL,
    stop_loss       REAL,
    take_profit     REAL,
    raw             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_signals_symbol_time ON signals(symbol, received_at DESC);

CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    submitted_at     TEXT NOT NULL,
    client_order_id  TEXT NOT NULL UNIQUE,
    broker           TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,
    quantity         REAL NOT NULL,
    price            REAL,
    stop_loss        REAL,
    take_profit      REAL,
    status           TEXT NOT NULL,
    broker_order_id  TEXT,
    error            TEXT,
    raw_request      TEXT,
    raw_response     TEXT
);
CREATE INDEX IF NOT EXISTS ix_orders_broker_time ON orders(broker, submitted_at DESC);

CREATE TABLE IF NOT EXISTS daily_pnl (
    date           TEXT PRIMARY KEY,
    starting_eq    REAL NOT NULL,
    realized_pnl   REAL NOT NULL DEFAULT 0,
    trade_count    INTEGER NOT NULL DEFAULT 0,
    halted         INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, url: str):
        if not url.startswith("sqlite"):
            raise ValueError("Only sqlite URLs supported in this build")
        # parse path from `sqlite+aiosqlite:///./data/qmie.db`
        path = url.split(":///")[-1]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    async def health_check(self) -> bool:
        try:
            async with aiosqlite.connect(self.path) as db:
                async with db.execute("SELECT 1") as cur:
                    row = await cur.fetchone()
                    return row is not None
        except Exception as e:
            logger.error("DB health check failed: %s", e)
            return False

    # ─── Signals ─────────────────────────────────────────────────────────
    async def insert_signal(self, sig: TVSignal) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT OR IGNORE INTO signals
                (received_at, idempotency_key, strategy, event, symbol, side,
                 grade, score, signal_price, stop_loss, take_profit, raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, sig.idempotency_key, sig.strategy, sig.event.value,
                 sig.symbol, sig.side.value if sig.side else None,
                 sig.grade.value if sig.grade else None, sig.score,
                 sig.signal_price, sig.stop_loss, sig.take_profit,
                 json.dumps(sig.model_dump(mode="json"))),
            )
            await db.commit()
            return cur.lastrowid or 0

    async def recent_signals(self, limit: int = 50) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    # ─── Orders ──────────────────────────────────────────────────────────
    async def insert_order(self, intent: OrderIntent, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO orders
                (submitted_at, client_order_id, broker, symbol, side, quantity,
                 price, stop_loss, take_profit, status, raw_request)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, intent.client_order_id, intent.broker, intent.symbol,
                 intent.side.value, intent.quantity, intent.price,
                 intent.stop_loss, intent.take_profit, status,
                 json.dumps(intent.model_dump(mode="json"))),
            )
            await db.commit()

    async def update_order_response(self, resp: BrokerResponse) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                UPDATE orders
                   SET status = ?, broker_order_id = ?, error = ?, raw_response = ?
                 WHERE client_order_id = ?
                """,
                (resp.status.value, resp.broker_order_id, resp.error,
                 json.dumps(resp.model_dump(mode="json")), resp.client_order_id),
            )
            await db.commit()

    # ─── Daily PnL (RiskManager) ─────────────────────────────────────────
    async def get_or_create_today(self, starting_eq: float) -> dict[str, Any]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM daily_pnl WHERE date = ?", (today,)
            ) as cur:
                row = await cur.fetchone()
                if row:
                    return dict(row)
            await db.execute(
                "INSERT INTO daily_pnl (date, starting_eq) VALUES (?, ?)",
                (today, starting_eq),
            )
            await db.commit()
            return {"date": today, "starting_eq": starting_eq,
                    "realized_pnl": 0.0, "trade_count": 0, "halted": 0}

    async def update_today(self, *, pnl_delta: float = 0.0,
                           trade_inc: int = 0, halt: bool | None = None) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.path) as db:
            sets, args = [], []
            if pnl_delta:
                sets.append("realized_pnl = realized_pnl + ?"); args.append(pnl_delta)
            if trade_inc:
                sets.append("trade_count = trade_count + ?"); args.append(trade_inc)
            if halt is not None:
                sets.append("halted = ?"); args.append(1 if halt else 0)
            if not sets:
                return
            args.append(today)
            await db.execute(
                f"UPDATE daily_pnl SET {', '.join(sets)} WHERE date = ?", args,
            )
            await db.commit()
