"""Bullish leaderboard scoring for 30m tape."""
from __future__ import annotations

import math
from typing import Any


def bullish_score(row: dict[str, Any]) -> float:
    """Higher = more 'leaderboard bullish' (LeveriScan ordering heuristic)."""
    if not row.get("ok"):
        return -1e9
    dist = float(row.get("dist_pct") or 0)
    if dist <= 0:
        return dist  # below VWAP sinks
    rsi = float(row.get("rsi") or 50)
    adx = float(row.get("adx") or 0)
    vol = math.log10(max(float(row.get("quote_vol_24h") or 1), 1))
    rsi_delta = float(row.get("rsi_delta") or 0)
    # Favor extension above VWAP + rising RSI + liquidity + some trend
    return (
        dist * 2.0
        + max(0, rsi_delta) * 0.4
        + min(rsi, 85) * 0.05
        + min(adx, 50) * 0.08
        + vol * 0.5
    )


def rank_rows(rows: list[dict[str, Any]], top_n: int = 10) -> list[dict[str, Any]]:
    scored = []
    for r in rows:
        if not r.get("ok"):
            continue
        atr_pct = float(r.get("atr_pct") or 0)
        if atr_pct <= 0:
            continue
        out = dict(r)
        out["score"] = bullish_score(r)
        scored.append(out)
    scored.sort(key=lambda x: x["score"], reverse=True)
    for i, row in enumerate(scored[:top_n], start=1):
        row["rank"] = i
    return scored[:top_n]
