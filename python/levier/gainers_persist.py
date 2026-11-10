"""Persist #CryptoGainers forward stats (24h from first 30m sighting)."""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

from levier.gainers import yesterday_top_movers_with_pct


def _now_iso() -> str:
    return pd.Timestamp.now("UTC").isoformat()


async def sync_gainer_stats(db: Any, panels: dict[str, pd.DataFrame], *, top_n: int = 20) -> None:
    """
    Record yesterday's top movers and update forward % vs first seen price today.
    """
    movers = yesterday_top_movers_with_pct(panels, top_n=top_n)
    prices: dict[str, float] = {}
    for sym, df in panels.items():
        if df is not None and len(df):
            prices[sym] = float(df.sort_index()["close"].iloc[-1])

    for m in movers:
        sym = m["symbol"]
        px = prices.get(sym)
        if px is None:
            continue
        await db.upsert_levier_gainer(
            symbol=sym,
            gainer_day=m["gainer_day"],
            yday_pct=float(m["pct"]),
            entry_price=px,
            fwd_ret_pct=0.0,
            first_seen_at=_now_iso(),
            last_updated_at=_now_iso(),
        )

    # Update forward returns for all open rows (same gainer_day still tracked)
    rows = await db.list_levier_gainers(limit=200)
    for row in rows:
        sym = row["symbol"]
        entry = float(row.get("entry_price") or 0)
        cur = prices.get(sym)
        if entry <= 0 or cur is None:
            continue
        fwd = (cur / entry - 1.0) * 100.0
        await db.update_levier_gainer_fwd(sym, row["gainer_day"], fwd, _now_iso())


async def persist_snapshot(db: Any, payload: dict) -> None:
    await db.insert_levier_snapshot(json.dumps(payload, default=str))
