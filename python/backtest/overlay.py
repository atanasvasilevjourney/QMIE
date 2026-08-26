"""
KovaView checklist overlays on frozen backtest signals
======================================================
Post-filters only. Does not call compute_signal. Does not retune W_*.
Uses production ``evaluate_native`` items too_late / btc_regime.
Two-loss cooldown is not applied (it locked a 4h alert stream).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from improve.checklist import evaluate_native
from scanner.indicators import adx
from scanner.radar import RadarConfig, classify_rgg_series

OVERLAY_GATES = ("too_late", "btc_regime")


def radar_state_table(
    df: pd.DataFrame,
    symbol: str,
    *,
    cfg: Optional[RadarConfig] = None,
) -> pd.DataFrame:
    """One row per daily bar: color, late-stage, days_in_state (Pine radar rules)."""
    cfg = cfg or RadarConfig()
    cfg.validate()
    if df is None or len(df) == 0:
        return pd.DataFrame(
            columns=["symbol", "color", "is_late_stage", "days_in_state", "pct_since_flip"]
        )

    plus_di, minus_di, adx_s = adx(df, cfg.adx_length)
    colors = classify_rgg_series(
        plus_di, minus_di, adx_s,
        enter_adx=cfg.enter_adx,
        exit_adx=cfg.exit_adx,
    )
    n = len(colors)
    days = np.ones(n, dtype=int)
    for i in range(1, n):
        if colors.iloc[i] == colors.iloc[i - 1]:
            days[i] = days[i - 1] + 1
        else:
            days[i] = 1

    close = df["close"].astype(float)
    pct = np.full(n, np.nan)
    late = np.zeros(n, dtype=bool)
    for i in range(n):
        d = int(days[i])
        flip_idx = i - d + 1
        censored = flip_idx <= 0
        if censored:
            continue
        entry = float(close.iloc[flip_idx])
        if entry <= 0:
            continue
        move = (float(close.iloc[i]) - entry) / entry * 100.0
        pct[i] = round(move, 2)
        if d >= cfg.late_stage_days:
            col = str(colors.iloc[i])
            if col == "GREEN" and move >= cfg.late_stage_move_pct:
                late[i] = True
            elif col == "RED" and move <= -cfg.late_stage_move_pct:
                late[i] = True

    return pd.DataFrame(
        {
            "symbol": symbol.upper(),
            "color": colors.astype(str).values,
            "is_late_stage": late,
            "days_in_state": days,
            "pct_since_flip": pct,
        },
        index=df.index,
    )


def _lookup_row(table: pd.DataFrame, ts: pd.Timestamp) -> Optional[dict[str, Any]]:
    if table is None or table.empty:
        return None
    sl = table.loc[:ts]
    if sl.empty:
        return None
    last = sl.iloc[-1]
    pct = last.get("pct_since_flip")
    return {
        "symbol": str(last["symbol"]).upper(),
        "color": str(last["color"]).upper(),
        "is_late_stage": bool(last["is_late_stage"]),
        "days_in_state": int(last["days_in_state"]),
        "pct_since_flip": None if pct is None or (isinstance(pct, float) and np.isnan(pct)) else float(pct),
    }


def radar_snapshot_at(
    tables: dict[str, pd.DataFrame],
    ts: pd.Timestamp,
    symbols: Iterable[str],
) -> dict[str, Any]:
    rows = []
    seen: set[str] = set()
    for raw in symbols:
        sym = str(raw or "").upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        table = tables.get(sym)
        if table is None:
            continue
        row = _lookup_row(table, ts)
        if row:
            rows.append(row)
    return {"rows": rows}


def result_to_signal_row(r: Any, *, signal_id: int) -> dict[str, Any]:
    """Map a BacktestResult (or dict) onto evaluate_native's stored-signal shape."""
    if not isinstance(r, dict):
        r = {
            "symbol": r.symbol,
            "side": r.side,
            "grade": r.grade,
            "score": r.score,
            "entry": r.entry,
            "stop_loss": r.stop_loss,
            "daily_trend": r.daily_trend,
            "timeframe": r.timeframe,
            "adx_value": r.adx_value,
            "atr_pct": r.atr_pct,
        }
    return {
        "id": signal_id,
        "symbol": str(r.get("symbol") or "").upper(),
        "side": str(r.get("side") or "").upper(),
        "grade": r.get("grade"),
        "score": r.get("score"),
        "signal_price": r.get("entry") or r.get("signal_price"),
        "stop_loss": r.get("stop_loss"),
        "daily_trend": r.get("daily_trend") or "unknown",
        "timestamp": r.get("timestamp"),
        "raw": json.dumps({
            "timeframe": r.get("timeframe"),
            "adx": r.get("adx_value") if r.get("adx_value") is not None else r.get("adx"),
            "atr_pct": r.get("atr_pct"),
            "bar_time": str(r.get("timestamp")) if r.get("timestamp") is not None else None,
        }),
    }


