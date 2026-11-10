from __future__ import annotations

import pytest

from db import Database


@pytest.mark.asyncio
async def test_levier_gainer_roundtrip(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    await db.init()
    await db.upsert_levier_gainer(
        symbol="ETHUSDT",
        gainer_day="2026-10-30",
        yday_pct=8.5,
        entry_price=100.0,
        fwd_ret_pct=0.0,
        first_seen_at="2026-10-31T00:00:00+00:00",
        last_updated_at="2026-10-31T00:00:00+00:00",
    )
    await db.update_levier_gainer_fwd("ETHUSDT", "2026-10-30", 2.5, "2026-10-31T12:00:00+00:00")
    rows = await db.list_levier_gainers()
    assert len(rows) == 1
    assert rows[0]["fwd_ret_pct"] == pytest.approx(2.5)
