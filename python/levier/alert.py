from __future__ import annotations

from models import AssetClass, EventType, Grade, Side, TVSignal

from levier.config import LevierConfig


def _display_symbol(row: dict) -> str:
    sym = str(row["symbol"]).replace("USDT", "")
    tag = row.get("venue") or ""
    return f"${sym}" + (f" [{tag}]" if tag else "")


def leaderboard_to_tvsignal(row: dict, rank: int) -> TVSignal:
    ts = row["timestamp"]
    bar_ms = int(ts.value // 1_000_000) if hasattr(ts, "value") else None
    dist_pct = float(row.get("dist_pct") or 0)
    rsi_d = row.get("rsi_delta")
    rsi_part = f"{float(row.get('rsi') or 0):.0f}"
    if rsi_d is not None:
        rsi_part += f" ({int(rsi_d):+d})"
    return TVSignal(
        strategy="QMIE-LevierScan",
        event=EventType.ENTRY,
        symbol=str(row["symbol"]),
        asset_class=AssetClass.CRYPTO,
        timeframe="30m",
        side=Side.BUY if dist_pct >= 0 else Side.SELL,
        signal_price=float(row["price"]),
        score=float(row.get("score") or 0),
        grade=Grade.B,
        trend="bullish" if dist_pct >= 0 else "bearish",
        adx=float(row.get("adx") or 0),
        rsi=float(row.get("rsi") or 0),
        atr_pct=float(row.get("atr_pct") or 0),
        timestamp=ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        bar_time=bar_ms,
        reason=str(row.get("label") or "levier_leaderboard"),
        setup_type="levier_scan",
        action="watch",
        levier_rank=int(rank),
        levier_display=_display_symbol(row),
        levier_vwap24=float(row.get("vwap24") or 0),
        levier_dist=float(row.get("dist") or 0),
        levier_dist_pct=dist_pct,
        levier_rsi_label=rsi_part,
        levier_quote_vol=float(row.get("quote_vol_24h") or 0),
        levier_gainer_watch=bool(row.get("gainer_watch")),
        venue_tag=str(row.get("venue") or ""),
    )


def pick_alert_rows(
    board: list[dict],
    cfg: LevierConfig,
    *,
    prev_top_symbols: set[str],
) -> list[dict]:
    if not board:
        return []
    out: list[dict] = []
    for row in board[: cfg.alerts.notify_top_n]:
        if float(row.get("dist_pct") or 0) < cfg.alerts.min_dist_pct_for_alert:
            continue
        sym = str(row["symbol"])
        if cfg.alerts.notify_new_leader_only and sym in prev_top_symbols:
            continue
        out.append(row)
    return out
