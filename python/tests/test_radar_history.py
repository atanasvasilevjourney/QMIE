"""Radar breadth history persistence and GET /radar/history."""
from __future__ import annotations

import pytest

from db import Database
from main import get_radar_history, state


@pytest.fixture
async def db(tmp_path):
    path = tmp_path / "t.db"
    database = Database(f"sqlite+aiosqlite:///{path}")
    await database.init()
    return database


@pytest.mark.asyncio
async def test_upsert_and_fetch_breadth(db: Database):
    await db.upsert_radar_breadth(
        as_of_date="2026-09-01", green=40, grey=10, red=50, total=100,
    )
    await db.upsert_radar_breadth(
        as_of_date="2026-09-02", green=55, grey=8, red=37, total=100,
    )
    rows = await db.radar_breadth_history(days=90)
    assert len(rows) == 2
    assert rows[0]["as_of_date"] == "2026-09-01"
    assert rows[1]["green"] == 55

    await db.upsert_radar_breadth(
        as_of_date="2026-09-02", green=60, grey=5, red=35, total=100,
    )
    rows2 = await db.radar_breadth_history(days=90)
    assert rows2[-1]["green"] == 60


@pytest.mark.asyncio
async def test_radar_history_endpoint(db: Database):
    state.db = db
    await db.upsert_radar_breadth(
        as_of_date="2026-08-01", green=20, grey=5, red=75, total=80,
    )
    await db.upsert_radar_breadth(
        as_of_date="2026-08-02", green=30, grey=5, red=65, total=80,
    )
    body = await get_radar_history(range="3m")
    assert body["days"] == 90
    assert body["count"] == 2
    assert body["points"][0]["green_pct"] == 25.0
    assert body["points"][1]["red_pct"] == 81.25
