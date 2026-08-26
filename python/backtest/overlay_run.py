"""
python -m backtest.overlay_run
==============================
Small closed-bar check of KovaView overlays on frozen 4h A/A+ outcomes.
Does not retune W_*. Does not write .env.
"""
from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path

import pandas as pd

from backtest.data_loader import load_klines, resample_ohlcv
from backtest.overlay import annotate_closed, radar_state_table, summarize
from backtest.runner import run_backtest, results_to_dataframe

_HTF_MAP = {"1h": "4h", "4h": "1D", "1d": "1W"}


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Validate KovaView overlays on a few 4h A/A+ trades")
    p.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    p.add_argument("--tf", default="4h")
    p.add_argument("--start", default="2024-04-01")
    p.add_argument("--end", default="2026-07-31")
    p.add_argument("--split", default="2025-01-01")
    p.add_argument("--min-adx", type=float, default=20.0)
    p.add_argument("--min-atr-pct", type=float, default=0.4)
    p.add_argument("--max-atr-pct", type=float, default=4.0)
    p.add_argument("--sample", type=int, default=15, help="How many kept+skipped rows to print")
    p.add_argument("--out", default=str(Path(__file__).parent / "results"))
    return p.parse_args(argv)


def _gate(df: pd.DataFrame, args) -> pd.DataFrame:
    g = df[
        (df["grade"].isin(["A", "A+"]))
        & (df["timeframe"].str.lower() == str(args.tf).lower())
        & (df["atr_pct"] >= args.min_atr_pct)
        & (df["atr_pct"] <= args.max_atr_pct)
        & (df["adx_value"] >= args.min_adx)
        & (df["outcome"].isin(["WIN", "LOSS"]))
    ].copy()
    if args.split:
        split = pd.Timestamp(args.split, tz="UTC")
        ts = pd.to_datetime(g["timestamp"], utc=True)
        g = g[ts >= split].copy()
    return g.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def main(argv=None) -> int:
    args = _parse_args(argv)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    symbols = [s.upper() for s in args.symbols]
    if "BTCUSDT" not in symbols:
        load_syms = symbols + ["BTCUSDT"]
    else:
        load_syms = list(symbols)

    print(
        f"Overlay check {symbols} {args.tf} {start}→{end} "
        f"OOS≥{args.split} A/A+ ADX≥{args.min_adx} ATR {args.min_atr_pct}-{args.max_atr_pct}\n"
        "Post-filter only. Not an order. Not a W_* retune.\n"
    )

    all_results = []
    daily: dict[str, pd.DataFrame] = {}
    for symbol in load_syms:
        print(f"  {symbol} {args.tf} ...", end=" ", flush=True)
        df = load_klines(symbol, args.tf, start, end)
        if len(df) < 350:
            print(f"skipped ({len(df)} bars)")
            continue
        daily[symbol] = resample_ohlcv(df, "1D")
        if symbol in symbols:
            results = run_backtest(symbol, args.tf, df, htf_rule=_HTF_MAP.get(args.tf, "1D"))
            all_results.extend(results)
            print(f"{len(results)} raw signals")
        else:
            print(f"radar only ({len(daily[symbol])} daily)")

    if not all_results:
        print("No signals.")
        return 1

    raw = results_to_dataframe(all_results)
    gated = _gate(raw, args)
    print(f"\nClosed 4h A/A+ after frozen protocol: {len(gated)}")
    if gated.empty:
        return 1

    tables = {sym: radar_state_table(d, sym) for sym, d in daily.items()}
    records = gated.to_dict(orient="records")
    annotated = annotate_closed(records, tables)

    raw_s = summarize(annotated, kept_only=False)
    kept_s = summarize(annotated, kept_only=True)
    skipped = [r for r in annotated if r.get("overlay_skip")]
    reason_counts: dict[str, int] = {}
    for r in skipped:
        for bit in str(r.get("overlay_reasons") or "").split(","):
            if bit:
                reason_counts[bit] = reason_counts.get(bit, 0) + 1

    print("\nBook (closed A/A+ 4h, frozen ATR/ADX gates, then overlays)")
    print(f"  raw      n={raw_s['n']:4d}  win={raw_s['win_pct']}%  E[R]={raw_s['expectancy_r']}  PF={raw_s['pf']}")
    print(f"  overlays n={kept_s['n']:4d}  win={kept_s['win_pct']}%  E[R]={kept_s['expectancy_r']}  PF={kept_s['pf']}")
    print(f"  skipped {len(skipped)}  reasons {reason_counts or '{}'}")

    adf = pd.DataFrame(annotated)
    adf["timestamp"] = pd.to_datetime(adf["timestamp"], utc=True)
    adf["day"] = adf["timestamp"].dt.floor("D")
    first = adf.sort_values("timestamp").drop_duplicates(["symbol", "day"], keep="first")
    first_recs = first.to_dict(orient="records")
    d_raw = summarize(first_recs, kept_only=False)
    d_ovl = summarize(first_recs, kept_only=True)
    d_skip = [r for r in first_recs if r.get("overlay_skip")]
    d_reasons: dict[str, int] = {}
    for r in d_skip:
        for bit in str(r.get("overlay_reasons") or "").split(","):
            if bit:
                d_reasons[bit] = d_reasons.get(bit, 0) + 1
    print("\nOne A/A+ per symbol per UTC day (swing-style, fewer clustered 4h alerts)")
    print(f"  raw      n={d_raw['n']:4d}  win={d_raw['win_pct']}%  E[R]={d_raw['expectancy_r']}  PF={d_raw['pf']}")
    print(f"  overlays n={d_ovl['n']:4d}  win={d_ovl['win_pct']}%  E[R]={d_ovl['expectancy_r']}  PF={d_ovl['pf']}")
    print(f"  skipped {len(d_skip)}  reasons {d_reasons or '{}'}")

    # Sample: first skips + first kept, time-ordered mix
    print(f"\nSample trades (up to {args.sample}, time order)")
    print(
        f"{'when':<20} {'sym':<10} {'side':<5} {'g':<3} {'out':<5} "
        f"{'R':>6} {'skip':<18} {'desk':<6}"
    )
    for r in annotated[: args.sample]:
        ts = str(r.get("timestamp"))[:19]
        rr = r.get("realized_r")
        rr_s = f"{float(rr):+.2f}" if rr is not None and not (isinstance(rr, float) and math.isnan(rr)) else "—"
        skip = str(r.get("overlay_reasons") or "keep")
        print(
            f"{ts:<20} {str(r.get('symbol')):<10} {str(r.get('side')):<5} "
            f"{str(r.get('grade')):<3} {str(r.get('outcome')):<5} {rr_s:>6} "
            f"{skip:<18} {str(r.get('desk_verdict')):<6}"
        )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(annotated).to_parquet(out_dir / "overlay_annotated.parquet", index=False)
    print(f"\nWrote {out_dir / 'overlay_annotated.parquet'}  places_orders=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