@dataclass
class OverlayDecision:
    skip: bool
    reasons: list[str]
    too_late: bool
    btc_regime: bool
    desk_verdict: str


def overlay_decision(
    signal_row: dict[str, Any],
    *,
    radar: Optional[dict[str, Any]],
) -> OverlayDecision:
    """SKIP only when a *new* overlay required-gate fails (not HTF/1h/ADX)."""
    chk = evaluate_native(signal_row, radar=radar)
    reasons: list[str] = []
    flags = {"too_late": False, "btc_regime": False}
    for item in chk.items:
        if item.id in flags and item.required and not item.passed:
            flags[item.id] = True
            reasons.append(item.id)
    return OverlayDecision(
        skip=bool(reasons),
        reasons=reasons,
        too_late=flags["too_late"],
        btc_regime=flags["btc_regime"],
        desk_verdict=chk.verdict,
    )


def annotate_closed(
    rows: list[dict[str, Any]],
    tables: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    """Apply too_late + btc_regime to closed trades. No loss-streak lockout."""
    ordered = sorted(rows, key=lambda r: (pd.Timestamp(r["timestamp"]), str(r.get("symbol") or "")))
    out: list[dict[str, Any]] = []
    for i, r in enumerate(ordered, start=1):
        ts = pd.Timestamp(r["timestamp"])
        radar = radar_snapshot_at(tables, ts, [r.get("symbol") or "", "BTCUSDT"])
        sig = result_to_signal_row(r, signal_id=i)
        dec = overlay_decision(sig, radar=radar)
        rec = dict(r)
        rec["overlay_skip"] = dec.skip
        rec["overlay_reasons"] = ",".join(dec.reasons)
        rec["desk_verdict"] = dec.desk_verdict
        rec["too_late"] = dec.too_late
        rec["btc_regime_skip"] = dec.btc_regime
        out.append(rec)
    return out


def summarize(rows: list[dict[str, Any]], *, kept_only: bool = False) -> dict[str, Any]:
    sample = rows
    if kept_only:
        sample = [r for r in rows if not r.get("overlay_skip")]
    closed = [r for r in sample if str(r.get("outcome") or "").upper() in ("WIN", "LOSS")]
    n = len(closed)
    if n == 0:
        return {"n": 0, "wins": 0, "win_pct": None, "expectancy_r": None, "pf": None}
    wins = [r for r in closed if str(r["outcome"]).upper() == "WIN"]
    win_pct = 100.0 * len(wins) / n
    rs: list[float] = []
    for r in closed:
        v = r.get("realized_r")
        if v is None:
            rs.append(float(r.get("rr_ratio") or 0.0) if str(r["outcome"]).upper() == "WIN" else -1.0)
        else:
            rs.append(float(v))
    e_r = sum(rs) / n
    win_r = sum(x for x in rs if x > 0)
    loss_r = abs(sum(x for x in rs if x <= 0))
    pf = (win_r / loss_r) if loss_r > 0 else None
    return {
        "n": n,
        "wins": len(wins),
        "win_pct": round(win_pct, 1),
        "expectancy_r": round(e_r, 3),
        "pf": None if pf is None else round(pf, 2),
    }
