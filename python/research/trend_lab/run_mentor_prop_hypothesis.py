"""CLI mirror of notebook 12 — mentor prop hypothesis board."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from research.trend_lab.allocation import blend_weights
from research.trend_lab.carver_book import (
    ANN_SESSIONS,
    BookParams,
    book_from_raw_weights,
    carver_weight_panel,
    pick_vol_target,
)
from research.trend_lab.data import DEFAULT_UNIVERSE, load_etf, load_symbol, mixed_panel
from research.trend_lab.donchian_combo import COST_BPS, equal_weight_portfolio
from research.trend_lab.donchian_nb08 import Donchian08Params, donchian_nb08_weight_panel
from research.trend_lab.metrics import kpis_from_net
from research.trend_lab.mentor_prop import (
    apply_gross_multiplier,
    canary_defensive_multiplier,
    days_to_profit_pct,
    dial_return_scale_is,
    ftmo_daily_stats,
    mentor_gated_weights,
)
from research.trend_lab.protocol import SPLIT, WARMUP_BARS
from research.trend_lab.spot_system import SpotParams, spot_signal

START_CAP = 100_000.0
FTMO_MAX_DD = -0.10
cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
is_end = cut - pd.Timedelta(days=1)
spot_p = SpotParams()


def eval_row(name: str, net: pd.Series, *, ledger: str, dial: bool = True) -> dict:
    net = net.fillna(0.0)
    sc, scaled = dial_return_scale_is(net, is_end) if dial else (1.0, net)
    oos = scaled.loc[cut:]
    k = kpis_from_net(oos)
    fd = ftmo_daily_stats(oos)
    return {
        "ledger": ledger,
        "book": name,
        "is_scale": sc,
        "oos_sharpe": k["sharpe"],
        "oos_cagr": k["cagr"],
        "oos_max_dd": k["max_dd"],
        "oos_pnl_100k": float(START_CAP * ((1 + oos).prod() - 1)),
        "oos_days_to_10pct": days_to_profit_pct(oos, 0.10),
        "ftmo_10pct_ok": k["max_dd"] > FTMO_MAX_DD,
        **fd,
    }


def main() -> None:
    symbols = ["BTCUSDT"] + [s for s in DEFAULT_UNIVERSE if s != "BTCUSDT"]
    ohlcv_c = {}
    for sym in symbols:
        df, _ = load_symbol(sym, "1d", start=date(2015, 1, 1))
        if len(df) >= WARMUP_BARS:
            ohlcv_c[sym] = df
    panel_c = pd.DataFrame({s: df["close"] for s, df in ohlcv_c.items()}).sort_index()
    w_car_c = carver_weight_panel(panel_c, use_cs=True, ann_days=365)
    flags_ens = pd.DataFrame(
        {s: spot_signal(ohlcv_c[s], spot_p)["signal"].reindex(panel_c.index).fillna(0) for s in panel_c.columns},
        index=panel_c.index,
    )
    w_don_c = donchian_nb08_weight_panel(ohlcv_c, Donchian08Params()).reindex(panel_c.index).fillna(0.0)
    flags_don = (w_don_c > 0.01).astype(float)

    def crypto_net(w: pd.DataFrame) -> pd.Series:
        return equal_weight_portfolio(w, panel_c, cost_bps=COST_BPS)

    books_c = {
        "carver_always_on": crypto_net(w_car_c),
        "mentor_ensemble_x_carver": crypto_net(mentor_gated_weights(w_car_c, flags_ens)),
        "mentor_donchian_x_carver": crypto_net(mentor_gated_weights(w_car_c, flags_don)),
        "blend_50_50_carver_don": crypto_net(
            pd.DataFrame({s: blend_weights(w_car_c[s], w_don_c[s], mix=0.5) for s in panel_c.columns}, index=panel_c.index)
        ),
    }
    rows_c = [eval_row(n, s, ledger="crypto") for n, s in books_c.items()]

    panel_t, src_t = mixed_panel()
    is_p = panel_t.loc[:is_end]
    raw_w_t = carver_weight_panel(panel_t, use_cs=True, ann_days=ANN_SESSIONS)
    picked = pick_vol_target(is_p, raw_w_t.reindex(is_p.index).fillna(0.0), lookback=60, top_n=2)
    params = BookParams(vol_target=picked["vol_target"], lookback=60, top_n=2, cost_bps=2.0)
    book_t = book_from_raw_weights(panel_t, raw_w_t, params)["net"]
    ohlcv_t = {
        c: pd.DataFrame(
            {"open": panel_t[c], "high": panel_t[c], "low": panel_t[c], "close": panel_t[c], "volume": 1.0},
            index=panel_t.index,
        )
        for c in panel_t.columns
    }
    flags_t = pd.DataFrame(
        {c: spot_signal(ohlcv_t[c], spot_p)["signal"].reindex(panel_t.index).fillna(0) for c in panel_t.columns},
        index=panel_t.index,
    )
    w_car_t = raw_w_t.reindex(panel_t.index).fillna(0.0)
    net_gate_t = equal_weight_portfolio(mentor_gated_weights(w_car_t, flags_t), panel_t, cost_bps=2.0)
    rows_t = [
        eval_row("trio_ranked_carver", book_t, ledger="trio"),
        eval_row("trio_mentor_ensemble_x_carver", net_gate_t, ledger="trio"),
    ]

    spy, _ = load_etf("SPY")
    qqq, _ = load_etf("QQQ")
    xlu, _ = load_etf("XLU")
    mult = canary_defensive_multiplier(spy, qqq, xlu).reindex(panel_t.index).ffill().fillna(1.0)
    net_canary = equal_weight_portfolio(apply_gross_multiplier(w_car_t, mult), panel_t, cost_bps=2.0)
    row_can = eval_row("trio_carver_x_canary", net_canary, ledger="trio")

    tbl_c = pd.DataFrame(rows_c)
    h1 = (
        tbl_c.loc[tbl_c["book"] == "carver_always_on", "oos_max_dd"].iloc[0]
        > tbl_c.loc[tbl_c["book"] == "mentor_ensemble_x_carver", "oos_max_dd"].iloc[0]
    )
    h4 = row_can["oos_max_dd"] > rows_t[0]["oos_max_dd"]

    board = pd.DataFrame(rows_c + rows_t + [row_can])
    board["recommended_prop"] = board["ftmo_10pct_ok"] & (board["worst_daily_loss_pct"] > -0.05)
    print(board.sort_values(["recommended_prop", "oos_cagr"], ascending=[False, False]).to_string(index=False))

    out = Path("/opt/cursor/artifacts/mentor_prop_hypothesis.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mentor_model": "ensemble_or_donchian_flag_x_carver_size",
        "hypotheses": {"H1_ensemble_gate_dd": bool(h1), "H4_canary_dd": bool(h4)},
        "ledgers_separate": ["crypto", "trio"],
        "sources_trio": src_t,
        "results": board.to_dict(orient="records"),
    }
    out.write_text(json.dumps(payload, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
