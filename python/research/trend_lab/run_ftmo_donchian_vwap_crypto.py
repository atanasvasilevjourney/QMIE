"""Crypto-only Donchian + AVWAP books — FTMO Swing $100K proxy.

Separate from BTC/QQQ/GLD trio (`run_btc_qqq_gld_suite.py`). No Carver merge.
IS-only vol dial (ranked books) or return scale (daily equal-weight).
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from research.trend_lab.data import DEFAULT_UNIVERSE, load_symbol
from research.trend_lab.donchian_combo import equal_weight_portfolio
from research.trend_lab.donchian_nb08 import Donchian08Params, dial_target_vol_for_dd, donchian_nb08_weight_panel
from research.trend_lab.donchian_vwap_book import DonchianVwapParams, dial_target_vol_is, run_book
from research.trend_lab.metrics import kpis_from_net, max_dd
from research.trend_lab.protocol import SPLIT

MIN_BARS = 370
START_CAP = 100_000.0
FTMO_MAX_LOSS_PCT = 0.10
FTMO_DAILY_LOSS_PCT = 0.05
CRYPTO_SYMBOLS = ["BTCUSDT"] + [s for s in DEFAULT_UNIVERSE if s != "BTCUSDT"]


def load_ohlcv(symbols: list[str]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    def _one(sym: str):
        df, src = load_symbol(sym, "1d", start=date(2015, 1, 1))
        return sym, df, src

    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(_one, symbols))
    ohlcv = {s: df for s, df, _ in rows if len(df) >= MIN_BARS}
    btc, _ = load_symbol("BTCUSDT", "1d", start=date(2015, 1, 1))
    return ohlcv, btc


def dial_scale_is(
    net: pd.Series,
    is_end: pd.Timestamp,
    *,
    max_dd_floor: float = -0.08,
) -> tuple[float, pd.Series]:
    is_net = net.loc[:is_end].fillna(0.0)
    chosen = 0.08
    for sc in np.arange(0.08, 1.51, 0.02):
        dd = max_dd((1.0 + is_net * sc).cumprod())
        if dd >= max_dd_floor:
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
    return {
        "worst_daily_pnl_usd": float(day_pnl.min()),
        "worst_daily_loss_pct": float(day_loss_pct.min()),
        "days_breach_5pct_mdl_proxy": int((day_loss_pct < -FTMO_DAILY_LOSS_PCT).sum()),
        "days_breach_3pct_buffer": int((day_loss_pct < -0.03).sum()),
        "bars": float(len(net)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-dd-floor", type=float, default=-0.08)
    ap.add_argument("--out", default="/opt/cursor/artifacts/ftmo_donchian_vwap_crypto.json")
    args = ap.parse_args()

    ohlcv, btc = load_ohlcv(CRYPTO_SYMBOLS)
    alts = {k: v for k, v in ohlcv.items() if k != "BTCUSDT"}
    panel = pd.DataFrame({s: ohlcv[s]["close"] for s in alts}).sort_index()
    cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
    is_end = cut - pd.Timedelta(days=1)

    base_vwap = DonchianVwapParams(
        use_avwap_gate=True,
        use_compression_gate=True,
        target_vol_ann=0.20,
        rebalance_rule="W-SUN",
    )
    base_daily = DonchianVwapParams(
        use_avwap_gate=True,
        use_compression_gate=True,
        target_vol_ann=0.20,
        rebalance_rule="D",
        min_strength=0.0,
        top_k=8,
    )

    books: dict[str, pd.Series] = {}

    vt_rank, net_rank = dial_target_vol_is(
        alts, btc, base_vwap, is_end, target_dd=args.max_dd_floor, ranked=True,
    )
    books["weekly_rank5_avwap_coil"] = net_rank

    base_weekly_k3 = DonchianVwapParams(
        **{
            **base_vwap.__dict__,
            "top_k": 3,
            "single_name_cap": 0.45,
        },
    )
    vt_k3, net_k3 = dial_target_vol_is(
        alts, btc, base_weekly_k3, is_end, target_dd=args.max_dd_floor, ranked=True,
    )
    books["weekly_rank3_avwap_coil"] = net_k3

    p_no_av = DonchianVwapParams(**{**base_vwap.__dict__, "use_avwap_gate": False, "target_vol_ann": vt_rank})
    books["weekly_rank_no_avwap"] = run_book(alts, btc, p_no_av, ranked=True)["net"]

    p_daily = DonchianVwapParams(**{**base_daily.__dict__, "target_vol_ann": vt_rank})
    books["daily_rank_avwap_coil"] = run_book(alts, btc, p_daily, ranked=True)["net"]

    vt_don, net_don = dial_target_vol_for_dd(
        {k: ohlcv[k] for k in alts},
        panel,
        is_end=is_end,
        target_dd=args.max_dd_floor,
    )
    books["daily_eq_donchian55_20_vol"] = net_don

    p_av = Donchian08Params(
        target_vol_ann=vt_don,
        use_avwap_gate=True,
        use_compression_gate=True,
    )
    w_av = donchian_nb08_weight_panel({k: ohlcv[k] for k in alts}, p_av).reindex(panel.index).fillna(0.0)
    books["daily_eq_don_avwap_coil"] = equal_weight_portfolio(w_av, panel)

    p_plain = Donchian08Params(target_vol_ann=vt_don, use_avwap_gate=False, use_compression_gate=False)
    w_plain = donchian_nb08_weight_panel({k: ohlcv[k] for k in alts}, p_plain).reindex(panel.index).fillna(0.0)
    books["daily_eq_don_plain"] = equal_weight_portfolio(w_plain, panel)

    rows = []
    for name, net in books.items():
        dial_note = ""
        if name.startswith("weekly") or name.startswith("daily_rank"):
            sc = 1.0
            scaled = net
            vt_note = vt_k3 if name == "weekly_rank3_avwap_coil" else vt_rank
            dial_note = f"top_k={'3' if 'rank3' in name else '5' if 'rank5' in name else '?'}; target_vol_ann={vt_note:.2f}"
            if name.startswith("daily_rank"):
                dial_note = f"target_vol_ann={vt_rank:.2f}"
        else:
            sc, scaled = dial_scale_is(net, is_end, max_dd_floor=args.max_dd_floor)
            dial_note = f"target_vol_ann={vt_don:.2f}; return_scale={sc:.2f}"

        is_k = kpis_from_net(scaled.loc[:is_end])
        oos_k = kpis_from_net(scaled.loc[cut:])
        daily = ftmo_daily_stats(scaled.loc[cut:])
        rows.append({
            "book": name,
            "dial": dial_note,
            "is_max_dd": is_k["max_dd"],
            "oos_sharpe": oos_k["sharpe"],
            "oos_cagr": oos_k["cagr"],
            "oos_max_dd": oos_k["max_dd"],
            "oos_pnl_100k": float(START_CAP * ((1.0 + scaled.loc[cut:]).prod() - 1.0)),
            "ftmo_static_10pct_ok_oos": bool(oos_k["max_dd"] > -FTMO_MAX_LOSS_PCT),
            **{f"oos_{k}": v for k, v in daily.items()},
        })

    ok = [
        r for r in rows
        if r["ftmo_static_10pct_ok_oos"] and r["oos_worst_daily_loss_pct"] > -FTMO_DAILY_LOSS_PCT
    ]
    ok.sort(key=lambda r: (-r["oos_cagr"], -r["oos_sharpe"]))
    weekly_ok = [r for r in ok if r["book"].startswith("weekly_rank")]
    primary = (
        weekly_ok[0]["book"]
        if weekly_ok
        else (ok[0]["book"] if ok else max(rows, key=lambda r: r["oos_sharpe"])["book"])
    )
    for r in rows:
        r["recommended_ftmo"] = r["book"] == primary

    rows.sort(key=lambda r: (-float(r["recommended_ftmo"]), -r["oos_sharpe"]))
    df = pd.DataFrame(rows)
    print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    payload = {
        "mandate": "FTMO_Swing_100K_proxy",
        "book_family": "crypto_donchian_vwap_only",
        "separate_from": "btc_qqq_gld_trio",
        "rules_proxy": {
            "max_loss_pct": FTMO_MAX_LOSS_PCT,
            "daily_loss_pct": FTMO_DAILY_LOSS_PCT,
            "is_max_dd_floor": args.max_dd_floor,
            "note": "Long-only trend + vol sizing; AVWAP gate; not symmetric long-vol/options.",
        },
        "universe_loaded": list(alts.keys()),
        "primary_book": primary,
        "weekly_rank3": {
            "top_k": 3,
            "rebalance_rule": base_vwap.rebalance_rule,
            "is_target_vol_ann": vt_k3,
        },
        "results": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
