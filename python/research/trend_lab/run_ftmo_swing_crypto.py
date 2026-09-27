"""Carver + Donchian (nb08) on crypto list — FTMO Swing $100K sizing dial.

IS-only scale to target max drawdown; report OOS including worst daily loss
(5% MDL proxy). Research only.
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
from research.trend_lab.carver_book import carver_weight_panel
from research.trend_lab.data import load_symbol
from research.trend_lab.donchian_combo import MCAP_TOP20, equal_weight_portfolio
from research.trend_lab.donchian_nb08 import Donchian08Params, donchian_nb08_weight_panel
from research.trend_lab.metrics import kpis_from_net, max_dd
from research.trend_lab.protocol import SPLIT, WARMUP_BARS

# Liquid USDT-M proxy for “crypto list” on a swing book (Vision data).
FTMO_CRYPTO_LIST = MCAP_TOP20
MIN_BARS = 370
START_CAP = 100_000.0
FTMO_MAX_LOSS_PCT = 0.10
FTMO_DAILY_LOSS_PCT = 0.05


def load_ohlcv(symbols: list[str]) -> dict[str, pd.DataFrame]:
    def _one(sym: str):
        df, src = load_symbol(sym, "1d", start=date(2015, 1, 1))
        return sym, df, src

    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(_one, symbols))
    out = {s: df for s, df, _ in rows if len(df) >= MIN_BARS}
    return out


def dial_scale_is(
    net: pd.Series,
    is_end: pd.Timestamp,
    *,
    max_dd_floor: float = -0.08,
) -> tuple[float, pd.Series]:
    """Largest return scale on IS such that max_dd is **no worse** than ``max_dd_floor``."""
    is_net = net.loc[:is_end].fillna(0.0)
    chosen = 0.08
    for sc in np.arange(0.08, 1.51, 0.02):
        dd = max_dd((1.0 + is_net * sc).cumprod())
        if dd >= max_dd_floor:  # e.g. -0.05 better than -0.08
            chosen = float(sc)
        else:
            break
    return chosen, net.fillna(0.0) * chosen


def ftmo_daily_stats(net: pd.Series, *, start_cap: float = START_CAP) -> dict[str, float]:
    net = net.fillna(0.0)
    eq = start_cap * (1.0 + net).cumprod()
    bal = eq.shift(1).fillna(start_cap)
    day_pnl = bal * net
    day_loss_pct = day_pnl / bal
    worst_day_usd = float(day_pnl.min())
    worst_day_pct = float(day_loss_pct.min())
    breach_5pct = int((day_loss_pct < -FTMO_DAILY_LOSS_PCT).sum())
    breach_3pct = int((day_loss_pct < -0.03).sum())
    return {
        "worst_daily_pnl_usd": worst_day_usd,
        "worst_daily_loss_pct": worst_day_pct,
        "days_breach_5pct_mdl_proxy": breach_5pct,
        "days_breach_3pct_buffer": breach_3pct,
        "bars": float(len(net)),
    }


def build_books(panel: pd.DataFrame, ohlcv: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    p_don = Donchian08Params(target_vol_ann=0.17)  # nb08 ~10% DD dial (IS) from prior run
    w_don = donchian_nb08_weight_panel(ohlcv, p_don).reindex(panel.index).fillna(0.0)
    w_car = carver_weight_panel(panel, use_cs=True, ann_days=365)
    w_blend = pd.DataFrame(
        {s: blend_weights(w_car[s], w_don[s], mix=0.5) for s in panel.columns},
        index=panel.index,
    )
    w_gate = w_car * (w_don > 0.01).astype(float)
    return {
        "gate_carver_x_donchian_nb08": equal_weight_portfolio(w_gate, panel),
        "blend_50_50": equal_weight_portfolio(w_blend, panel),
        "carver_only": equal_weight_portfolio(w_car, panel),
        "donchian_nb08_only": equal_weight_portfolio(w_don, panel),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-dd-floor", type=float, default=-0.08, help="IS max DD floor (default -8%% under FTMO 10%%)")
    ap.add_argument("--out", default="/opt/cursor/artifacts/ftmo_swing_crypto_carver_donchian.json")
    args = ap.parse_args()

    ohlcv = load_ohlcv(FTMO_CRYPTO_LIST)
    loaded = list(ohlcv.keys())
    panel = pd.DataFrame({s: ohlcv[s]["close"] for s in loaded}).sort_index()
    cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
    is_end = cut - pd.Timedelta(days=1)

    raw = build_books(panel, ohlcv)
    rows = []
    for name, net in raw.items():
        sc, scaled = dial_scale_is(net, is_end, max_dd_floor=args.max_dd_floor)
        # Sparse IS books can dial to 1.5× with ~0 IS DD; cap at carver-only dial when IS is flat.
        is_k_raw = kpis_from_net(net.loc[:is_end].fillna(0.0))
        if abs(is_k_raw["max_dd"]) < 0.01 and name != "carver_only":
            sc_cap, _ = dial_scale_is(raw["carver_only"], is_end, max_dd_floor=args.max_dd_floor)
            sc = min(sc, sc_cap)
            scaled = net.fillna(0.0) * sc
        is_k = kpis_from_net(scaled.loc[:is_end])
        oos_k = kpis_from_net(scaled.loc[cut:])
        oos_daily = ftmo_daily_stats(scaled.loc[cut:])
        rows.append({
            "book": name,
            "is_scale": sc,
            "is_max_dd": is_k["max_dd"],
            "oos_sharpe": oos_k["sharpe"],
            "oos_cagr": oos_k["cagr"],
            "oos_max_dd": oos_k["max_dd"],
            "oos_pnl_100k": float(START_CAP * ((1.0 + scaled.loc[cut:]).prod() - 1.0)),
            "ftmo_static_10pct_ok_oos": bool(oos_k["max_dd"] > -FTMO_MAX_LOSS_PCT),
            **{f"oos_{k}": v for k, v in oos_daily.items()},
        })

    ok = [r for r in rows if r["ftmo_static_10pct_ok_oos"] and r["oos_worst_daily_loss_pct"] > -FTMO_DAILY_LOSS_PCT]
    ok.sort(key=lambda r: -r["oos_sharpe"])
    primary = ok[0]["book"] if ok else rows[0]["book"]
    for r in rows:
        r["recommended_ftmo"] = r["book"] == primary

    rows.sort(key=lambda r: (-float(r["recommended_ftmo"]), -float(r["oos_sharpe"])))
    df = pd.DataFrame(rows)
    print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    payload = {
        "mandate": "FTMO_Swing_100K_proxy",
        "rules_proxy": {
            "max_loss_pct": FTMO_MAX_LOSS_PCT,
            "daily_loss_pct": FTMO_DAILY_LOSS_PCT,
            "is_max_dd_floor": args.max_dd_floor,
            "note": "Vision USDT-M 1d; not FTMO CFD fills/swaps. IS-only scale on returns.",
        },
        "universe_requested": FTMO_CRYPTO_LIST,
        "universe_loaded": loaded,
        "primary_book": primary,
        "results": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
