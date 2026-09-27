"""CLI for CS prop basket (notebook 16)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from research.trend_lab.cs_prop_basket import (
    UNIVERSE_10,
    UNIVERSE_20,
    CsBasketParams,
    avg_pairwise_corr,
    evaluate_cs_basket,
    load_cs_panel,
)
from research.trend_lab.mentor_prop import ftmo_daily_stats
from research.trend_lab.protocol import SPLIT

is_end = pd.Timestamp(SPLIT.is_end, tz="UTC")
cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, choices=(10, 20), default=10)
    ap.add_argument("--gross", type=float, default=0.68)
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--out", default="/opt/cursor/artifacts/cs_prop_basket.json")
    args = ap.parse_args()

    syms = UNIVERSE_10 if args.n == 10 else UNIVERSE_20
    p = CsBasketParams(gross_target=args.gross, top_n=min(args.top_n, len(syms)))
    panel, sources = load_cs_panel(syms)
    if panel.shape[1] < 3:
        raise SystemExit(f"too few symbols loaded: {panel.columns.tolist()} sources={sources}")

    ev = evaluate_cs_basket(panel, p, is_end=is_end)
    oos_net = ev["net"].loc[cut:]
    payload = {
        "universe": list(panel.columns),
        "sources": sources,
        "protocol": {"is_end": str(is_end.date()), "oos_start": str(cut.date())},
        "params": {
            "horizons": p.horizons,
            "min_votes": p.min_votes,
            "top_n": p.top_n,
            "gross_target": p.gross_target,
        },
        "avg_corr_60d_oos": avg_pairwise_corr(panel.loc[cut:], lookback=60),
        "avg_gross": ev["avg_gross"],
        "avg_names": ev["avg_names"],
        "is": ev["is"],
        "oos": {**ev["oos"], **ftmo_daily_stats(oos_net)},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print("symbols", list(panel.columns))
    print("OOS", payload["oos"])
    print("wrote", out)


if __name__ == "__main__":
    main()
