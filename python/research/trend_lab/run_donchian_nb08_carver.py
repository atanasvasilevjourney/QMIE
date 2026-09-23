"""Notebook 08 Donchian (dual channel) × Carver — research CLI."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from research.trend_lab.allocation import blend_weights
from research.trend_lab.carver import VOL_TARGET
from research.trend_lab.data import DEFAULT_UNIVERSE, load_symbol
from research.trend_lab.donchian_combo import COST_BPS, EXEC_LAG, equal_weight_portfolio
from research.trend_lab.donchian_nb08 import Donchian08Params, donchian_nb08_weight_panel
from research.trend_lab.carver_book import carver_weight_panel
from research.trend_lab.metrics import kpis_from_net
from research.trend_lab.protocol import SPLIT, WARMUP_BARS

START_CAP = 100_000.0


def load_ohlcv(symbols: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df, _ = load_symbol(sym, "1d", start=date(2015, 1, 1))
        if len(df) >= WARMUP_BARS:
            out[sym] = df
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/opt/cursor/artifacts/donchian_nb08_carver_results.json")
    args = ap.parse_args()

    symbols = ["BTCUSDT"] + [s for s in DEFAULT_UNIVERSE if s != "BTCUSDT"]
    ohlcv = load_ohlcv(symbols)
    panel = pd.DataFrame({s: df["close"] for s, df in ohlcv.items()}).sort_index()
    p = Donchian08Params()

    w_don = donchian_nb08_weight_panel(ohlcv, p).reindex(panel.index).fillna(0.0)
    w_car = carver_weight_panel(panel, use_cs=True, ann_days=365)
    w_blend = pd.DataFrame(
        {s: blend_weights(w_car[s], w_don[s], mix=0.5) for s in panel.columns},
        index=panel.index,
    )
    w_gate = w_car * (w_don > 0.01).astype(float)

    books = {
        "donchian_nb08_eq": equal_weight_portfolio(w_don, panel),
        "carver_eq": equal_weight_portfolio(w_car, panel),
        "blend_50_50_eq": equal_weight_portfolio(w_blend, panel),
        "gate_carver_if_donchian_eq": equal_weight_portfolio(w_gate, panel),
    }

    cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
    rows = []
    for name, net in books.items():
        oos = net.loc[cut:].fillna(0.0)
        k = kpis_from_net(oos)
        rows.append({
            "book": name,
            "oos_sharpe": k["sharpe"],
            "oos_cagr": k["cagr"],
            "oos_max_dd": k["max_dd"],
            "oos_pnl_100k": float(START_CAP * ((1.0 + oos).prod() - 1.0)),
            "full_sharpe": kpis_from_net(net)["sharpe"],
        })

    table = pd.DataFrame(rows).sort_values("oos_sharpe", ascending=False)
    print(table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    payload = {
        "focus": "notebook_08_donchian_dual_55_20_x_carver",
        "params": {"n_entry": p.n_entry, "n_exit": p.n_exit, "avwap": p.use_avwap_gate, "compression": p.use_compression_gate},
        "universe": list(panel.columns),
        "results": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
