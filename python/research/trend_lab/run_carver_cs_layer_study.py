"""Cross-sectional Carver layer: CS on vs off by bucket (research only).

Mirrors ``carver_engine_with_cross_sectional`` / mentor Price Action notebook:
relative normalized-price momentum (PN, group mean A, R), FDM blend, long-only.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from research.trend_lab.carver import backtest, full_carver
from research.trend_lab.carver_book import ANN_SESSIONS, BookParams, book_from_raw_weights, carver_weight_panel
from research.trend_lab.data import load_etf, load_panel, mixed_panel
from research.trend_lab.metrics import kpis_from_net
from research.trend_lab.protocol import SPLIT

cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
is_end = cut - pd.Timedelta(days=1)


def _load_etf_panel(tickers: list[str], start: date) -> tuple[pd.DataFrame, dict[str, str]]:
    closes: dict[str, pd.Series] = {}
    src: dict[str, str] = {}
    for t in tickers:
        s, origin = load_etf(t)
        s = s.loc[s.index >= pd.Timestamp(start, tz="UTC")]
        closes[t] = s
        src[t] = origin
    panel = pd.concat(closes.values(), axis=1).sort_index().ffill().dropna(how="any")
    return panel, src


def _avg_corr(panel: pd.DataFrame, *, lookback: int = 60) -> float:
    rets = panel.pct_change(fill_method=None).fillna(0.0)
    if len(rets) < lookback + 5:
        return float("nan")
    c = rets.iloc[-lookback:].corr().values
    n = c.shape[0]
    if n < 2:
        return float("nan")
    off = c[~np.eye(n, dtype=bool)]
    return float(np.nanmean(off))


def _single_asset_rows(panel: pd.DataFrame, target: str, *, ann: int, label: str) -> list[dict]:
    rows = []
    for use_cs in (False, True):
        w, fc, fdm = full_carver(
            panel, target, use_cs=use_cs and panel.shape[1] >= 3, ann_days=ann,
        )
        bt = backtest(panel[target], w)
        for sl, tag in [(slice(None, is_end), "IS"), (slice(cut, None), "OOS")]:
            k = kpis_from_net(bt["net"].loc[sl], ann=ann)
            rows.append({
                "bucket": label,
                "target": target,
                "use_cs": use_cs,
                "slice": tag,
                "fdm": float(fdm),
                "weight_mean_abs_delta_vs_no_cs": float("nan"),
                **k,
            })
    w_off, _, _ = full_carver(panel, target, use_cs=False, ann_days=ann)
    w_on, _, fdm_on = full_carver(panel, target, use_cs=True, ann_days=ann)
    d = (w_on - w_off).abs().mean()
    for r in rows:
        if r["use_cs"]:
            r["weight_mean_abs_delta_vs_no_cs"] = float(d)
            r["fdm"] = float(fdm_on)
    return rows


def _book_rows(panel: pd.DataFrame, *, ann: int, label: str, vol_target: float = 0.12) -> list[dict]:
    rows = []
    p = BookParams(vol_target=vol_target, lookback=60, top_n=min(3, panel.shape[1]), cost_bps=2.0)
    for use_cs in (False, True):
        raw = carver_weight_panel(panel, use_cs=use_cs, ann_days=ann)
        book = book_from_raw_weights(panel, raw, p)
        for sl, tag in [(slice(None, is_end), "IS"), (slice(cut, None), "OOS")]:
            k = kpis_from_net(book["net"].loc[sl], ann=ann)
            rows.append({
                "bucket": label,
                "book": "ranked_carver_top3",
                "use_cs": use_cs,
                "slice": tag,
                **k,
            })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--out", default="/opt/cursor/artifacts/carver_cs_layer_study.json")
    args = ap.parse_args()
    start = date.fromisoformat(args.start)

    buckets: dict[str, tuple[pd.DataFrame, int, str]] = {}

    panel_t, src_t = mixed_panel()
    panel_t = panel_t.loc[panel_t.index >= pd.Timestamp(start, tz="UTC")]
    buckets["trio_BTC_QQQ_GLD"] = (panel_t, ANN_SESSIONS, json.dumps(src_t))

    spy = load_etf("SPY")[0]
    qqq = load_etf("QQQ")[0]
    btc = panel_t["BTC"].rename("BTC") if "BTC" in panel_t.columns else None
    if btc is not None:
        idx = spy.index.intersection(qqq.index).intersection(btc.index)
        idx = idx[idx >= pd.Timestamp(start, tz="UTC")]
        buckets["high_corr_SPY_QQQ_BTC"] = (
            pd.DataFrame({"SPY": spy.reindex(idx), "QQQ": qqq.reindex(idx), "BTC": btc.reindex(idx)}).dropna(how="any"),
            ANN_SESSIONS,
            "SPY/QQQ yahoo+stooq; BTC native",
        )

    try:
        sub, sub_src = _load_etf_panel(["SMH", "BOTZ", "GLD"], start)
        buckets["subsector_SMH_BOTZ_GLD"] = (sub, ANN_SESSIONS, json.dumps(sub_src))
    except Exception as exc:
        sub = None
        print("subsector bucket skip:", exc)

    crypto_syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT", "ADAUSDT"]
    panel_c, src_c = load_panel(crypto_syms, "1d", start=start)
    panel_c = panel_c.dropna(how="any")
    if panel_c.shape[1] >= 3:
        buckets["crypto_6"] = (panel_c, 365, json.dumps(src_c))

    meta = []
    single_rows: list[dict] = []
    book_rows: list[dict] = []

    for label, (panel, ann, sources) in buckets.items():
        if panel.shape[0] < 400 or panel.shape[1] < 2:
            continue
        meta.append({
            "bucket": label,
            "sources": sources,
            "n_assets": int(panel.shape[1]),
            "bars": int(panel.shape[0]),
            "avg_corr_60d_oos": _avg_corr(panel.loc[cut:]),
            "avg_corr_60d_full": _avg_corr(panel),
        })
        tgt = panel.columns[0]
        single_rows.extend(_single_asset_rows(panel, tgt, ann=ann, label=label))
        if panel.shape[1] >= 3:
            single_rows.extend(_single_asset_rows(panel, panel.columns[1], ann=ann, label=label))
        book_rows.extend(_book_rows(panel, ann=ann, label=label))

    # OOS delta summary per bucket (first target only)
    deltas = []
    for m in meta:
        lab = m["bucket"]
        oos_off = next(r for r in single_rows if r["bucket"] == lab and r["slice"] == "OOS" and r["use_cs"] is False and r["target"] == buckets[lab][0].columns[0])
        oos_on = next(r for r in single_rows if r["bucket"] == lab and r["slice"] == "OOS" and r["use_cs"] is True and r["target"] == buckets[lab][0].columns[0])
        deltas.append({
            "bucket": lab,
            "target": oos_off["target"],
            "avg_corr_60d_oos": m["avg_corr_60d_oos"],
            "oos_sharpe_delta_cs_minus_no_cs": float(oos_on["sharpe"] - oos_off["sharpe"]),
            "oos_max_dd_delta": float(oos_on["max_dd"] - oos_off["max_dd"]),
            "oos_cagr_delta": float(oos_on["cagr"] - oos_off["cagr"]),
            "mean_abs_weight_delta": float(oos_on["weight_mean_abs_delta_vs_no_cs"]),
            "fdm_with_cs": float(oos_on["fdm"]),
        })

    payload = {
        "protocol": {"is_end": str(is_end.date()), "oos_start": str(cut.date())},
        "note": "CS requires panel.shape[1]>=3; horizons in carver.py cs_momentum_forecast default (40,80).",
        "buckets": meta,
        "oos_cs_impact": deltas,
        "single_asset": single_rows,
        "book": book_rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    print(json.dumps({"buckets": meta, "oos_cs_impact": deltas}, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    main()
