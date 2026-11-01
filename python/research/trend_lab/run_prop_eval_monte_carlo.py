"""Monte Carlo eval rinse: EV/day vs risk scale for research books."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from research.trend_lab.carver_book import ANN_SESSIONS, BookParams, book_from_raw_weights, carver_weight_panel, pick_vol_target
from research.trend_lab.data import DEFAULT_UNIVERSE, load_symbol, mixed_panel
from research.trend_lab.donchian_combo import COST_BPS, equal_weight_portfolio
from research.trend_lab.donchian_vwap_book import DonchianVwapParams, run_book, dial_target_vol_is
from research.trend_lab.mentor_prop import mentor_gated_weights, dial_return_scale_is
from research.trend_lab.prop_eval_mc import EvalEconomics, EvalRules, McParams, run_mc_grid, sensitivity_ok
from research.trend_lab.protocol import SPLIT, WARMUP_BARS
from research.trend_lab.spot_system import SpotParams, spot_signal
from research.trend_lab.carver_book import carver_weight_panel as cwp

cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
is_end = cut - pd.Timedelta(days=1)


def net_weekly_rank3() -> pd.Series:
    from concurrent.futures import ThreadPoolExecutor

    syms = ["BTCUSDT"] + [s for s in DEFAULT_UNIVERSE if s != "BTCUSDT"]

    def _one(sym: str):
        df, src = load_symbol(sym, "1d", start=date(2015, 1, 1))
        return sym, df, src

    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(_one, syms))
    ohlcv = {s: df for s, df, _ in rows if len(df) >= WARMUP_BARS}
    alts = {k: v for k, v in ohlcv.items() if k != "BTCUSDT"}
    btc, _ = load_symbol("BTCUSDT", "1d", start=date(2015, 1, 1))
    base = DonchianVwapParams(top_k=3, single_name_cap=0.45, rebalance_rule="W-SUN")
    _, net = dial_target_vol_is(alts, btc, base, is_end, target_dd=-0.08)
    return net


def net_trio_ranked_carver() -> pd.Series:
    panel, _ = mixed_panel()
    is_p = panel.loc[:is_end]
    raw = carver_weight_panel(panel, use_cs=True, ann_days=ANN_SESSIONS)
    picked = pick_vol_target(is_p, raw.reindex(is_p.index).fillna(0.0), lookback=60, top_n=2)
    params = BookParams(vol_target=picked["vol_target"], lookback=60, top_n=2, cost_bps=2.0)
    return book_from_raw_weights(panel, raw, params)["net"]


def net_crypto_mentor_ensemble() -> pd.Series:
    from research.trend_lab.data import load_symbol as ls

    syms = ["BTCUSDT"] + [s for s in DEFAULT_UNIVERSE if s != "BTCUSDT"]
    ohlcv = {}
    for sym in syms:
        df, _ = ls(sym, "1d", start=date(2015, 1, 1))
        if len(df) >= WARMUP_BARS:
            ohlcv[sym] = df
    panel = pd.DataFrame({s: df["close"] for s, df in ohlcv.items()}).sort_index()
    w = cwp(panel, use_cs=True, ann_days=365)
    flags = pd.DataFrame(
        {s: spot_signal(ohlcv[s], SpotParams())["signal"].reindex(panel.index).fillna(0) for s in panel.columns},
        index=panel.index,
    )
    net = equal_weight_portfolio(mentor_gated_weights(w, flags), panel, cost_bps=COST_BPS)
    _, scaled = dial_return_scale_is(net, is_end)
    return scaled


BOOKS = {
    "crypto_weekly_rank3_don_vwap": net_weekly_rank3,
    "trio_ranked_carver": net_trio_ranked_carver,
    "crypto_mentor_ensemble_x_carver": net_crypto_mentor_ensemble,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="trio_ranked_carver", choices=list(BOOKS))
    ap.add_argument("--eval-cost", type=float, default=500.0)
    ap.add_argument("--expected-payout", type=float, default=8000.0)
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--out", default="/opt/cursor/artifacts/prop_eval_monte_carlo.json")
    args = ap.parse_args()

    net = BOOKS[args.book]()
    grid = np.round(np.arange(0.5, 3.01, 0.1), 2)
    df = run_mc_grid(
        net,
        grid,
        rules=EvalRules(),
        econ=EvalEconomics(eval_cost_usd=args.eval_cost, expected_payout_usd=args.expected_payout),
        mc=McParams(n_sims=args.sims),
        is_end=is_end,
    )
    best = df.loc[df["ev_per_day_usd"].idxmax()]
    sens = sensitivity_ok(df)
    print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nBest EV/day risk_scale", best["risk_scale"], "pass_rate", best["pass_rate"], "EV/day", best["ev_per_day_usd"])
    print("Neighbor sensitivity OK:", sens)

    payload = {
        "framework": "EV_per_day = (p*payout - cost) / T",
        "book": args.book,
        "regimes": {"eval": "maximize EV/day", "funded": "throttle vol — not simulated here"},
        "economics": {"eval_cost": args.eval_cost, "expected_payout": args.expected_payout},
        "bootstrap": "IS block bootstrap (pre-2023), not OOS",
        "sensitivity_ok": sens,
        "best": best.to_dict(),
        "grid": df.to_dict(orient="records"),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
