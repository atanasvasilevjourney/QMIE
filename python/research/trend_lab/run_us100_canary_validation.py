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
from research.trend_lab.protocol import SPLIT
from research.trend_lab.us100_canary import us100_bull_canary

cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
is_end = cut - pd.Timedelta(days=1)


def gated_net(panel: pd.DataFrame, canary: pd.Series, p: RotationParams) -> pd.Series:
    w = monthly_top_momentum_weights(panel, p)
    mult = canary.reindex(panel.index).ffill().fillna(0.0)
    w = w.mul(mult, axis=0)
    return rotation_net_returns(panel, w, p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--out", default="/opt/cursor/artifacts/us100_canary_validation.json")
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
        "top10_gated_us100_canary_both": gated_net(panel, canary_both, p),
        "top10_gated_us100_donchian_only": gated_net(panel, canary_don, p),
        "top10_gated_us100_sma200_only": gated_net(panel, canary_ma, p),
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

    print("Symbols", panel.shape[1], "QQQ", qsrc)
    print(oos_tbl[["sharpe", "cagr", "max_dd", "calmar"]].round(4).to_string())
    print("\nStory:", json.dumps(story["OOS_compare_canary_both_vs_ungated"], indent=2))

    payload = {"story": story, "results": rows}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
