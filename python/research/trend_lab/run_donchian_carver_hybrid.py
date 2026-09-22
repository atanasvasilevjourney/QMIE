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
from research.trend_lab.metrics import kpis_from_net
from research.trend_lab.protocol import SPLIT

MCAP_TOP20 = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "TRXUSDT", "ZECUSDT", "DOGEUSDT",
    "HYPEUSDT", "ADAUSDT", "LINKUSDT", "XLMUSDT", "UNIUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT",
    "NEARUSDT", "DOTUSDT", "ENAUSDT", "SUIUSDT",
]

HORIZONS = (5, 10, 20, 30, 60, 90, 150, 250, 360)
DON_VOL_TARGET = 0.25
SIGMA_DAYS = 90
LEV_CAP = 2.0
COST_BPS = 10.0
REBAL_THRESH = 0.20
EXEC_LAG = 1
ANN = 365
MIN_BARS = 370


def combo_weight_series(close: pd.Series) -> pd.Series:
    c = close.to_numpy(dtype=float)
    n_bars = len(c)
    sigma = close.pct_change().rolling(SIGMA_DAYS).std(ddof=1).to_numpy(dtype=float) * np.sqrt(ANN)
    mids, ups = {}, {}
    for n in HORIZONS:
        up = close.rolling(n, min_periods=n).max().to_numpy(dtype=float)
        dn = close.rolling(n, min_periods=n).min().to_numpy(dtype=float)
        mids[n] = (up + dn) / 2
        ups[n] = up
    nh = len(HORIZONS)
    in_pos = np.zeros(nh, dtype=bool)
    trail = np.full(nh, np.nan)
    w_exec = np.zeros(nh)
    w_combo = np.zeros(n_bars)
    for i in range(n_bars):
        ci = c[i]
        sig = sigma[i]
        for j, n in enumerate(HORIZONS):
            mid, up = mids[n][i], ups[n][i]
            if not in_pos[j]:
                if np.isfinite(up) and ci >= up:
                    in_pos[j] = True
                    trail[j] = mid
            else:
                if np.isfinite(trail[j]) and ci < trail[j]:
                    in_pos[j] = False
                    trail[j] = np.nan
                elif np.isfinite(mid):
                    trail[j] = max(trail[j], mid)
            w_tgt = 0.0
            if in_pos[j] and np.isfinite(sig) and sig > 0:
                w_tgt = min(LEV_CAP, DON_VOL_TARGET / sig)
            if abs(w_tgt - w_exec[j]) > REBAL_THRESH:
                w_exec[j] = w_tgt
        w_combo[i] = w_exec.mean()
    return pd.Series(w_combo, index=close.index)


def equal_weight_portfolio(raw_w: pd.DataFrame, panel: pd.DataFrame) -> pd.Series:
    """Mean of per-asset net returns (notebook 09 style)."""
    rets = panel.pct_change(fill_method=None).fillna(0.0)
    held = raw_w.shift(EXEC_LAG).fillna(0.0)
    nets = {}
    for c in raw_w.columns:
        w = held[c]
        nets[c] = w * rets[c] - w.diff().abs().fillna(w.abs()) * (COST_BPS / 1e4)
    return pd.DataFrame(nets).mean(axis=1)


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
    rows = []
    for name, net in books.items():
        full = kpis_from_net(net)
        oos = kpis_from_net(net.loc[cut:])
        is_ = kpis_from_net(net.loc[: cut - pd.Timedelta(days=1)])
        rows.append({"book": name, "full_sharpe": full["sharpe"], "oos_sharpe": oos["sharpe"],
                     "oos_cagr": oos["cagr"], "oos_max_dd": oos["max_dd"], "is_sharpe": is_["sharpe"]})

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
