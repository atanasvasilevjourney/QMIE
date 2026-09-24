"""Smoke tests for Top-10 TEMA prop plots (no network)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from research.trend_lab.tema_prop_plots import (
    plot_cumulative_r,
    plot_equity_and_drawdown,
    render_top10_plots,
    symbol_stats,
)
from research.trend_lab.tema_prop_universe import SimConfig, run_paper_sim


def _book(n: int = 50) -> pd.DataFrame:
    idx = pd.date_range("2025-02-01", periods=n, freq="4h", tz="UTC")
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    rows = []
    for i, ts in enumerate(idx):
        win = i % 4 != 0
        rows.append(
            {
                "symbol": syms[i % len(syms)],
                "timestamp": ts,
                "exit_ts": ts + pd.Timedelta(hours=12),
                "entry": 100.0,
                "stop_loss": 98.5,
                "realized_r": 1.667 if win else -1.0,
                "outcome": "WIN" if win else "LOSS",
                "risk_pct": 0.015,
                "grade": "A+" if win else "A",
                "score": 70.0 + (i % 20),
                "atr_pct": 1.0,
                "adx_value": 25.0,
                "bars_to_outcome": 3,
                "timeframe": "4h",
            }
        )
    return pd.DataFrame(rows)


def test_symbol_stats_sorted():
    stats = symbol_stats(_book())
    assert len(stats) == 4
    assert stats["expectancy_r"].is_monotonic_increasing


def test_plot_png_written(tmp_path: Path):
    book = _book()
    sim, _ = run_paper_sim(book, SimConfig())
    out = tmp_path / "eq.png"
    plot_equity_and_drawdown(sim, out)
    assert out.exists() and out.stat().st_size > 500
    plot_cumulative_r(book, tmp_path / "cum.png")
    assert (tmp_path / "cum.png").exists()


def test_render_top10_from_parquet(tmp_path: Path):
    book = _book(80)
    for sym in ("XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"):
        extra = book.copy()
        extra["symbol"] = sym
        book = pd.concat([book, extra.iloc[:5]], ignore_index=True)
    pq = tmp_path / "latest.parquet"
    book.to_parquet(pq, index=False)
    paths = render_top10_plots(pq, tmp_path / "plots", also_cursor=False)
    assert "equity_dd" in paths
    assert Path(paths["equity_dd"]).exists()
