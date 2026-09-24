"""Validate crypto-turtle style Donchian (20/10 + RSI/ATR) on Vision 1d.

Usage::

    python -m research.trend_lab.run_crypto_turtle_validation
    python -m research.trend_lab.run_crypto_turtle_validation --quick
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from .crypto_turtle import (
    TurtleCryptoParams,
    backtest_turtle_crypto,
    eval_turtle_crypto,
    export_signals_csv,
    plot_backtest_trades,
    plot_turtle_signals,
    turtle_signal_frame,
)
from .data import load_symbol
from .protocol import WARMUP_BARS

log = logging.getLogger("crypto_turtle")

TURTLE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "XLMUSDT"]
ART = Path(__file__).resolve().parents[1] / "artifacts"
CURSOR = Path("/opt/cursor/artifacts")


def _warmup() -> int:
    return max(WARMUP_BARS, 30)


def run(*, quick: bool = False) -> dict[str, Any]:
    symbols = TURTLE_SYMBOLS[:2] if quick else TURTLE_SYMBOLS
    p = TurtleCryptoParams()
    payload: dict[str, Any] = {"params": p.__dict__, "symbols": {}}

    for sym in symbols:
        df, src = load_symbol(sym, "1d")
        if df.empty:
            log.warning("skip %s (no data)", sym)
            continue
        ev = eval_turtle_crypto(df, p, warmup=_warmup())
        sig = ev["signal_frame"]
        _, all_trades = backtest_turtle_crypto(df, p)

        plot_dir = ART / "crypto_turtle" / "plots"
        csv_dir = ART / "crypto_turtle" / "signals"
        export_signals_csv(df, sig, csv_dir / f"signals_{sym}.csv")
        plot_turtle_signals(df, sig, sym, plot_dir / f"plot_signals_{sym}.png")
        oos_start = pd.Timestamp("2023-01-01", tz="UTC")
        oos_tr = [t for t in all_trades if t.entry_time >= oos_start]
        plot_backtest_trades(df.loc[oos_start:], oos_tr, sym, plot_dir / f"backtest_{sym}.png")

        payload["symbols"][sym] = {
            "source": src,
            "bars": len(df),
            "oos_kpis": ev["oos"],
            "oos_summary": ev["oos_summary"],
            "oos_attribution": ev["oos_attribution"].to_dict(orient="records"),
        }
        log.info("%s OOS trades=%s win_rate=%.1f%%", sym, ev["oos_summary"]["total_trades"], ev["oos_summary"]["win_rate_pct"])

    for root in (ART, CURSOR):
        try:
            root.mkdir(parents=True, exist_ok=True)
            (root / "crypto_turtle_validation.json").write_text(json.dumps(payload, indent=2, default=str))
        except OSError as exc:
            log.warning("write %s: %s", root, exc)

    return payload


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    ns = parser.parse_args()
    out = run(quick=ns.quick)
    rows = []
    for sym, block in out.get("symbols", {}).items():
        s = block["oos_summary"]
        rows.append({
            "symbol": sym,
            "trades": s["total_trades"],
            "win_rate_pct": s["win_rate_pct"],
            "total_profit_pct": s["total_profit_pct"],
            "oos_sharpe": block["oos_kpis"]["sharpe"],
        })
    if rows:
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
