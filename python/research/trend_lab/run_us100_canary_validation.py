"""Validate US100 canary gating S&P top-10 monthly momentum."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from research.trend_lab.data import load_etf
from research.trend_lab.equity_universe import load_equity_panel, sp500_tickers
from research.trend_lab.metrics import kpis_from_net
from research.trend_lab.momentum_rotation import (
    RotationParams,
    monthly_top_momentum_weights,
    rotation_net_returns,
)
from research.trend_lab.mentor_prop import dial_return_scale_is, ftmo_daily_stats
from research.trend_lab.protocol import SPLIT
from research.trend_lab.us100_canary import us100_bull_canary

cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
is_end = cut - pd.Timedelta(days=1)
FTMO_MAX_DD = -0.10
DEFAULT_DD_FLOOR = -0.08


def gated_net(
    panel: pd.DataFrame,
    canary: pd.Series,
    p: RotationParams,
    *,
    gross_when_on: float = 1.0,
) -> pd.Series:
    w = monthly_top_momentum_weights(panel, p)
    mult = canary.reindex(panel.index).ffill().fillna(0.0) * gross_when_on
    w = w.mul(mult, axis=0)
    return rotation_net_returns(panel, w, p)


def prop_row(name: str, net: pd.Series, *, max_dd_floor: float) -> dict:
    sc, scaled = dial_return_scale_is(net, is_end, max_dd_floor=max_dd_floor)
    oos = scaled.loc[cut:].fillna(0.0)
    k = kpis_from_net(oos)
    fd = ftmo_daily_stats(oos)
    return {
        "book": name,
        "slice": "OOS_prop_dial",
        "is_return_scale": sc,
        "is_max_dd_floor": max_dd_floor,
        **k,
        "ftmo_10pct_ok": k["max_dd"] > FTMO_MAX_DD,
        **fd,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--out", default="/opt/cursor/artifacts/us100_canary_validation.json")
    ap.add_argument("--max-dd-floor", type=float, default=DEFAULT_DD_FLOOR)
    ap.add_argument("--canary-gross", type=float, default=1.0, help="Scale stock gross when canary ON (before prop dial)")
    args = ap.parse_args()

    panel, _ = load_equity_panel(sp500_tickers(), start=date.fromisoformat(args.start))
    qqq, qsrc = load_etf("QQQ")
    qqq = qqq.reindex(panel.index).ffill()
    canary_both = us100_bull_canary(qqq, mode="both")
    canary_don = us100_bull_canary(qqq, mode="donchian")
    canary_ma = us100_bull_canary(qqq, mode="sma200")

    p = RotationParams(top_n=args.top_n, use_sma200_filter=False)
    p_ma = RotationParams(top_n=args.top_n, use_sma200_filter=True)

    books = {
        "top10_momentum_ungated": rotation_net_returns(
            panel, monthly_top_momentum_weights(panel, p), p,
        ),
        "top10_momentum_per_stock_sma200": rotation_net_returns(
            panel, monthly_top_momentum_weights(panel, p_ma), p_ma,
        ),
        "top10_gated_us100_canary_both": gated_net(
            panel, canary_both, p, gross_when_on=args.canary_gross,
        ),
        "top10_gated_us100_donchian_only": gated_net(panel, canary_don, p, gross_when_on=args.canary_gross),
        "top10_gated_us100_sma200_only": gated_net(panel, canary_ma, p, gross_when_on=args.canary_gross),
    }
    spy = load_etf("SPY")[0].reindex(panel.index).ffill().pct_change(fill_method=None).fillna(0.0)
    books["SPY_buy_hold"] = spy.rename("net")

    rows = []
    for name, net in books.items():
        for label, sl in [("IS", net.loc[:is_end]), ("OOS", net.loc[cut:])]:
            k = kpis_from_net(sl)
            rows.append({"book": name, "slice": label, **k})
    canary_pct = float(canary_both.loc[cut:].mean())
    story = {
        "proxy": "QQQ as US100",
        "qqq_source": qsrc,
        "n_stocks": int(panel.shape[1]),
        "canary_both_OOS_pct_days_on": canary_pct,
        "survivorship": "Current S&P 500 members on full history (biased)",
    }
    oos_tbl = pd.DataFrame([r for r in rows if r["slice"] == "OOS"]).set_index("book")
    ung = oos_tbl.loc["top10_momentum_ungated"]
    gated = oos_tbl.loc["top10_gated_us100_canary_both"]
    story["OOS_compare_canary_both_vs_ungated"] = {
        "cagr_delta": float(gated["cagr"] - ung["cagr"]),
        "max_dd_improved": bool(gated["max_dd"] > ung["max_dd"]),
        "sharpe_delta": float(gated["sharpe"] - ung["sharpe"]),
    }

    prop_rows = [prop_row(n, net, max_dd_floor=args.max_dd_floor) for n, net in books.items() if n != "SPY_buy_hold"]
    story["prop_note"] = (
        "Raw max DD is not prop-safe. OOS_prop_dial applies IS-only return scale to sit near max_dd_floor "
        "under FTMO 10% static loss proxy."
    )
    story["OOS_prop_dial"] = {r["book"]: r for r in prop_rows}

    print("Symbols", panel.shape[1], "QQQ", qsrc, "canary_gross", args.canary_gross)
    print("\n--- Raw OOS (not prop-safe) ---")
    print(oos_tbl[["sharpe", "cagr", "max_dd", "calmar"]].round(4).to_string())
    prop_tbl = pd.DataFrame(prop_rows).set_index("book")
    print(f"\n--- OOS after IS prop dial (floor {args.max_dd_floor:.0%}) ---")
    print(prop_tbl[["is_return_scale", "sharpe", "cagr", "max_dd", "ftmo_10pct_ok", "worst_daily_loss_pct"]].round(4))
    print("\nStory:", json.dumps(story["OOS_compare_canary_both_vs_ungated"], indent=2))

    payload = {"story": story, "results": rows, "prop_dial": prop_rows}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
