"""#CryptoGainers — yesterday's top movers → today's watchlist."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd


def yesterday_top_movers_with_pct(
    panels: dict[str, pd.DataFrame],
    *,
    top_n: int = 20,
) -> list[dict]:
    """Prior UTC day OHLC % change per symbol."""
    rows: list[dict] = []
    for sym, df in panels.items():
        if df is None or len(df) < 100:
            continue
        d = df.sort_index()
        d = d.copy()
        d["day"] = d.index.normalize()
        daily = d.groupby("day").agg({"open": "first", "close": "last"})
        if len(daily) < 2:
            continue
        day_idx = daily.index[-2]
        prev = daily.iloc[-2]
        if prev["open"] <= 0:
            continue
        chg = (float(prev["close"]) / float(prev["open"]) - 1.0) * 100.0
        rows.append({"symbol": sym, "pct": chg, "gainer_day": str(day_idx.date())})
    rows.sort(key=lambda x: x["pct"], reverse=True)
    return rows[:top_n]


def yesterday_top_movers(
    panels: dict[str, pd.DataFrame],
    *,
    top_n: int = 20,
) -> list[str]:
    """
    Rank symbols by prior UTC calendar day % change (daily close-to-close
    approximated from 30m bars).
    """
    return [r["symbol"] for r in yesterday_top_movers_with_pct(panels, top_n=top_n)]


def mark_gainer_watch(
    row: dict,
    *,
    gainers: set[str],
    min_dist_pct: float,
) -> bool:
    if row.get("symbol") not in gainers:
        return False
    return float(row.get("dist_pct") or 0) >= min_dist_pct
