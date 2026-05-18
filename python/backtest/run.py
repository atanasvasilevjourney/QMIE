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
import math
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
    p.add_argument("--min-atr-pct", type=float, default=0.0,
                   help="Exclude signals with ATR%% below this value (default: 0 = all). "
                        "Sweet spot ≥1.0 filters low-volatility noise.")
    p.add_argument("--max-atr-pct", type=float, default=99.0,
                   help="Exclude signals with ATR%% above this value (default: 99 = all). "
                        "Use ≤4.0 to avoid extreme-volatility signals.")
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

    # ATR volatility filter (post-collection, no re-run needed)
    if args.min_atr_pct > 0 or args.max_atr_pct < 99:
        before = len(df_out)
        df_out = df_out[
            (df_out["atr_pct"] >= args.min_atr_pct) &
            (df_out["atr_pct"] <= args.max_atr_pct)
        ].copy()
        print(f"ATR filter [{args.min_atr_pct}%-{args.max_atr_pct}%]: "
              f"{before} -> {len(df_out)} signals ({before - len(df_out)} removed)")

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
            win_rate = (g_df["outcome"] == "WIN").mean()
            avg_rr = g_df["rr_ratio"].mean()
            # Expectancy in R: win% * avg_rr - loss% * 1.0
            expectancy = win_rate * avg_rr - (1 - win_rate) * 1.0
            # Profit factor: sum of winning R / sum of losing R
            wins_r = g_df.loc[g_df["outcome"] == "WIN", "rr_ratio"].sum()
            losses_r = float(len(g_df[g_df["outcome"] == "LOSS"]))
            pf = wins_r / losses_r if losses_r > 0 else float("inf")
            # SQN = E(R) / stdev(R) * sqrt(n)  — Van Tharp, >1.6 tradeable
            r_series = g_df["realized_r"].dropna()
            r_std = r_series.std()
            sqn = (r_series.mean() / r_std * math.sqrt(len(r_series))
                   if r_std > 0 else 0.0)
            # MAE/MFE averages
            avg_mae = g_df["mae_r"].mean() if "mae_r" in g_df else float("nan")
            avg_mfe = g_df["mfe_r"].mean() if "mfe_r" in g_df else float("nan")
            # Sharpe / Sortino / Calmar via quantstats (daily R-series)
            # Sharpe / Sortino via quantstats (daily R-series; Calmar skipped — not valid for R-multiples)
            sharpe = sortino = float("nan")
            try:
                import quantstats as qs
                daily_r = (
                    g_df.set_index("timestamp")["realized_r"]
                    .dropna()
                    .resample("1D")
                    .sum()
                )
                if len(daily_r) >= 30:
                    sharpe  = round(qs.stats.sharpe(daily_r, annualize=True), 2)
                    sortino = round(qs.stats.sortino(daily_r, annualize=True), 2)
            except Exception:
                pass
            # Max drawdown on equity curve (in R units)
            r_eq = g_df.sort_values("timestamp")["realized_r"].dropna().cumsum()
            max_dd = round((r_eq - r_eq.cummax()).min(), 1)
            rows.append({
                "Grade": g,
                "Signals": len(subset[subset["grade"] == g]),
                "Closed": len(g_df),
                "Win %": f"{100 * win_rate:.1f}%",
                "Avg RR": f"{avg_rr:.2f}",
                "Expectancy R": f"{expectancy:+.3f}",
                "Prof.Factor": f"{pf:.2f}",
                "SQN": f"{sqn:.2f}",
                "Sharpe": f"{sharpe:.2f}",
                "Sortino": f"{sortino:.2f}",
                "Max DD R": f"{max_dd:.1f}",
                "Avg MAE": f"{avg_mae:.2f}",
                "Avg MFE": f"{avg_mfe:.2f}",
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
