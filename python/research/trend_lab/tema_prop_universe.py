"""TEMA 4h A/A+ prop-style KPIs on Top-3 vs Top-10 universes.

Research only — does not retune ``W_*`` or place orders. Uses frozen
``backtest/results/latest.parquet`` when present (``python -m backtest.run``).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from backtest.cash_sim import load_book, simulate
from backtest.overlay import summarize

TOP3_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

TOP10_SYMBOLS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
)

UNIVERSES: dict[str, tuple[str, ...]] = {
    "top3": TOP3_SYMBOLS,
    "top10": TOP10_SYMBOLS,
}


@dataclass(frozen=True)
class PropRules:
    """Typical evaluation-style limits (configurable, not legal advice)."""

    max_trailing_dd_pct: float = 10.0
    max_daily_loss_pct: float = 5.0
    max_liquidations: int = 0
    require_not_blown: bool = True
    min_closed_trades: int = 30
    min_expectancy_r: float = 0.0
    min_profit_factor: float = 1.0


@dataclass(frozen=True)
class SimConfig:
    start_cash: float = 10_000.0
    stake_pct: float = 0.01
    max_slots: int = 3
    leverage: float = 1.0
    isolated: bool = True
    one_per_symbol: bool = True
    rank_by_score: bool = True


def default_parquet() -> Path:
    return Path(__file__).resolve().parents[2] / "backtest" / "results" / "latest.parquet"


def filter_symbols(book: pd.DataFrame, symbols: tuple[str, ...]) -> pd.DataFrame:
    syms = {s.upper() for s in symbols}
    out = book[book["symbol"].str.upper().isin(syms)].copy()
    return out.reset_index(drop=True)


def _daily_r_sharpe(book: pd.DataFrame) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if book.empty:
        return None, None, None
    rs = book.sort_values("timestamp")["realized_r"].astype(float)
    ts = pd.to_datetime(book.sort_values("timestamp")["timestamp"], utc=True)
    daily = pd.Series(rs.values, index=ts).resample("1D").sum()
    daily = daily[daily != 0]
    if len(daily) < 2:
        return None, None, None
    mean = float(daily.mean())
    std = float(daily.std(ddof=1))
    if std <= 0:
        sharpe = None
    else:
        sharpe = round(mean / std * math.sqrt(365), 2)
    downside = daily[daily < 0]
    dstd = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = round(mean / dstd * math.sqrt(365), 2) if dstd > 0 else None
    cum = daily.cumsum()
    max_dd_r = round(float((cum - cum.cummax()).min()), 1)
    return sharpe, sortino, max_dd_r


def signal_kpis(book: pd.DataFrame) -> dict[str, Any]:
    base = summarize(book.to_dict(orient="records"), kept_only=False)
    sharpe, sortino, max_dd_r = _daily_r_sharpe(book)
    rs = book["realized_r"].astype(float)
    r_std = float(rs.std(ddof=1)) if len(rs) > 1 else 0.0
    sqn = round(float(rs.mean()) / r_std * math.sqrt(len(rs)), 2) if r_std > 0 else None
    base.update(
        {
            "sharpe": sharpe,
            "sortino": sortino,
            "max_dd_r": max_dd_r,
            "sqn": sqn,
            "symbols": sorted(book["symbol"].str.upper().unique().tolist()),
        }
    )
    return base


def _curve_daily_metrics(
    curve: list[dict[str, Any]], start_cash: float
) -> tuple[float, float]:
    if not curve:
        return 0.0, 0.0
    c = pd.DataFrame(curve)
    c["timestamp"] = pd.to_datetime(c["timestamp"], utc=True)
    c = c.sort_values("timestamp").set_index("timestamp")
    daily = c["equity"].resample("1D").last().ffill()
    if daily.empty:
        return 0.0, 0.0
    peak = float(daily.cummax().max())
    trough_dd = float((daily - daily.cummax()).min())
    max_dd_pct = 100.0 * abs(trough_dd) / peak if peak > 0 else 0.0
    daily_pnl = daily.diff().fillna(0.0)
    worst_day = float(daily_pnl.min())
    worst_daily_loss_pct = 100.0 * abs(worst_day) / start_cash if worst_day < 0 else 0.0
    return round(max_dd_pct, 2), round(worst_daily_loss_pct, 2)


def cash_kpis(book: pd.DataFrame, cfg: SimConfig) -> dict[str, Any]:
    stake = round(cfg.start_cash * cfg.stake_pct, 2)
    sim = simulate(
        book,
        start_cash=cfg.start_cash,
        stake=stake,
        max_slots=cfg.max_slots,
        leverage=cfg.leverage,
        rank_by_score=cfg.rank_by_score,
        one_per_symbol=cfg.one_per_symbol,
        isolated=cfg.isolated,
    )
    taken = sim["taken_rows"]
    sig_taken = signal_kpis(taken) if len(taken) else signal_kpis(book.iloc[0:0])
    max_dd_usd = abs(float(sim["max_dd"]))
    peak = float(sim["peak"]) if sim["peak"] else cfg.start_cash
    max_dd_pct_curve, worst_daily_pct = _curve_daily_metrics(sim["curve"], cfg.start_cash)
    max_dd_pct = round(100.0 * max_dd_usd / peak, 2) if peak > 0 else 0.0
    profit_pct = round(100.0 * float(sim["pnl"]) / cfg.start_cash, 2)
    win_pct = round(100.0 * sim["wins"] / sim["taken"], 1) if sim["taken"] else None
    return {
        "start_cash": cfg.start_cash,
        "stake_usd": stake,
        "stake_pct": cfg.stake_pct,
        "max_slots": cfg.max_slots,
        "leverage": cfg.leverage,
        "isolated": cfg.isolated,
        "taken": sim["taken"],
        "skipped": sim["skipped"],
        "wins": sim["wins"],
        "win_pct": win_pct,
        "liquidations": sim["liquidations"],
        "blown": bool(sim["blown"]),
        "final_equity": round(float(sim["final"]), 2),
        "pnl_usd": round(float(sim["pnl"]), 2),
        "profit_pct": profit_pct,
        "max_dd_usd": round(max_dd_usd, 2),
        "max_dd_pct": max_dd_pct,
        "max_dd_pct_daily_curve": max_dd_pct_curve,
        "worst_daily_loss_pct": worst_daily_pct,
        "max_open": sim["max_open"],
        "book_signals": signal_kpis(book),
        "taken_signals": sig_taken,
    }


def evaluate_prop(cash: dict[str, Any], rules: PropRules) -> dict[str, Any]:
    checks = {
        "trailing_dd_ok": cash["max_dd_pct_daily_curve"] <= rules.max_trailing_dd_pct,
        "daily_loss_ok": cash["worst_daily_loss_pct"] <= rules.max_daily_loss_pct,
        "liquidations_ok": cash["liquidations"] <= rules.max_liquidations,
        "not_blown": (not cash["blown"]) if rules.require_not_blown else True,
        "min_trades_ok": cash["taken"] >= rules.min_closed_trades,
        "expectancy_ok": float(cash["taken_signals"]["expectancy_r"] or 0)
        >= rules.min_expectancy_r,
        "pf_ok": float(cash["taken_signals"]["pf"] or 0) >= rules.min_profit_factor,
    }
    prop_compliant = all(checks.values())
    return {"prop_compliant": prop_compliant, "checks": checks}


def load_oos_book(
    parquet: Path,
    symbols: tuple[str, ...],
    *,
    tf: str = "4h",
    start: str = "2025-01-01",
    end: Optional[str] = None,
    min_adx: float = 20.0,
    min_atr_pct: float = 0.4,
    max_atr_pct: float = 4.0,
) -> pd.DataFrame:
    book = load_book(
        parquet,
        tf=tf,
        start=start,
        end=end,
        min_adx=min_adx,
        min_atr_pct=min_atr_pct,
        max_atr_pct=max_atr_pct,
    )
    return filter_symbols(book, symbols)


def run_universe(
    name: str,
    symbols: tuple[str, ...],
    parquet: Path,
    *,
    sim: SimConfig | None = None,
    rules: PropRules | None = None,
    **load_kw: Any,
) -> dict[str, Any]:
    sim = sim or SimConfig()
    rules = rules or PropRules()
    book = load_oos_book(parquet, symbols, **load_kw)
    cash = cash_kpis(book, sim)
    prop = evaluate_prop(cash, rules)
    return {
        "universe": name,
        "symbols": list(symbols),
        "n_book": len(book),
        "signal_kpis": cash["book_signals"],
        "cash_sim": {k: v for k, v in cash.items() if k not in ("book_signals", "taken_signals")},
        "taken_signal_kpis": cash["taken_signals"],
        "prop": prop,
        "rules": asdict(rules),
        "sim": asdict(sim),
    }


def compare_universes(
    parquet: Path,
    *,
    sim: SimConfig | None = None,
    rules: PropRules | None = None,
    **load_kw: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {"parquet": str(parquet), "universes": {}}
    for key, syms in UNIVERSES.items():
        out["universes"][key] = run_universe(
            key, syms, parquet, sim=sim, rules=rules, **load_kw
        )
    return out


def kpi_table(payload: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for key, block in payload.get("universes", {}).items():
        sig = block["signal_kpis"]
        cash = block["cash_sim"]
        prop = block["prop"]
        rows.append(
            {
                "universe": key,
                "n_signals": sig.get("n"),
                "win_pct": sig.get("win_pct"),
                "expectancy_r": sig.get("expectancy_r"),
                "pf": sig.get("pf"),
                "sharpe_r": sig.get("sharpe"),
                "sqn": sig.get("sqn"),
                "taken": cash.get("taken"),
                "profit_pct": cash.get("profit_pct"),
                "max_dd_pct": cash.get("max_dd_pct_daily_curve"),
                "worst_day_pct": cash.get("worst_daily_loss_pct"),
                "liquidations": cash.get("liquidations"),
                "blown": cash.get("blown"),
                "prop_compliant": prop.get("prop_compliant"),
            }
        )
    return pd.DataFrame(rows)
