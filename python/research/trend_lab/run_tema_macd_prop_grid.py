"""CLI for notebook 15 — TEMA+MACD Calmar grid on QQQ/GLD/BTC."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from research.trend_lab.protocol import SPLIT
from research.trend_lab.tema_macd_prop import (
    ANN_PROP,
    brute_force_calmar_is,
    eval_tema_macd_prop,
    ftmo_proxy,
    load_trio_daily_ohlcv,
)

is_end = pd.Timestamp(SPLIT.is_end, tz="UTC")
cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", default=True)
    ap.add_argument("--full", action="store_true", help="Larger grid (overrides --quick)")
    ap.add_argument("--max-dd-floor", type=float, default=-0.10)
    ap.add_argument("--out", default="/opt/cursor/artifacts/tema_macd_prop_grid.json")
    args = ap.parse_args()
    quick = not args.full

    ohlcv, sources = load_trio_daily_ohlcv()
    best_params = {}
    grid_top = {}
    results = []
    for sym, df in ohlcv.items():
        table, best = brute_force_calmar_is(
            df, is_end=is_end, quick=quick, max_dd_floor=args.max_dd_floor,
        )
        grid_top[sym] = table.head(10).to_dict(orient="records") if not table.empty else []
        best_params[sym] = best
        if best is None:
            print(sym, "no IS combo passed filters")
            continue
        ev = eval_tema_macd_prop(df, best, is_end=is_end, ann=ANN_PROP)
        for slice_name, k in [("IS", ev["is"]), ("OOS", ev["oos"])]:
            sl = ev["net"].loc[:is_end] if slice_name == "IS" else ev["net"].loc[cut:]
            results.append({
                "symbol": sym,
                "slice": slice_name,
                **k,
                **ftmo_proxy(sl),
                "n_trades": ev["n_trades_full"],
            })
        print(f"\n{sym} best IS calmar={table.iloc[0]['calmar']:.3f} OOS max_dd={ev['oos']['max_dd']:.3%}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "protocol": {"is_end": str(is_end.date()), "oos_start": str(cut.date())},
        "sources": sources,
        "best_params": {k: asdict(v) for k, v in best_params.items() if v is not None},
        "results": results,
        "grid_top10": grid_top,
    }, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
