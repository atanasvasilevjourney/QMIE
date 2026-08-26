"""
python -m backtest.cash_sim
===========================
Paper cash replay of frozen 4h A/A+ (not an order, not a W_* retune).

Default book: latest.parquet, 4h A/A+, OOS >= 2025-01-01, ADX>=20,
ATR% 0.4-4.0. Stake is notional (1x). $100 risk sizing is a different
question — 1.5*ATR on a 2.5% ATR name is ~3.7% of notional, so $100
risk would need ~$2.7k notional per trade, which this $1000 book cannot
support without leverage QMIE does not size.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from backtest.overlay import summarize

_BAR_HOURS = {"1h": 1, "4h": 4, "1d": 24}


def load_book(
    path: Path,
    *,
    tf: str = "4h",
    start: str = "2025-01-01",
    end: Optional[str] = None,
    min_adx: float = 20.0,
    min_atr_pct: float = 0.4,
    max_atr_pct: float = 4.0,
) -> pd.DataFrame:
    df = pd.read_parquet(path)
    g = df[
        (df["grade"].isin(["A", "A+"]))
        & (df["timeframe"].str.lower() == tf.lower())
        & (df["outcome"].isin(["WIN", "LOSS"]))
        & (df["adx_value"] >= min_adx)
        & (df["atr_pct"] >= min_atr_pct)
        & (df["atr_pct"] <= max_atr_pct)
    ].copy()
    g["timestamp"] = pd.to_datetime(g["timestamp"], utc=True)
    g = g[g["timestamp"] >= pd.Timestamp(start, tz="UTC")]
    if end:
        g = g[g["timestamp"] <= pd.Timestamp(end, tz="UTC")]
    hours = _BAR_HOURS.get(tf.lower(), 4)
    g["exit_ts"] = g["timestamp"] + pd.to_timedelta(
        g["bars_to_outcome"].astype(int) * hours, unit="h"
    )
    risk_pct = (g["entry"] - g["stop_loss"]).abs() / g["entry"]
    g["risk_pct"] = risk_pct
    return g.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def first_per_symbol_day(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["day"] = d["timestamp"].dt.floor("D")
    return (
        d.sort_values("timestamp")
        .drop_duplicates(["symbol", "day"], keep="first")
        .drop(columns=["day"])
        .reset_index(drop=True)
    )


def simulate(
    trades: pd.DataFrame,
    *,
    start_cash: float = 1000.0,
    stake: float = 100.0,
    one_per_symbol: bool = False,
    max_slots: Optional[int] = None,
) -> dict[str, Any]:
    """FIFO: open if cash >= stake (and optional one-per-symbol). Close frees cash.

    PnL on a WIN/LOSS is stake * realized_r * (SL distance / entry).
    No leverage. No MTM. Not an order.
    """
    if trades.empty:
        return {
            "start": start_cash,
            "final": start_cash,
            "pnl": 0.0,
            "taken": 0,
            "skipped": 0,
            "wins": 0,
            "max_dd": 0.0,
            "peak": start_cash,
            "max_open": 0,
            "curve": [],
            "taken_rows": trades.iloc[0:0].copy(),
        }

    t = trades.reset_index(drop=True)
    t["pnl_usd"] = stake * t["realized_r"].astype(float) * t["risk_pct"].astype(float)
    events: list[tuple[pd.Timestamp, int, int, str]] = []
    for i, r in t.iterrows():
        events.append((r["timestamp"], 1, int(i), "open"))
        events.append((r["exit_ts"], 0, int(i), "close"))
    events.sort(key=lambda x: (x[0], x[1], x[2]))

    cash = float(start_cash)
    open_ids: dict[int, str] = {}
    taken_idx: list[int] = []
    skipped = 0
    peak = cash
    max_dd = 0.0
    max_open = 0
    curve: list[dict[str, Any]] = []

    def equity() -> float:
        return cash + stake * len(open_ids)

    for ts, _ord, i, kind in events:
        if kind == "close":
            if i not in open_ids:
                continue
            cash += stake + float(t.at[i, "pnl_usd"])
            del open_ids[i]
        else:
            if cash + 1e-9 < stake:
                skipped += 1
                continue
            if max_slots is not None and len(open_ids) >= max_slots:
                skipped += 1
                continue
            if one_per_symbol:
                sym = str(t.at[i, "symbol"])
                if any(s == sym for s in open_ids.values()):
                    skipped += 1
                    continue
            cash -= stake
            open_ids[i] = str(t.at[i, "symbol"])
            taken_idx.append(i)
            max_open = max(max_open, len(open_ids))
        eq = equity()
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
        curve.append({"timestamp": ts, "equity": eq, "cash": cash, "open": len(open_ids)})

    taken = t.loc[taken_idx].copy() if taken_idx else t.iloc[0:0].copy()
    wins = int((taken["outcome"] == "WIN").sum()) if len(taken) else 0
    return {
        "start": start_cash,
        "final": equity() if not open_ids else cash + stake * len(open_ids),
        "pnl": (cash + stake * len(open_ids)) - start_cash,
        "taken": len(taken_idx),
        "skipped": skipped,
        "wins": wins,
        "max_dd": max_dd,
        "peak": peak,
        "max_open": max_open,
        "curve": curve,
        "taken_rows": taken,
        "open_left": len(open_ids),
    }


def _fmt(sim: dict[str, Any]) -> str:
    win_pct = (100.0 * sim["wins"] / sim["taken"]) if sim["taken"] else 0.0
    return (
        f"  taken={sim['taken']:4d}  skip={sim['skipped']:4d}  "
        f"win={win_pct:5.1f}%  final=${sim['final']:.2f}  "
        f"PnL=${sim['pnl']:+.2f}  peak=${sim['peak']:.2f}  "
        f"maxDD=${sim['max_dd']:.2f}  max_open={sim['max_open']}"
    )


def _monthly(taken: pd.DataFrame, stake: float) -> pd.DataFrame:
    if taken.empty:
        return pd.DataFrame(columns=["month", "n", "pnl"])
    d = taken.copy()
    d["month"] = d["exit_ts"].dt.tz_convert("UTC").dt.strftime("%Y-%m")
    d["pnl_usd"] = stake * d["realized_r"].astype(float) * d["risk_pct"].astype(float)
    g = d.groupby("month").agg(n=("pnl_usd", "size"), pnl=("pnl_usd", "sum"))
    return g.reset_index()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Paper $ cash replay of 4h A/A+ (not an order)")
    p.add_argument("--parquet", default=str(Path(__file__).parent / "results" / "latest.parquet"))
    p.add_argument("--tf", default="4h")
    p.add_argument("--start", default="2025-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--stake", type=float, default=100.0)
    p.add_argument("--min-adx", type=float, default=20.0)
    p.add_argument("--min-atr-pct", type=float, default=0.4)
    p.add_argument("--max-atr-pct", type=float, default=4.0)
    args = p.parse_args(argv)

    path = Path(args.parquet)
    if not path.exists():
        print(f"Missing {path}. Run python -m backtest.run first.")
        return 1

    book = load_book(
        path,
        tf=args.tf,
        start=args.start,
        end=args.end,
        min_adx=args.min_adx,
        min_atr_pct=args.min_atr_pct,
        max_atr_pct=args.max_atr_pct,
    )
    stats = summarize(book.to_dict(orient="records"), kept_only=False)
    print(
        f"Paper cash sim  {args.tf} A/A+  {args.start} -> {book['timestamp'].max()}\n"
        f"Book n={stats['n']} win={stats['win_pct']}% E[R]={stats['expectancy_r']} PF={stats['pf']}\n"
        f"Start ${args.cash:.0f}  stake ${args.stake:.0f} notional 1x  "
        f"hard cap {int(args.cash // args.stake)} concurrent (cash/stake)\n"
        "Not an order. Overlay skip list empty. Do not retune W_*.\n"
    )

    unlimited_pnl = float((args.stake * book["realized_r"] * book["risk_pct"]).sum())
    print(
        f"Unlimited slots (not this $1000 book): "
        f"n={len(book)}  PnL=${unlimited_pnl:+.2f}  "
        f"final=${args.cash + unlimited_pnl:.2f}"
    )

    slots = int(args.cash // args.stake)
    fifo = simulate(book, start_cash=args.cash, stake=args.stake, one_per_symbol=False, max_slots=slots)
    one = simulate(book, start_cash=args.cash, stake=args.stake, one_per_symbol=True, max_slots=slots)
    daily = first_per_symbol_day(book)
    day_fifo = simulate(daily, start_cash=args.cash, stake=args.stake, one_per_symbol=False, max_slots=slots)
    day_one = simulate(daily, start_cash=args.cash, stake=args.stake, one_per_symbol=True, max_slots=slots)

    print("\nWith $ cash constraint (skip when $100 is already in open trades)")
    print("FIFO take every 4h A/A+ that fits:")
    print(_fmt(fifo))
    print("One open per symbol (cluster_max=1 analog):")
    print(_fmt(one))
    print(f"First alert / symbol / UTC day (n={len(daily)}), then FIFO:")
    print(_fmt(day_fifo))
    print("First / symbol / day + one open per symbol:")
    print(_fmt(day_one))

    print("\nMonthly PnL — one open per symbol (the book that fits $1000)")
    months = _monthly(one["taken_rows"], args.stake)
    print(f"  {'month':<10} {'n':>4} {'pnl':>10}")
    for _, r in months.iterrows():
        print(f"  {r['month']:<10} {int(r['n']):4d} ${r['pnl']:+8.2f}")

    mean_risk = float(book["risk_pct"].mean()) if len(book) else 0.0
    print(
        f"\nMean SL distance {100 * mean_risk:.2f}% of entry. "
        f"$100 notional risks ~${args.stake * mean_risk:.2f} per trade, "
        f"not $100. A $100 *stop* would need ~${args.stake / mean_risk if mean_risk else float('nan'):.0f} "
        f"notional (leverage QMIE does not size).\n"
        "places_orders=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
