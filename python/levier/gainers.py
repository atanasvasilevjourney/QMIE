"""#CryptoGainers — yesterday's top movers → today's watchlist."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd


def yesterday_top_movers(
    panels: dict[str, pd.DataFrame],
    *,
    top_n: int = 20,
) -> list[str]:
    """
    Rank symbols by prior UTC calendar day % change (daily close-to-close
    approximated from 30m bars).
    """
    rows: list[tuple[str, float]] = []
    for sym, df in panels.items():
        if df is None or len(df) < 100:
            continue
        d = df.sort_index()
        d = d.copy()
        d["day"] = d.index.normalize()
        daily = d.groupby("day").agg({"open": "first", "close": "last"})
        if len(daily) < 2:
            continue
        prev = daily.iloc[-2]
        if prev["open"] <= 0:
            continue
        chg = (float(prev["close"]) / float(prev["open"]) - 1.0) * 100.0
        rows.append((sym, chg))
    rows.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in rows[:top_n]]


def mark_gainer_watch(
    row: dict,
    *,
    gainers: set[str],
    min_dist_pct: float,
) -> bool:
    if row.get("symbol") not in gainers:
        return False
    return float(row.get("dist_pct") or 0) >= min_dist_pct
