"""
python -m backtest.cash_sim
===========================
Paper cash replay of frozen 4h A/A+ (not an order, not a W_* retune).

Default book: latest.parquet, 4h A/A+, OOS >= 2025-01-01, ADX>=20,
ATR% 0.4-4.0.

``stake`` is isolated margin. ``leverage`` sizes notional (25x → $100
margin is $2500 notional). Isolated loss is capped at the $100 margin.
``max_slots=3`` + ``rank_by_score``: at each bar, fill free slots with
the highest-score A/A+; no 4th until one of the 3 closes.

QMIE still does not place orders. This is a paper what-if.
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


def _isolated_pnl(stake: float, leverage: float, realized_r: float, risk_pct: float) -> tuple[float, bool]:
    """Return (pnl, liquidated). Isolated margin cannot lose more than stake."""
    notional = stake * leverage
    raw = notional * float(realized_r) * float(risk_pct)
    if raw < -stake:
        return -stake, True
    return raw, False


def simulate(
    trades: pd.DataFrame,
    *,
    start_cash: float = 1000.0,
    stake: float = 100.0,
    one_per_symbol: bool = False,
    max_slots: Optional[int] = None,
    leverage: float = 1.0,
    rank_by_score: bool = False,
) -> dict[str, Any]:
    """Open if cash >= stake and a slot is free. Close frees margin.

    At a timestamp, closes run first. Remaining slots fill from that bar's
    alerts (highest score first when rank_by_score). Alerts that fire while
    full are skipped — no queue. Isolated: loss capped at stake.
    Not an order.
    """
    empty = {
        "start": start_cash,
        "final": start_cash,
        "pnl": 0.0,
        "taken": 0,
        "skipped": 0,
        "wins": 0,
        "liquidations": 0,
        "max_dd": 0.0,
        "peak": start_cash,
        "max_open": 0,
        "curve": [],
        "taken_rows": trades.iloc[0:0].copy() if trades is not None else pd.DataFrame(),
        "open_left": 0,
        "leverage": leverage,
        "notional": stake * leverage,
    }
    if trades is None or trades.empty:
        return empty

    t = trades.reset_index(drop=True)
    pnls: list[float] = []
    liq_flags: list[bool] = []
    for _, r in t.iterrows():
        pnl, liq = _isolated_pnl(stake, leverage, float(r["realized_r"]), float(r["risk_pct"]))
        pnls.append(pnl)
        liq_flags.append(liq)
    t["pnl_usd"] = pnls
    t["liquidated"] = liq_flags

    opens_at: dict[pd.Timestamp, list[int]] = {}
    closes_at: dict[pd.Timestamp, list[int]] = {}
    for i, r in t.iterrows():
        opens_at.setdefault(r["timestamp"], []).append(int(i))
        closes_at.setdefault(r["exit_ts"], []).append(int(i))
    all_ts = sorted(set(opens_at) | set(closes_at))

    cash = float(start_cash)
    open_ids: dict[int, str] = {}
    taken_idx: list[int] = []
    skipped = 0
    liquidations = 0
    peak = cash
    max_dd = 0.0
    max_open = 0
    curve: list[dict[str, Any]] = []

    def equity() -> float:
        return cash + stake * len(open_ids)

    def snap(ts: pd.Timestamp) -> None:
        nonlocal peak, max_dd
        eq = equity()
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
        curve.append({"timestamp": ts, "equity": eq, "cash": cash, "open": len(open_ids)})

    def try_open(i: int) -> bool:
        nonlocal skipped, max_open, cash
        if cash + 1e-9 < stake:
            skipped += 1
            return False
        if max_slots is not None and len(open_ids) >= max_slots:
            skipped += 1
            return False
        if one_per_symbol:
            sym = str(t.at[i, "symbol"])
            if any(s == sym for s in open_ids.values()):
                skipped += 1
                return False
        cash -= stake
        open_ids[i] = str(t.at[i, "symbol"])
        taken_idx.append(i)
        max_open = max(max_open, len(open_ids))
        return True

    def rank_key(i: int) -> tuple[int, float]:
        g = str(t.at[i, "grade"] or "")
        grade_rank = 2 if g == "A+" else 1 if g == "A" else 0
        try:
            sc = float(t.at[i, "score"] or 0.0)
        except (TypeError, ValueError):
            sc = 0.0
        return (grade_rank, sc)

    for ts in all_ts:
        for i in closes_at.get(ts, []):
            if i not in open_ids:
                continue
            cash += stake + float(t.at[i, "pnl_usd"])
            if bool(t.at[i, "liquidated"]):
                liquidations += 1
            del open_ids[i]
        candidates = list(opens_at.get(ts, []))
        if rank_by_score:
            candidates.sort(key=rank_key, reverse=True)
        for i in candidates:
            try_open(i)
        snap(ts)

    taken = t.loc[taken_idx].copy() if taken_idx else t.iloc[0:0].copy()
    wins = int((taken["outcome"] == "WIN").sum()) if len(taken) else 0
    final = equity()
    return {
        "start": start_cash,
        "final": final,
        "pnl": final - start_cash,
        "taken": len(taken_idx),
        "skipped": skipped,
        "wins": wins,
        "liquidations": liquidations,
        "max_dd": max_dd,
        "peak": peak,
        "max_open": max_open,
        "curve": curve,
        "taken_rows": taken,
        "open_left": len(open_ids),
        "leverage": leverage,
        "notional": stake * leverage,
    }


def _fmt(sim: dict[str, Any]) -> str:
    win_pct = (100.0 * sim["wins"] / sim["taken"]) if sim["taken"] else 0.0
    liq = sim.get("liquidations", 0)
    return (
        f"  taken={sim['taken']:4d}  skip={sim['skipped']:4d}  "
        f"win={win_pct:5.1f}%  liq={liq:3d}  final=${sim['final']:.2f}  "
        f"PnL=${sim['pnl']:+.2f}  peak=${sim['peak']:.2f}  "
        f"maxDD=${sim['max_dd']:.2f}  max_open={sim['max_open']}"
    )


def _monthly(taken: pd.DataFrame, stake: float, *, leverage: float = 1.0) -> pd.DataFrame:
    if taken.empty:
        return pd.DataFrame(columns=["month", "n", "pnl"])
    d = taken.copy()
    d["month"] = d["exit_ts"].dt.tz_convert("UTC").dt.strftime("%Y-%m")
    if "pnl_usd" not in d.columns:
        d["pnl_usd"] = [
            _isolated_pnl(stake, leverage, float(r["realized_r"]), float(r["risk_pct"]))[0]
            for _, r in d.iterrows()
        ]
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
    p.add_argument("--leverage", type=float, default=1.0, help="Isolated notional = stake * leverage")
    p.add_argument("--max-slots", type=int, default=0, help="Max concurrent (0 = cash/stake)")
    p.add_argument("--rank-score", action="store_true", help="Fill free slots with highest score at that bar")
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
    slots = args.max_slots if args.max_slots > 0 else int(args.cash // args.stake)
    notional = args.stake * args.leverage
    print(
        f"Paper cash sim  {args.tf} A/A+  {args.start} -> {book['timestamp'].max()}\n"
        f"Book n={stats['n']} win={stats['win_pct']}% E[R]={stats['expectancy_r']} PF={stats['pf']}\n"
        f"Start ${args.cash:.0f}  margin ${args.stake:.0f}  {args.leverage:.0f}x  "
        f"notional ${notional:.0f}/fill  max_open={slots}  "
        f"rank_score={args.rank_score}\n"
        "Isolated: a fill cannot lose more than its $ margin. Not an order.\n"
    )

    kw = dict(
        start_cash=args.cash,
        stake=args.stake,
        max_slots=slots,
        leverage=args.leverage,
        rank_by_score=args.rank_score,
    )
    fifo = simulate(book, one_per_symbol=False, **kw)
    one = simulate(book, one_per_symbol=True, **kw)
    daily = first_per_symbol_day(book)
    day_one = simulate(daily, one_per_symbol=True, **kw)

    print("FIFO (time order, skip when 3 slots full):")
    print(_fmt(fifo))
    print("One open per symbol + fill best score into free slots:")
    print(_fmt(one))
    print("First / symbol / UTC day, then one-per-symbol:")
    print(_fmt(day_one))

    print(f"\nMonthly PnL — max {slots} open, one per symbol, {args.leverage:.0f}x isolated")
    months = _monthly(one["taken_rows"], args.stake, leverage=args.leverage)
    print(f"  {'month':<10} {'n':>4} {'pnl':>10}")
    for _, r in months.iterrows():
        print(f"  {r['month']:<10} {int(r['n']):4d} ${r['pnl']:+8.2f}")

    mean_risk = float(book["risk_pct"].mean()) if len(book) else 0.0
    raw_1r = notional * mean_risk
    print(
        f"\nMean SL {100 * mean_risk:.2f}% of entry. "
        f"{args.leverage:.0f}x on ${args.stake:.0f} margin → 1R ≈ ${raw_1r:.2f} "
        f"(isolated cap ${args.stake:.0f}).\n"
        "places_orders=false  QMIE does not send this leverage to a venue."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
