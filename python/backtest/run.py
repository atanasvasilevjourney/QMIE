"""
QMIE Backtest CLI
=================
Usage:
    cd python
    python -m backtest.run --symbols BTCUSDT ETHUSDT --tf 1h 4h --start 2023-01-01
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .data_loader import load_klines
from .runner import run_backtest, results_to_dataframe

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# HTF map: base TF → pandas resample rule for HTF
_HTF_MAP = {"1h": "4h", "4h": "1D", "1d": "1W"}

_DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
]


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="QMIE Backtest Runner")
    p.add_argument("--symbols", nargs="+", default=_DEFAULT_SYMBOLS,
                   help="Symbols to backtest")
    p.add_argument("--tf", nargs="+", default=["1h", "4h"],
                   help="Timeframes")
    p.add_argument("--start", default=str(date.today() - timedelta(days=730)),
                   help="Start date YYYY-MM-DD (default: 2 years ago)")
    p.add_argument("--end", default=str(date.today() - timedelta(days=1)),
                   help="End date YYYY-MM-DD (default: yesterday)")
    p.add_argument("--out", default=str(Path(__file__).parent / "results"),
                   help="Output directory for parquet files")
    p.add_argument("--split", default=None,
                   help="Walk-forward split date YYYY-MM-DD. "
                        "Signals before split = in-sample, on/after = out-of-sample.")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_results = []
    combos = [(s, tf) for s in args.symbols for tf in args.tf]
    print(f"Running {len(combos)} symbol/tf combinations ({start} to {end})\n")

    for symbol, tf in combos:
        print(f"  {symbol} {tf} ...", end=" ", flush=True)
        htf_rule = _HTF_MAP.get(tf, "1D")
        df = load_klines(symbol, tf, start, end)
        if len(df) < 350:
            print(f"skipped (only {len(df)} bars)")
            continue
        results = run_backtest(symbol, tf, df, htf_rule=htf_rule)
        all_results.extend(results)
        print(f"{len(results)} signals")

    df_out = results_to_dataframe(all_results)

    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    stamped = out_dir / f"backtest_{ts}.parquet"
    latest = out_dir / "latest.parquet"
    df_out.to_parquet(stamped, index=False)
    df_out.to_parquet(latest, index=False)

    # Print summary table(s)
    print(f"\nTotal signals: {len(df_out)}")

    def _print_summary(label: str, subset: pd.DataFrame) -> None:
        closed = subset[subset["outcome"] != "OPEN"]
        if closed.empty:
            print(f"\n{label}: no closed trades")
            return
        grade_order = ["A+", "A", "B", "C"]
        rows = []
        for g in grade_order:
            g_df = closed[closed["grade"] == g]
            if len(g_df) == 0:
                continue
            rows.append({
                "Grade": g,
                "Signals": len(subset[subset["grade"] == g]),
                "Closed": len(g_df),
                "Win %": f"{100 * (g_df['outcome'] == 'WIN').mean():.1f}%",
                "Avg bars": f"{g_df['bars_to_outcome'].mean():.1f}",
            })
        print(f"\n{label} ({len(subset)} signals):")
        print(pd.DataFrame(rows).set_index("Grade").to_string())

    if len(df_out):
        split_date = date.fromisoformat(args.split) if args.split else None
        if split_date:
            split_ts = pd.Timestamp(split_date, tz="UTC")
            in_sample = df_out[df_out["timestamp"] < split_ts]
            out_sample = df_out[df_out["timestamp"] >= split_ts]
            _print_summary(f"IN-SAMPLE  (< {split_date})", in_sample)
            _print_summary(f"OUT-OF-SAMPLE (>= {split_date})", out_sample)
        else:
            _print_summary("All signals", df_out)

    print(f"\nSaved: {latest}")
    print(f"       {stamped}")


if __name__ == "__main__":
    main()
