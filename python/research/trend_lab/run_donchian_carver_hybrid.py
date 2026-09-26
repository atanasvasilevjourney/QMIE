"""Donchian Combo (SSRN) × Carver engine × cross-sectional rank (HedgeFund_WiP port).

Uses:
  - ``carver.py`` — absolute forecast sizing (engine notebook)
  - ``carver_book.py`` — ranked top-N + portfolio vol scale (cross-sectional layer)
  - Donchian Combo weights — same as notebook 09

Research only. Does not touch live QMIE scanner.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from research.trend_lab.allocation import blend_weights
from research.trend_lab.carver import VOL_TARGET
from research.trend_lab.carver_book import BookParams, book_from_raw_weights, carver_weight_panel
from research.trend_lab.data import load_symbol
from research.trend_lab.donchian_combo import (
    ANN,
    COST_BPS,
    EXEC_LAG,
    MCAP_TOP20,
    combo_weight_series,
    equal_weight_portfolio,
)
from research.trend_lab.metrics import kpis_from_net
from research.trend_lab.protocol import SPLIT

MIN_BARS = 370


def load_panel(symbols: list[str]) -> pd.DataFrame:
    def _one(sym: str):
        df, _ = load_symbol(sym, "1d", start=date(2015, 1, 1))
        return sym, df

    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(_one, symbols))
    ok = {s: df["close"] for s, df in rows if len(df) >= MIN_BARS}
    return pd.DataFrame(ok).sort_index()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="/opt/cursor/artifacts/donchian_carver_hybrid_results.json")
    args = p.parse_args()

    panel = load_panel(MCAP_TOP20)
    w_don = pd.DataFrame({s: combo_weight_series(panel[s]) for s in panel.columns})
    w_car = carver_weight_panel(panel, use_cs=True, ann_days=ANN)

    w_blend = pd.DataFrame(
        {s: blend_weights(w_car[s], w_don[s], mix=0.5) for s in panel.columns},
        index=panel.index,
    )
    w_gate = w_car * (w_don > 0.01).astype(float)

    cs_params = BookParams(vol_target=VOL_TARGET, lookback=60, top_n=5, cost_bps=COST_BPS, exec_lag=EXEC_LAG)

    books = {
        "donchian_combo_equal20": equal_weight_portfolio(w_don, panel),
        "carver_engine_equal20": equal_weight_portfolio(w_car, panel),
        "blend50_equal20": equal_weight_portfolio(w_blend, panel),
        "gate_carver_if_donchian_eq20": equal_weight_portfolio(w_gate, panel),
        "carver_cs_rank_top5": book_from_raw_weights(panel, w_car, cs_params)["net"],
        "donchian_cs_rank_top5": book_from_raw_weights(panel, w_don, cs_params)["net"],
        "blend_cs_rank_top5": book_from_raw_weights(panel, w_blend, cs_params)["net"],
        "gate_cs_rank_top5": book_from_raw_weights(panel, w_gate, cs_params)["net"],
    }

    cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
    start_cap = 100_000.0
    rows = []
    for name, net in books.items():
        full = kpis_from_net(net)
        oos = kpis_from_net(net.loc[cut:])
        is_ = kpis_from_net(net.loc[: cut - pd.Timedelta(days=1)])
        oos_net = net.loc[cut:].fillna(0.0)
        oos_pnl = float(start_cap * ((1.0 + oos_net).prod() - 1.0))
        full_pnl = float(start_cap * ((1.0 + net.fillna(0.0)).prod() - 1.0))
        rows.append({
            "book": name,
            "full_sharpe": full["sharpe"],
            "oos_sharpe": oos["sharpe"],
            "oos_cagr": oos["cagr"],
            "oos_max_dd": oos["max_dd"],
            "is_sharpe": is_["sharpe"],
            "oos_pnl_usd_100k": oos_pnl,
            "full_pnl_usd_100k": full_pnl,
        })

    table = pd.DataFrame(rows).sort_values("oos_sharpe", ascending=False)
    print(table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    payload = {
        "source_notebooks": "HedgeFund_WiP/carver_engine_with_cross_sectional.ipynb (ported to trend_lab/carver.py + carver_book.py)",
        "universe": list(panel.columns),
        "mcap_top20_intent": MCAP_TOP20,
        "cs_params": {"lookback": 60, "top_n": 5, "vol_target": VOL_TARGET},
        "results": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
