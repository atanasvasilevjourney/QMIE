from __future__ import annotations

from models import AssetClass, EventType, Grade, Side, TVSignal

from levier.config import LevierConfig


def leaderboard_to_tvsignal(row: dict, rank: int) -> TVSignal:
    ts = row["timestamp"]
    bar_ms = int(ts.value // 1_000_000) if hasattr(ts, "value") else None
    dist = float(row.get("dist_pct") or 0)
    return TVSignal(
        strategy="QMIE-LevierScan",
        event=EventType.ENTRY,
        symbol=str(row["symbol"]),
        asset_class=AssetClass.CRYPTO,
        timeframe="30m",
        side=Side.BUY if dist >= 0 else Side.SELL,
        signal_price=float(row["price"]),
        score=float(row.get("score") or 0),
        grade=Grade.B,
        trend="bullish" if dist >= 0 else "bearish",
        adx=float(row.get("adx") or 0),
        rsi=float(row.get("rsi") or 0),
        atr_pct=float(row.get("atr_pct") or 0),
        timestamp=ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        bar_time=bar_ms,
        reason=str(row.get("label") or "levier_leaderboard"),
        setup_type="levier_scan",
        action="watch",
        dist_atr=dist,
        rvol=float(row.get("quote_vol_24h") or 0),
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
