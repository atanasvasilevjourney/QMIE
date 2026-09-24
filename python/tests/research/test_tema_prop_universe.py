"""TEMA prop universe KPIs (synthetic book, no network)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from research.trend_lab.tema_prop_universe import (
    PropRules,
    SimConfig,
    cash_kpis,
    compare_universes,
    evaluate_prop,
    filter_symbols,
    signal_kpis,
)


def _synthetic_book(n: int = 40) -> pd.DataFrame:
    idx = pd.date_range("2025-01-05", periods=n, freq="4h", tz="UTC")
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    rows = []
    for i, ts in enumerate(idx):
        sym = syms[i % len(syms)]
        win = i % 3 != 1
        rows.append(
            {
                "symbol": sym,
                "timestamp": ts,
                "exit_ts": ts + pd.Timedelta(hours=16),
                "entry": 100.0,
                "stop_loss": 98.5,
                "realized_r": 1.667 if win else -1.0,
                "outcome": "WIN" if win else "LOSS",
                "risk_pct": 0.015,
                "grade": "A+" if win else "A",
                "score": 90.0 - (i % 5),
                "atr_pct": 1.2,
                "adx_value": 25.0,
                "bars_to_outcome": 4,
                "timeframe": "4h",
            }
        )
    return pd.DataFrame(rows)


def test_filter_symbols_top3():
    book = _synthetic_book()
    f = filter_symbols(book, ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    assert set(f["symbol"].unique()) <= {"BTCUSDT", "ETHUSDT", "SOLUSDT"}


def test_signal_kpis_positive_edge():
    book = _synthetic_book()
    k = signal_kpis(book)
    assert k["n"] == len(book)
    assert k["expectancy_r"] is not None
    assert k["expectancy_r"] > 0


def test_prop_eval_passes_small_dd():
    book = _synthetic_book()
    cash = cash_kpis(book, SimConfig(start_cash=10_000.0, stake_pct=0.01))
    prop = evaluate_prop(cash, PropRules(min_closed_trades=5))
    assert prop["checks"]["not_blown"] is True
    assert "prop_compliant" in prop


def test_compare_universes_from_parquet(tmp_path: Path):
    book = _synthetic_book(60)
    path = tmp_path / "latest.parquet"
    book.to_parquet(path, index=False)
    payload = compare_universes(path, start="2025-01-01")
    assert "top3" in payload["universes"]
    assert "top10" in payload["universes"]
    assert payload["universes"]["top3"]["n_book"] <= payload["universes"]["top10"]["n_book"]
