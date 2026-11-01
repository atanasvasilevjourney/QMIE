from __future__ import annotations

from typing import Any

import pandas as pd

from levier.config import LevierConfig
from levier.features import compute_tape_row, tape_label
from levier.gainers import mark_gainer_watch, yesterday_top_movers
from levier.hl_symbols import venue_tag
from levier.rank import rank_rows


def scan_universe(
    panels: dict[str, pd.DataFrame],
    cfg: LevierConfig,
    *,
    prev_rsi: dict[str, float] | None = None,
) -> dict[str, Any]:
    prev_rsi = prev_rsi or {}
    uni = cfg.universe
    rows: list[dict] = []
    for sym, df in panels.items():
        if df is None or len(df) < cfg.scan.min_bars:
            continue
        row = compute_tape_row(
            df,
            vwap_bars=cfg.scan.vwap_bars,
            atr_len=cfg.scan.atr_length,
            rsi_len=cfg.scan.rsi_length,
            adx_len=cfg.scan.adx_length,
            prev_rsi=prev_rsi.get(sym),
        )
        if not row.get("ok"):
            continue
        atr_pct = float(row.get("atr_pct") or 0)
        if atr_pct < uni.min_atr_pct or atr_pct > uni.max_atr_pct:
            continue
        if float(row.get("quote_vol_24h") or 0) < uni.min_24h_quote_volume_usdt:
            continue
        row["symbol"] = sym
        row["venue"] = venue_tag(sym)
        row["label"] = tape_label(
            float(row["dist_pct"]), float(row["rsi"]), float(row["adx"]),
        )
        rows.append(row)

    gainers = set(yesterday_top_movers(panels, top_n=cfg.gainers.top_n_yesterday))
    for row in rows:
        row["gainer_watch"] = mark_gainer_watch(
            row,
            gainers=gainers,
            min_dist_pct=cfg.gainers.continuation_min_dist_pct,
        )

    board = rank_rows(rows, top_n=uni.top_n_leaderboard)
    return {
        "rows": rows,
        "leaderboard": board,
        "gainers_yesterday": sorted(gainers),
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
    }
