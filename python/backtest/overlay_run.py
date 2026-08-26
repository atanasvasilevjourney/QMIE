"""
python -m backtest.overlay_run
==============================
Closed-bar A/A+ check on 4h or 1d. Production overlay skip list is empty.
Does not retune W_*. Does not write .env. Not an order.
"""
from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path

import pandas as pd

from backtest.data_loader import load_tf_ohlcv, resample_ohlcv
from backtest.overlay import annotate_closed, radar_state_table, summarize
from backtest.runner import run_backtest, results_to_dataframe

_HTF_MAP = {"1h": "4h", "4h": "1D", "1d": "1W"}
_MIN_BARS = 350


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Closed-bar A/A+ overlay check (skip list empty). Use --tf 1d or 4h.",
    )
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


def _norm_tf(tf: str) -> str:
    t = str(tf).strip().lower()
    if t in ("1d", "d", "daily"):
        return "1d"
    return t


def _gate(df: pd.DataFrame, args) -> pd.DataFrame:
    tf = _norm_tf(args.tf)
    g = df[
        (df["grade"].isin(["A", "A+"]))
        & (df["timeframe"].str.lower() == tf)
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


def _aa_closed(df: pd.DataFrame, tf: str, split: str | None) -> pd.DataFrame:
    g = df[
        (df["grade"].isin(["A", "A+"]))
        & (df["timeframe"].str.lower() == tf)
        & (df["outcome"].isin(["WIN", "LOSS"]))
    ].copy()
    if split:
        split_ts = pd.Timestamp(split, tz="UTC")
        ts = pd.to_datetime(g["timestamp"], utc=True)
        g = g[ts >= split_ts].copy()
    return g


def _print_grade_table(label: str, subset: pd.DataFrame) -> None:
    closed = subset[subset["outcome"].isin(["WIN", "LOSS"])]
    print(f"\n{label}")
    if closed.empty:
        print("  (no closed trades)")
        return
    print(f"  {'Grade':<6} {'N':>5} {'Win':>7} {'E[R]':>7} {'PF':>6} {'bars':>6} {'max':>5}")
    for g in ("A+", "A", "B", "C"):
        part = closed[closed["grade"] == g]
        if part.empty:
            continue
        recs = part.to_dict(orient="records")
        s = summarize(recs, kept_only=False)
        bars = part["bars_to_outcome"].mean() if "bars_to_outcome" in part else float("nan")
        mx = part["score"].max() if "score" in part else float("nan")
        print(
            f"  {g:<6} {s['n']:5d} {s['win_pct']:6.1f}% "
            f"{s['expectancy_r']:7.3f} {s['pf'] if s['pf'] is not None else float('nan'):6.2f} "
            f"{bars:6.1f} {mx:5.0f}"
        )
    aa = closed[closed["grade"].isin(["A", "A+"])]
    if not aa.empty:
        s = summarize(aa.to_dict(orient="records"), kept_only=False)
        bars = aa["bars_to_outcome"].mean() if "bars_to_outcome" in aa else float("nan")
        mx = aa["score"].max() if "score" in aa else float("nan")
        print(
            f"  {'A/A+':<6} {s['n']:5d} {s['win_pct']:6.1f}% "
            f"{s['expectancy_r']:7.3f} {s['pf'] if s['pf'] is not None else float('nan'):6.2f} "
            f"{bars:6.1f} {mx:5.0f}"
        )
    if "score" in closed:
        print(f"  all-grade max score {closed['score'].max():.0f}")


def main(argv=None) -> int:
    args = _parse_args(argv)
    args.tf = _norm_tf(args.tf)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    symbols = [s.upper() for s in args.symbols]
    if "BTCUSDT" not in symbols:
        load_syms = symbols + ["BTCUSDT"]
    else:
        load_syms = list(symbols)
    htf = _HTF_MAP.get(args.tf, "1D")

    print(
        f"Overlay check {symbols} {args.tf} (HTF {htf}) {start}->{end} "
        f"OOS>={args.split} A/A+ ADX>={args.min_adx} ATR {args.min_atr_pct}-{args.max_atr_pct}\n"
        "Overlay skip list is empty. Not an order. Not a W_* retune.\n"
        "1d lookahead is 100 daily bars (~100d); 4h lookahead is 100*4h (~17d).\n"
    )

    all_results = []
    daily: dict[str, pd.DataFrame] = {}
    for symbol in load_syms:
        print(f"  {symbol} {args.tf} ...", end=" ", flush=True)
        df, source = load_tf_ohlcv(symbol, args.tf, start, end)
        if len(df) < _MIN_BARS:
            print(f"skipped ({len(df)} bars, {source})")
            continue
        if args.tf == "1d":
            daily[symbol] = df
        else:
            daily[symbol] = resample_ohlcv(df, "1D")
        if symbol in symbols:
            results = run_backtest(symbol, args.tf, df, htf_rule=htf)
            all_results.extend(results)
            weekly = resample_ohlcv(df, "1W") if args.tf == "1d" else None
            extra = ""
            if weekly is not None:
                extra = f", weekly={len(weekly)} (HTF needs 220)"
            print(f"{len(results)} raw signals ({source}, {len(df)} bars{extra})")
        else:
            print(f"radar only ({source}, {len(daily[symbol])} daily)")

    if not all_results:
        print("No signals.")
        return 1

    raw = results_to_dataframe(all_results)
    if args.split:
        split_ts = pd.Timestamp(args.split, tz="UTC")
        ts_all = pd.to_datetime(raw["timestamp"], utc=True)
        is_df = raw[ts_all < split_ts].copy()
        oos = raw[ts_all >= split_ts].copy()
    else:
        is_df = raw.iloc[0:0].copy()
        oos = raw
    if not is_df.empty:
        _print_grade_table(f"All grades IS <{args.split} (ungated ATR/ADX)", is_df)
    _print_grade_table(f"All grades OOS >={args.split} (ungated ATR/ADX)", oos)

    aa_ungated = _aa_closed(raw, args.tf, args.split)
    if not aa_ungated.empty:
        atr = aa_ungated["atr_pct"]
        print(
            f"\nA/A+ OOS ATR%  n={len(aa_ungated)}  "
            f"p10={atr.quantile(0.10):.2f}  p50={atr.median():.2f}  "
            f"p90={atr.quantile(0.90):.2f}  max={atr.max():.2f}"
        )
        u = summarize(aa_ungated.to_dict(orient="records"), kept_only=False)
        print(f"  ungated A/A+  n={u['n']}  win={u['win_pct']}%  E[R]={u['expectancy_r']}  PF={u['pf']}")

    gated = _gate(raw, args)
    print(
        f"\nClosed {args.tf} A/A+ after frozen ATR/ADX protocol: {len(gated)}"
    )
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw.to_parquet(out_dir / f"overlay_raw_{args.tf}.parquet", index=False)
    if gated.empty:
        print(
            "No gated A/A+ rows. On 1d, W_HTF needs 220 weekly bars "
            "(~4.2y) or A+ is unreachable and A needs a perfect 80. "
            "Not an order. Not a W_* retune."
        )
        return 0

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

    print(f"\nBook (closed A/A+ {args.tf}, frozen ATR/ADX gates, then overlays)")
    print(f"  raw      n={raw_s['n']:4d}  win={raw_s['win_pct']}%  E[R]={raw_s['expectancy_r']}  PF={raw_s['pf']}")
    print(f"  overlays n={kept_s['n']:4d}  win={kept_s['win_pct']}%  E[R]={kept_s['expectancy_r']}  PF={kept_s['pf']}")
    print(f"  skipped {len(skipped)}  reasons {reason_counts or '{}'}")

    if args.tf != "1d":
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
    else:
        print("\nOne-per-UTC-day de-dupe skipped (base TF is already 1d).")

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
    out_path = out_dir / f"overlay_annotated_{args.tf}.parquet"
    pd.DataFrame(annotated).to_parquet(out_path, index=False)
    print(f"\nWrote {out_path}  places_orders=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
