"""S&P 500 momentum rotation vs +SMA200; prop rinse cadence (research only)."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from research.trend_lab.data import load_etf
from research.trend_lab.equity_universe import load_equity_panel, sp500_tickers
from research.trend_lab.metrics import kpis_from_net, max_dd
from research.trend_lab.momentum_rotation import compare_rotations
from research.trend_lab.prop_eval_mc import EvalEconomics, EvalRules, McParams, run_mc_grid, simulate_one_attempt
from research.trend_lab.protocol import SPLIT

cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
is_end = cut - pd.Timedelta(days=1)


def overlapping_eval_starts(net: pd.Series, *, every_days: int = 14, rules: EvalRules | None = None) -> dict:
    """Pass rate when a new eval starts every ``every_days`` (overlapping attempts)."""
    rules = rules or EvalRules()
    net = net.fillna(0.0)
    oos = net.loc[cut:]
    if oos.empty:
        return {"n_starts": 0, "pass_rate": 0.0}
    starts = oos.index[::every_days]
    passes = 0
    days_list = []
    for ts in starts:
        path = oos.loc[ts:].to_numpy(dtype=float)
        if len(path) < 5:
            continue
        outcome, days = simulate_one_attempt(path, risk_scale=1.0, rules=rules)
        if outcome == "pass":
            passes += 1
            days_list.append(days)
    n = len(starts)
    return {
        "n_starts": n,
        "pass_rate": passes / n if n else 0.0,
        "median_days_to_pass": float(np.median(days_list)) if days_list else None,
        "cadence_days": every_days,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--max-tickers", type=int, default=0, help="0 = all S&P with data")
    ap.add_argument("--out", default="/opt/cursor/artifacts/equity_momentum_rotation.json")
    args = ap.parse_args()

    tickers = sp500_tickers()
    if args.max_tickers > 0:
        tickers = tickers[: args.max_tickers]
    start = date.fromisoformat(args.start)
    panel, sources = load_equity_panel(tickers, start=start)
    if panel.shape[1] < 50:
        raise RuntimeError(f"too few symbols loaded ({panel.shape[1]})")

    books = compare_rotations(panel, top_n=args.top_n)
    spy, _ = load_etf("SPY")
    spy = spy.reindex(panel.index).ffill().pct_change(fill_method=None).fillna(0.0).rename("SPY_bh")

    rows = []
    for name, net in {**books, "SPY_buy_hold": spy}.items():
        for label, sl in [("IS", net.loc[:is_end]), ("OOS", net.loc[cut:])]:
            k = kpis_from_net(sl)
            rows.append({"book": name, "slice": label, **k})
        oos = net.loc[cut:].fillna(0.0)
        mc = run_mc_grid(
            net,
            np.round(np.arange(0.8, 2.01, 0.2), 2),
            is_end=is_end,
            mc=McParams(n_sims=600, block_len=10),
        )
        best = mc.loc[mc["ev_per_day_usd"].idxmax()]
        pipe = overlapping_eval_starts(net, every_days=14)
        rows.append({
            "book": name,
            "slice": "OOS_meta",
            "oos_max_dd": kpis_from_net(oos)["max_dd"],
            "mc_best_scale": float(best["risk_scale"]),
            "mc_pass_rate": float(best["pass_rate"]),
            "mc_ev_per_day": float(best["ev_per_day_usd"]),
            "eval_every_14d_pass_rate": pipe["pass_rate"],
            "eval_every_14d_median_days_pass": pipe.get("median_days_to_pass"),
        })

    tbl = pd.DataFrame(rows)
    print("Loaded symbols:", panel.shape[1], "bars:", len(panel))
    print(tbl[tbl["slice"].isin(["IS", "OOS"])].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    meta_cols = [
        "book", "mc_pass_rate", "mc_ev_per_day", "eval_every_14d_pass_rate",
        "eval_every_14d_median_days_pass", "oos_max_dd",
    ]
    print("\nProp proxies (OOS, IS-bootstrap MC + overlapping 14d eval starts):")
    print(tbl[tbl["slice"] == "OOS_meta"][meta_cols].to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # Story metrics
    pure = books[f"top{args.top_n}_momentum_monthly"]
    ma = books[f"top{args.top_n}_momentum_sma200_monthly"]
    k_pure = kpis_from_net(pure.loc[cut:])
    k_ma = kpis_from_net(ma.loc[cut:])
    story = {
        "survivorship": "Current S&P 500 members on full history (biased; FTMO-style selection)",
        "OOS": {
            "momentum_only": k_pure,
            "momentum_sma200": k_ma,
            "sma200_reduced_dd": k_ma["max_dd"] > k_pure["max_dd"],
            "sma200_cagr_delta": k_ma["cagr"] - k_pure["cagr"],
        },
        "n_symbols": int(panel.shape[1]),
    }
    print("\nStory OOS:", json.dumps(story["OOS"], indent=2, default=float))

    payload = {
        "hypothesis": "monthly top-N momentum vs top-N + close> SMA200",
        "top_n": args.top_n,
        "start": args.start,
        "story": story,
        "results": rows,
        "sources_note": f"{len(sources)} equity series via yahoo/stooq cache",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
