"""Strategy performance snapshot for research notebooks (read-only)."""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.data_loader import load_klines
from backtest.runner import run_backtest, results_to_dataframe

PYTHON_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PYTHON_ROOT / "data" / "qmie.db"

# Canonical frozen OOS from docs/backtest-baseline.md (do not edit without re-run).
FROZEN_BASELINE: dict[str, Any] = {
    "engine": "TEMA 9/90/199 · 7-component · SL 1.5×ATR TP 2.5×ATR",
    "split": "2025-01-01",
    "filters": "ATR% 0.4–4.0 · ADX ≥ 20",
    "combined_aa_oos": {
        "closed": 12744,
        "win_pct": 42.1,
        "expectancy_r": 0.122,
        "profit_factor": 1.21,
        "sharpe": 1.30,
    },
    "four_h_aa_oos": {
        "closed": 2152,
        "win_pct": 49.1,
        "expectancy_r": 0.309,
        "profit_factor": 1.61,
        "sharpe": 2.09,
    },
    "one_h_aa_oos": {
        "closed": 10592,
        "win_pct": 40.6,
        "expectancy_r": 0.084,
        "profit_factor": 1.14,
        "sharpe": 0.89,
    },
    "proposed_knob": "SCAN_TIMEFRAMES → 4h only (not applied)",
}

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
]

GOALS = {
    "min_win_pct": 48.0,
    "min_expectancy_r": 0.15,
    "min_sharpe": 1.0,
    "min_profit_factor": 1.3,
}


@dataclass(frozen=True)
class AASummary:
    label: str
    signals: int
    closed: int
    win_pct: float
    expectancy_r: float
    profit_factor: float
    sharpe: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "signals": self.signals,
            "closed": self.closed,
            "win_pct": round(self.win_pct, 2),
            "expectancy_r": round(self.expectancy_r, 4),
            "profit_factor": round(self.profit_factor, 3),
            "sharpe": round(self.sharpe, 3),
        }


def summarize_aa(df: pd.DataFrame, *, label: str = "A/A+") -> AASummary | None:
    if df.empty:
        return None
    sub = df[df["grade"].isin(["A", "A+"])].copy()
    closed = sub[sub["outcome"].isin(["WIN", "LOSS"])]
    if closed.empty:
        return AASummary(label, len(sub), 0, 0.0, 0.0, 0.0, 0.0)
    win_rate = (closed["outcome"] == "WIN").mean()
    avg_rr = float(closed["rr_ratio"].mean())
    expectancy = win_rate * avg_rr - (1.0 - win_rate)
    wins_r = closed.loc[closed["outcome"] == "WIN", "rr_ratio"].sum()
    losses_r = float(len(closed[closed["outcome"] == "LOSS"]))
    pf = float(wins_r / losses_r) if losses_r > 0 else float("inf")
    r_series = closed["realized_r"].dropna()
    sharpe = 0.0
    if len(r_series) >= 30 and r_series.std() > 0:
        daily_r = (
            closed.set_index("timestamp")["realized_r"]
            .dropna()
            .resample("1D")
            .sum()
        )
        if len(daily_r) >= 30 and daily_r.std() > 0:
            sharpe = float(daily_r.mean() / daily_r.std() * math.sqrt(365))
    return AASummary(
        label=label,
        signals=len(sub),
        closed=len(closed),
        win_pct=100.0 * win_rate,
        expectancy_r=expectancy,
        profit_factor=pf,
        sharpe=sharpe,
    )


def run_tema_backtest(
    symbols: list[str],
    timeframes: list[str],
    start: date,
    end: date,
    *,
    split: date | None = None,
    min_adx: float = 20.0,
    min_atr_pct: float = 0.4,
    max_atr_pct: float = 4.0,
) -> tuple[pd.DataFrame, dict[str, AASummary | None]]:
    """Vision walk-forward; returns filtered frame and OOS A/A+ summaries per TF."""
    htf_map = {"1h": "4h", "4h": "1D", "1d": "1W"}
    all_results = []
    for symbol in symbols:
        for tf in timeframes:
            htf = htf_map.get(tf, "1D")
            df = load_klines(symbol, tf, start, end)
            if len(df) < 350:
                continue
            all_results.extend(run_backtest(symbol, tf, df, htf_rule=htf))
    frame = results_to_dataframe(all_results)
    if frame.empty:
        return frame, {}
    frame = frame[
        (frame["atr_pct"] >= min_atr_pct) & (frame["atr_pct"] <= max_atr_pct)
    ]
    if min_adx > 0 and "adx_value" in frame.columns:
        frame = frame[frame["adx_value"] >= min_adx]
    split_ts = pd.Timestamp(split, tz="UTC") if split else None
    summaries: dict[str, AASummary | None] = {}
    if split_ts is not None:
        oos = frame[frame["timestamp"] >= split_ts]
        for tf in timeframes:
            summaries[tf] = summarize_aa(oos[oos["timeframe"] == tf], label=f"OOS {tf} A/A+")
        summaries["all"] = summarize_aa(oos, label="OOS all TF A/A+")
    else:
        summaries["all"] = summarize_aa(frame, label="All A/A+")
    return frame, summaries


def journal_stats_sync(db_path: Path | None = None) -> dict[str, Any]:
    path = db_path or DEFAULT_DB
    if not path.exists():
        return {"error": "no_db", "path": str(path)}
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT f.outcome, f.realized_r, f.pnl, f.source, s.grade, s.raw
        FROM fills f
        JOIN signals s ON s.id = f.signal_id
        WHERE s.grade IN ('A+', 'A')
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    closed = [r for r in rows if r.get("outcome") not in (None, "OPEN")]
    wins = [r for r in closed if r.get("outcome") == "WIN"]
    import json

    def tf_of(raw: str | None) -> str:
        if not raw:
            return "unknown"
        try:
            return str(json.loads(raw).get("timeframe") or "unknown").lower()
        except json.JSONDecodeError:
            return "unknown"

    by_tf: dict[str, int] = {}
    manual_4h = 0
    for r in closed:
        tf = tf_of(r.get("raw"))
        by_tf[tf] = by_tf.get(tf, 0) + 1
        if str(r.get("source") or "manual") != "paper" and tf in ("4h", "240"):
            manual_4h += 1
    r_vals = [float(r["realized_r"]) for r in closed if r.get("realized_r") is not None]
    return {
        "fills": len(rows),
        "closed": len(closed),
        "wins": len(wins),
        "win_pct": round(100.0 * len(wins) / len(closed), 1) if closed else 0.0,
        "avg_realized_r": round(sum(r_vals) / len(r_vals), 3) if r_vals else None,
        "by_timeframe": by_tf,
        "manual_4h_closed": manual_4h,
        "note": "Live book — not frozen OOS; need 30 manual 4h closes for edge claim",
    }


def goals_check(summary: AASummary | None) -> dict[str, bool]:
    if summary is None or summary.closed == 0:
        return {k: False for k in ("win_pct", "expectancy_r", "sharpe", "profit_factor")}
    return {
        "win_pct": bool(summary.win_pct >= GOALS["min_win_pct"]),
        "expectancy_r": bool(summary.expectancy_r >= GOALS["min_expectancy_r"]),
        "sharpe": bool(summary.sharpe >= GOALS["min_sharpe"]),
        "profit_factor": bool(summary.profit_factor >= GOALS["min_profit_factor"]),
    }


def default_window() -> tuple[date, date, date]:
    end = date.today() - timedelta(days=1)
    start = date(2024, 1, 1)
    split = date(2025, 1, 1)
    return start, end, split
