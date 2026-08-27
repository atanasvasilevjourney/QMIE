"""
QMIE — Persistence Layer
========================
Async SQLite (via aiosqlite) for:
  - signals received (scanner alerts)
  - fills (manual journal against those alerts)
  - leftover orders / daily_pnl tables from the broker edition (unused)

Lightweight by design. Swap the URL to Postgres for prod scale.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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
    daily_trend     TEXT,
    funding_rate    REAL,
    raw             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_signals_symbol_time ON signals(symbol, received_at DESC);

CREATE TABLE IF NOT EXISTS fills (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    signal_id    INTEGER NOT NULL,
    fill_price   REAL NOT NULL,
    size         REAL NOT NULL,
    exit_price   REAL,
    notes        TEXT,
    realized_r   REAL,
    outcome      TEXT NOT NULL,
    pnl          REAL,
    source       TEXT NOT NULL DEFAULT 'manual',
    exit_reason  TEXT,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);
CREATE INDEX IF NOT EXISTS ix_fills_signal ON fills(signal_id);
CREATE INDEX IF NOT EXISTS ix_fills_outcome ON fills(outcome);

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            await self._migrate(db)
            await db.commit()

    async def _migrate(self, db: aiosqlite.Connection) -> None:
        """Add columns that CREATE TABLE IF NOT EXISTS will not alter."""
        async with db.execute("PRAGMA table_info(signals)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "daily_trend" not in cols:
            await db.execute("ALTER TABLE signals ADD COLUMN daily_trend TEXT")
        if "funding_rate" not in cols:
            await db.execute("ALTER TABLE signals ADD COLUMN funding_rate REAL")
        async with db.execute("PRAGMA table_info(fills)") as cur:
            fill_cols = {row[1] for row in await cur.fetchall()}
        if "pnl" not in fill_cols:
            await db.execute("ALTER TABLE fills ADD COLUMN pnl REAL")
        if "source" not in fill_cols:
            await db.execute("ALTER TABLE fills ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
        if "exit_reason" not in fill_cols:
            await db.execute("ALTER TABLE fills ADD COLUMN exit_reason TEXT")

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
        now = _now()
        daily_trend = getattr(sig, "daily_trend", None)
        funding_rate = getattr(sig, "funding_rate", None)
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT OR IGNORE INTO signals
                (received_at, idempotency_key, strategy, event, symbol, side,
                 grade, score, signal_price, stop_loss, take_profit,
                 daily_trend, funding_rate, raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, sig.idempotency_key, sig.strategy, sig.event.value,
                 sig.symbol, sig.side.value if sig.side else None,
                 sig.grade.value if sig.grade else None, sig.score,
                 sig.signal_price, sig.stop_loss, sig.take_profit,
                 daily_trend, funding_rate,
                 json.dumps(sig.model_dump(mode="json"))),
            )
            await db.commit()
            rid = cur.lastrowid or 0
            if rid:
                return rid
            async with db.execute(
                "SELECT id FROM signals WHERE idempotency_key = ?",
                (sig.idempotency_key,),
            ) as found:
                existing = await found.fetchone()
            return int(existing[0]) if existing else 0

    async def get_signal(self, signal_id: int) -> Optional[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM signals WHERE id = ?", (signal_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def recent_signals(self, limit: int = 50) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    # ─── Fills (manual journal) ──────────────────────────────────────────
    async def insert_fill(
        self,
        *,
        signal_id: int,
        fill_price: float,
        size: float,
        exit_price: Optional[float],
        notes: Optional[str],
        realized_r: Optional[float],
        outcome: str,
        pnl: Optional[float] = None,
        source: str = "manual",
        exit_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        now = _now()
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO fills
                (created_at, updated_at, signal_id, fill_price, size,
                 exit_price, notes, realized_r, outcome, pnl, source, exit_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, now, signal_id, fill_price, size,
                 exit_price, notes, realized_r, outcome, pnl, source, exit_reason),
            )
            await db.commit()
            fill_id = cur.lastrowid or 0
        row = await self.get_fill(fill_id)
        return row or {"id": fill_id}

    async def get_fill(self, fill_id: int) -> Optional[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM fills WHERE id = ?", (fill_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def update_fill_exit(
        self,
        fill_id: int,
        *,
        exit_price: float,
        realized_r: Optional[float],
        outcome: str,
        notes: Optional[str],
        pnl: Optional[float] = None,
        exit_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        now = _now()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                UPDATE fills
                   SET updated_at = ?, exit_price = ?, realized_r = ?,
                       outcome = ?, notes = ?, pnl = ?, exit_reason = ?
                 WHERE id = ?
                """,
                (now, exit_price, realized_r, outcome, notes, pnl, exit_reason, fill_id),
            )
            await db.commit()
        row = await self.get_fill(fill_id)
        return row or {"id": fill_id}

    async def fills_for_symbol(self, symbol: str, limit: int = 200) -> list[dict[str, Any]]:
        """Journal/paper fills for one USDT-perp, oldest first (chart marks)."""
        symbol = (symbol or "").upper()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT f.*, s.symbol, s.side, s.grade, s.strategy, s.event,
                       s.stop_loss, s.take_profit, s.signal_price,
                       json_extract(s.raw, '$.timeframe') AS timeframe,
                       json_extract(s.raw, '$.bar_time') AS bar_time
                FROM fills f
                JOIN signals s ON s.id = f.signal_id
                WHERE s.symbol = ?
                ORDER BY f.id ASC
                LIMIT ?
                """,
                (symbol, limit),
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def recent_fills(self, limit: int = 50) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT f.*, s.symbol, s.side, s.grade, s.strategy, s.event,
                       s.stop_loss, s.take_profit, s.signal_price,
                       json_extract(s.raw, '$.timeframe') AS timeframe,
                       json_extract(s.raw, '$.bar_time') AS bar_time
                FROM fills f
                JOIN signals s ON s.id = f.signal_id
                ORDER BY f.id DESC
                LIMIT ?
                """,
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def fill_for_signal(self, signal_id: int) -> Optional[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM fills WHERE signal_id = ? ORDER BY id ASC LIMIT 1",
                (signal_id,),
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def open_fills(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT f.*, s.symbol, s.side, s.grade, s.strategy, s.event,
                       s.stop_loss, s.take_profit, s.signal_price,
                       json_extract(s.raw, '$.timeframe') AS timeframe,
                       json_extract(s.raw, '$.bar_time') AS bar_time
                FROM fills f
                JOIN signals s ON s.id = f.signal_id
                WHERE f.outcome = 'OPEN'
                ORDER BY f.id ASC
                """
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def entry_signals_without_fill(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT s.*
                FROM signals s
                LEFT JOIN fills f ON f.signal_id = s.id
                WHERE f.id IS NULL
                  AND lower(s.event) = 'entry'
                  AND ifnull(s.strategy, '') != 'QMIE-Paper'
                ORDER BY s.id ASC
                """
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def journal_stats(self, *, grades: tuple[str, ...] | None = None) -> dict[str, Any]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            sql = """
                SELECT f.outcome, f.realized_r, f.pnl, s.grade,
                       ifnull(f.source, 'manual') AS source,
                       json_extract(s.raw, '$.timeframe') AS timeframe
                FROM fills f
                JOIN signals s ON s.id = f.signal_id
                """
            params: list[Any] = []
            if grades:
                placeholders = ",".join("?" * len(grades))
                sql += f" WHERE s.grade IN ({placeholders})"
                params.extend(grades)
            async with db.execute(sql, params) as cur:
                rows = [dict(r) for r in await cur.fetchall()]

        closed = [r for r in rows if r.get("outcome") not in (None, "OPEN")]
        wins = [r for r in closed if r.get("outcome") == "WIN"]
        win_pct = round(100.0 * len(wins) / len(closed), 1) if closed else 0.0
        r_vals = [float(r["realized_r"]) for r in closed if r.get("realized_r") is not None]
        avg_r = round(sum(r_vals) / len(r_vals), 3) if r_vals else None
        pnls = [float(r["pnl"]) for r in closed if r.get("pnl") is not None]
        sum_pnl = round(sum(pnls), 4) if pnls else None

        def _norm_tf(raw: Any) -> str:
            t = str(raw or "").strip().lower()
            return t if t else "unknown"

        paper_closed = [r for r in closed if str(r.get("source") or "manual") == "paper"]
        manual_closed = [r for r in closed if str(r.get("source") or "manual") != "paper"]
        by_source = {"paper": len(paper_closed), "manual": len(manual_closed)}
        by_timeframe: dict[str, int] = {}
        for r in closed:
            tf = _norm_tf(r.get("timeframe"))
            by_timeframe[tf] = by_timeframe.get(tf, 0) + 1
        manual_4h = sum(
            1
            for r in manual_closed
            if _norm_tf(r.get("timeframe")) in ("4h", "4hour", "240")
        )
        return {
            "fills": len(rows),
            "closed": len(closed),
            "wins": len(wins),
            "losses": len(closed) - len(wins),
            "win_pct": win_pct,
            "avg_realized_r": avg_r,
            "sum_pnl": sum_pnl,
            "grades": list(grades) if grades else "all",
            "by_source": by_source,
            "by_timeframe": by_timeframe,
            "manual_4h_closed": manual_4h,
            "pooled": True,
            "oos_edge": "4h A/A+ OOS 49.1% / E[R] +0.309 — not this mix",
        }

    # ─── Orders (unused in scanner edition; kept for schema compatibility) ─
    async def insert_order(self, intent: OrderIntent, status: str) -> None:
        now = _now()
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

    # ─── Daily PnL (unused in scanner edition) ───────────────────────────
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
