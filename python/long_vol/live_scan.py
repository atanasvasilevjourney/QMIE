"""
Live scanner path — same feature + signal code as research, closed 15m bar only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from long_vol.config import EntryConfig, ExitConfig, LongVolConfig
from long_vol.data.validate import validate_ohlcv
from long_vol.features.long_vol_features import btc_ok_series, compute_long_vol_features
from long_vol.signals.long_vol_breakout import SymbolRuntime, evaluate_bar


@dataclass
class LongVolCandidate:
    symbol: str
    timestamp: pd.Timestamp
    side: str = "BUY"
    price: float = 0.0
    stop_loss: float = 0.0
    alert: bool = False
    gates: dict[str, bool] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    state: str = ""


def liquidity_ok(df15: pd.DataFrame, *, min_quote_vol: float, max_spread_median: float) -> tuple[bool, dict[str, float]]:
    """24h quote-volume and spread proxy from last 96×15m bars (~24h)."""
    tail = df15.tail(96)
    if len(tail) < 48:
        return False, {"quote_vol_24h": 0.0, "spread_median": 1.0}
    quote = float((tail["close"] * tail["volume"]).sum())
    spread = ((tail["high"] - tail["low"]) / tail["close"].replace(0, pd.NA)).median()
    spread_f = float(spread) if pd.notna(spread) else 1.0
    ok = quote >= min_quote_vol and spread_f <= max_spread_median
    return ok, {"quote_vol_24h": quote, "spread_median": spread_f}


def scan_closed_bar(
    symbol: str,
    df15: pd.DataFrame,
    *,
    cfg: LongVolConfig,
    btc15: pd.DataFrame,
    runtime: Optional[SymbolRuntime] = None,
) -> tuple[LongVolCandidate, SymbolRuntime]:
    """
    Evaluate the **last closed** 15m bar (drop forming bar if present).

    Exchange klines are closed bars; last row = most recently closed bar.
    """
    runtime = runtime or SymbolRuntime()
    if df15 is None or len(df15) < cfg.features.vwap_bars + 10:
        return LongVolCandidate(symbol=symbol, timestamp=pd.Timestamp.now("UTC"), reason="insufficient_bars"), runtime

    work = df15.sort_index()
    rep = validate_ohlcv(work, timeframe="15m")
    lv = compute_long_vol_features(work, cfg=cfg.features, blocked=rep.blocked_mask)
    feat = lv.df15
    ts = feat.index[-1]
    row = feat.iloc[-1]
    if bool(rep.blocked_mask.reindex(feat.index).iloc[-1]):
        return LongVolCandidate(
            symbol=symbol, timestamp=ts, reason="bar_blocked",
            features=_feat_snapshot(row),
        ), runtime

    bok = btc_ok_series(btc15.sort_index(), cfg.features.vwap_bars)
    btc_flag = bool(bok.reindex(feat.index).iloc[-1]) if len(bok) else False

    liq_ok, liq_meta = liquidity_ok(
        work,
        min_quote_vol=cfg.universe.min_24h_quote_volume_usdt,
        max_spread_median=cfg.universe.max_spread_proxy_median,
    )

    entry, exit_i, runtime, meta = evaluate_bar(
        symbol,
        ts,
        row,
        runtime=runtime,
        btc_ok=btc_flag,
        ent=cfg.entry,
        ex=cfg.exit,
        liquidity_ok=liq_ok,
        in_position=False,
    )

    gates = dict(meta.get("gates") or {})
    cand = LongVolCandidate(
        symbol=symbol,
        timestamp=ts,
        price=float(row["close"]),
        gates=gates,
        features={**_feat_snapshot(row), **liq_meta},
        state=runtime.state.name,
        reason=str(meta.get("transition") or ""),
    )

    if entry is not None and gates and all(gates.values()):
        cand.alert = True
        cand.stop_loss = float(entry.stop)
        cand.price = float(row["close"])
        cand.reason = entry.reason
        # Cooldown after signal fire (entry at next open — alert on close)
        runtime.cooldown_until = ts + pd.Timedelta(minutes=15 * cfg.entry.cooldown_bars)

    return cand, runtime


def _feat_snapshot(row: pd.Series) -> dict[str, Any]:
    keys = (
        "dist_atr", "rvol", "vwap24", "rsi_1h", "adx", "adx_slope",
        "width_pct", "don_up_1h", "close_1h", "compression_ok",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in row.index and pd.notna(row[k]):
            v = row[k]
            out[k] = float(v) if isinstance(v, (float, int)) else v
    return out


def candidate_to_scan_fields(cand: LongVolCandidate) -> dict[str, Any]:
    """Desk / API friendly dict."""
    return {
        "symbol": cand.symbol,
        "timestamp": cand.timestamp.isoformat(),
        "side": cand.side,
        "alert": cand.alert,
        "price": cand.price,
        "stop_loss": cand.stop_loss,
        "reason": cand.reason,
        "state": cand.state,
        "gates": cand.gates,
        "features": cand.features,
    }
