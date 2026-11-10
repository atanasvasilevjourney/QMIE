"""FTI (Khalsa) × Donchian nb08 × Carver — OOS edge search. Research only."""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from research.trend_lab.allocation import blend_weights
from research.trend_lab.carver_book import carver_weight_panel
from research.trend_lab.data import load_symbol
from research.trend_lab.donchian_combo import MCAP_TOP20, equal_weight_portfolio
from research.trend_lab.donchian_nb08 import Donchian08Params, donchian_nb08_weight_panel
from research.trend_lab.fti_khalsa import fti_panel
from research.trend_lab.metrics import kpis_from_net
from research.trend_lab.protocol import SPLIT

MIN_BARS = 400
THRESHOLDS = (0.0, 10.0, 20.0)


def load_panel(symbols: list[str]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    def _one(sym: str):
        df, _ = load_symbol(sym, "1d", start=date(2015, 1, 1))
        return sym, df

    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(_one, symbols))
    ohlcv = {s: df for s, df in rows if len(df) >= MIN_BARS}
    panel = pd.DataFrame({s: df["close"] for s, df in ohlcv.items()}).sort_index()
    return ohlcv, panel


def apply_fti_gate(w: pd.DataFrame, fti: pd.DataFrame, thresh: float) -> pd.DataFrame:
    gate = (fti.shift(1) > thresh).astype(float)
    return w.mul(gate).reindex(w.index).fillna(0.0)


def apply_fti_scale(w: pd.DataFrame, fti: pd.DataFrame) -> pd.DataFrame:
    """Scale weights up when FTI continuation is strong (causal)."""
    s = ((50.0 + fti.shift(1)) / 100.0).clip(0.0, 1.5)
    return w.mul(s).reindex(w.index).fillna(0.0)


def forward_edge(fti: pd.Series, close: pd.Series, horizon: int = 5) -> dict[str, float]:
    ret = close.pct_change(horizon, fill_method=None).shift(-horizon)
    f = fti.shift(1)
    df = pd.concat([f, ret], axis=1, keys=["fti", "ret"]).dropna()
    if len(df) < 100:
        return {"n": float(len(df)), "corr": float("nan"), "p": float("nan")}
    c, p = stats.pearsonr(df["fti"], df["ret"])
    return {"n": float(len(df)), "corr": float(c), "p": float(p)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/opt/cursor/artifacts/fti_donchian_carver_edge.json")
    args = ap.parse_args()

    ohlcv, panel = load_panel(MCAP_TOP20)
    cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")

    print("computing FTI panel…")
    fti = fti_panel(panel)
    p_don = Donchian08Params(target_vol_ann=0.17)
    w_don = donchian_nb08_weight_panel(ohlcv, p_don).reindex(panel.index).fillna(0.0)
    w_car = carver_weight_panel(panel, use_cs=True, ann_days=365)
    w_blend = pd.DataFrame(
        {s: blend_weights(w_car[s], w_don[s], mix=0.5) for s in panel.columns},
        index=panel.index,
    )

    bases = {
        "donchian_nb08": w_don,
        "carver": w_car,
        "blend_50_50": w_blend,
    }

    rows = []
    for bname, w in bases.items():
        net0 = equal_weight_portfolio(w, panel)
        k0 = kpis_from_net(net0.loc[cut:])
        rows.append({"book": bname, "variant": "baseline", "fti_thresh": None, **k0})

        for th in THRESHOLDS:
            wg = apply_fti_gate(w, fti, th)
            net = equal_weight_portfolio(wg, panel)
            k = kpis_from_net(net.loc[cut:])
            rows.append({"book": bname, "variant": "fti_gate", "fti_thresh": th, **k})

        ws = apply_fti_scale(w, fti)
        net = equal_weight_portfolio(ws, panel)
        k = kpis_from_net(net.loc[cut:])
        rows.append({"book": bname, "variant": "fti_scale", "fti_thresh": None, **k})

    # Predictive sanity: FTI vs 5d forward return (OOS only, not a strategy)
    pred = []
    for sym in panel.columns:
        oos_f = fti[sym].loc[cut:]
        oos_c = panel[sym].loc[cut:]
        pred.append({"symbol": sym, **forward_edge(oos_f, oos_c, 5)})
    pred_df = pd.DataFrame(pred)
    mean_corr = float(pred_df["corr"].mean())

    # Rank by OOS Sharpe vs baseline blend
    blend_base_sh = next(r["sharpe"] for r in rows if r["book"] == "blend_50_50" and r["variant"] == "baseline")
    winners = [
        r for r in rows
        if r["sharpe"] > blend_base_sh and r["variant"] != "baseline"
    ]
    winners.sort(key=lambda r: -r["sharpe"])

    payload = {
        "source": "Khalsa FTI via indicatorPy (TSSB/Masters); causal fti.shift(1)",
        "universe": list(panel.columns),
        "oos_start": str(cut.date()),
        "strategy_rows": rows,
        "fti_forward_5d_corr_oos_mean": mean_corr,
        "per_symbol_forward_corr": pred_df.to_dict(orient="records"),
        "blend_baseline_oos_sharpe": blend_base_sh,
        "beats_blend_baseline": winners[:5],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))

    tbl = pd.DataFrame(rows).sort_values(["book", "variant", "fti_thresh"])
    print(tbl[["book", "variant", "fti_thresh", "sharpe", "cagr", "max_dd"]].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("OOS mean FTI→5d return corr", round(mean_corr, 4))
    print("Top variants vs blend baseline Sharpe", blend_base_sh)
    for w in winners[:3]:
        print(w["book"], w["variant"], w.get("fti_thresh"), "sharpe", round(w["sharpe"], 4))
    print("wrote", out)


if __name__ == "__main__":
    main()
