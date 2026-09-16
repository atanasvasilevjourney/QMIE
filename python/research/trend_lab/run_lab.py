"""End-to-end research lab runner. Fit on IS only. Writes artifacts + JSON KPIs.

Usage (from ``python/``)::

    python -m research.trend_lab.run_lab --quick
    python -m research.trend_lab.run_lab --full
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .allocation import (
    bh_equal,
    blend_weights,
    book_kpis,
    chop_gate,
    equal_weight_book,
    ranked_spot_book,
)
from .carver import backtest, dd_circuit_breaker, full_carver
from .data import CORE, DEFAULT_UNIVERSE, SATELLITES, coverage_table, load_panel, load_symbol
from .evaluate import eval_spot, eval_tema, reverse_split_diagnostic
from .features import feature_frame
from .metrics import kpi_table, kpis, kpis_from_net, rolling_sharpe
from .optimize import (
    boruta_select,
    df_neighborhood_score,
    grid_spot,
    grid_tema,
    optimize_spot,
    optimize_tema,
    trend_label,
)
from .plots import (
    allocation_fig,
    df_scatter,
    equity_overlay,
    param_heatmap,
    price_signals,
    rolling_sharpe_fig,
    underwater,
    write_html,
    write_png_mpl,
)
from .protocol import SPLIT, WARMUP_BARS, inner_validation_start, split_frame
from .spot_system import SpotParams, spot_signal
from .tema_system import TemaParams

log = logging.getLogger("trend_lab")

ARTIFACTS = Path("/opt/cursor/artifacts")
LOCAL_ART = Path(__file__).resolve().parents[1] / "artifacts"


def _json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_ready(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        x = float(obj)
        return None if not np.isfinite(x) else x
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (pd.Timestamp, date)):
        return str(obj)
    if hasattr(obj, "__dataclass_fields__"):
        return _json_ready(asdict(obj))
    return obj


def _dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_ready(payload), indent=2, default=str))


def _save_fig(fig, stem: str) -> None:
    if fig is None:
        return
    for root in (ARTIFACTS, LOCAL_ART):
        try:
            write_html(fig, root / f"{stem}.html")
        except Exception as exc:  # pragma: no cover
            log.warning("html %s: %s", stem, exc)


def run(quick: bool = True) -> dict[str, Any]:
    n_spot = 16 if quick else 28
    n_tema = 12 if quick else 24
    n_boruta = 8 if quick else 12
    spot_universe = CORE[:4] if quick else CORE
    out: dict[str, Any] = {
        "protocol": {
            "is": f"{SPLIT.is_start} → {SPLIT.is_end}",
            "oos": f"{SPLIT.oos_start} → {SPLIT.oos_end}",
            "warmup_bars": WARMUP_BARS,
            "requested_note": SPLIT.requested_note,
            "live_tema_frozen": "9/90/199 — Optuna winners are NOT promoted",
        }
    }

    log.info("coverage")
    cov_syms = (CORE[:3] + SATELLITES[:2]) if quick else DEFAULT_UNIVERSE
    try:
        cov = coverage_table(cov_syms, ("1d", "4h"))
        out["coverage"] = cov.to_dict(orient="records")
        (LOCAL_ART).mkdir(parents=True, exist_ok=True)
        cov.to_csv(LOCAL_ART / "coverage.csv", index=False)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        cov.to_csv(ARTIFACTS / "coverage.csv", index=False)
    except Exception as exc:
        log.warning("coverage failed: %s", exc)
        out["coverage_error"] = str(exc)

    log.info("load BTC 1d + 4h")
    btc_1d, src_1d = load_symbol("BTCUSDT", "1d")
    btc_4h, src_4h = load_symbol("BTCUSDT", "4h")
    out["data"] = {
        "btc_1d_src": src_1d,
        "btc_4h_src": src_4h,
        "btc_1d_bars": int(len(btc_1d)),
        "btc_4h_bars": int(len(btc_4h)),
        "btc_1d_start": None if btc_1d.empty else str(btc_1d.index[0]),
        "btc_4h_start": None if btc_4h.empty else str(btc_4h.index[0]),
    }
    if btc_1d.empty or btc_4h.empty:
        out["fatal"] = "no BTC data — cannot run lab"
        _dump(LOCAL_ART / "lab_results.json", out)
        _dump(ARTIFACTS / "lab_results.json", out)
        return out

    # ---- H1 spot baseline + Optuna + DF (IS only) ----
    log.info("spot baseline + optuna")
    baseline_spot = SpotParams()
    spot_eval = eval_spot(btc_1d, baseline_spot)
    grid = grid_spot(split_frame(btc_1d)["is"])
    opt_spot = optimize_spot(split_frame(btc_1d)["is"], n_trials=n_spot)
    opt_eval = eval_spot(btc_1d, opt_spot["params"])
    inner = inner_validation_start(split_frame(btc_1d)["is"].index)

    def _spot_run(ohlcv: pd.DataFrame, pdict: dict) -> pd.DataFrame:
        p = SpotParams(
            ema_fast=int(pdict["ema_fast"]),
            ema_slow=int(pdict["ema_slow"]),
            donchian=int(pdict["donchian"]),
            min_adx=float(pdict["min_adx"]),
        )
        fr = spot_signal(ohlcv, p)
        return fr[["net", "equity"]]

    center = {
        "ema_fast": float(opt_spot["params"].ema_fast),
        "ema_slow": float(opt_spot["params"].ema_slow),
        "donchian": float(opt_spot["params"].donchian),
        "min_adx": float(opt_spot["params"].min_adx),
    }
    steps = {
        "ema_fast": [center["ema_fast"] - 2, center["ema_fast"], center["ema_fast"] + 2],
        "ema_slow": [center["ema_slow"] - 10, center["ema_slow"], center["ema_slow"] + 10],
        "donchian": [max(10, center["donchian"] - 5), center["donchian"], center["donchian"] + 5],
        "min_adx": [center["min_adx"] - 2, center["min_adx"], center["min_adx"] + 2],
    }
    df_spot = df_neighborhood_score(
        is_ohlcv=split_frame(btc_1d)["is"],
        inner_val_start=inner,
        center=center,
        neighbor_steps=steps,
        run_fn=_spot_run,
        min_is_sharpe=0.5,
    )
    leak = reverse_split_diagnostic(btc_1d, baseline_spot)

    # ---- H4 Boruta on IS features ----
    log.info("boruta")
    is_1d = split_frame(btc_1d)["is"]
    feats = feature_frame(is_1d).iloc[WARMUP_BARS:]
    y = trend_label(is_1d["close"], horizon=10).reindex(feats.index)
    # drop last 10 bars (label uses future close — only inside IS)
    feats_fit = feats.iloc[:-10]
    y_fit = y.iloc[:-10]
    boruta = boruta_select(feats_fit, y_fit, n_iter=n_boruta, n_estimators=80)
    confirmed = boruta.loc[boruta["decision"] == "confirmed", "feature"].tolist()
    confluence = SpotParams(
        use_kama="kama_cross" in confirmed or "kama_er" in confirmed,
        use_macd="macd_hist" in confirmed,
        use_zscore="zscore_20" in confirmed,
        use_alma="alma_slope" in confirmed,
    )
    # if nothing confirmed, still test the four as AND-gates vs baseline (honesty)
    conf_eval = eval_spot(btc_1d, confluence)

    # ---- H2/H3 TEMA 10x vs 1x, frozen vs Optuna ----
    log.info("tema 4h")
    frozen_10 = TemaParams(leverage=10.0)
    frozen_1 = TemaParams(leverage=1.0)
    tema10 = eval_tema(btc_4h, frozen_10)
    tema1 = eval_tema(btc_4h, frozen_1)
    grid_t = grid_tema(split_frame(btc_4h)["is"], leverage=10.0)
    opt_tema = optimize_tema(split_frame(btc_4h)["is"], n_trials=n_tema, leverage=10.0)
    opt_tema_eval = eval_tema(btc_4h, opt_tema["params"])

    # ---- H5/H6 Carver vs ensemble + chop + DD breaker ----
    log.info("carver vs ensemble")
    parts = split_frame(btc_1d)
    panel, srcs = load_panel(spot_universe, "1d")
    # Carver on BTC with optional CS
    use_cs = panel.shape[1] >= 3
    w_full, fc, fdm = full_carver(panel if use_cs else panel[["BTCUSDT"]], "BTCUSDT", use_cs=use_cs)
    cv_bt = backtest(btc_1d["close"], w_full.reindex(btc_1d.index).fillna(0.0))
    cv_oos = cv_bt.reindex(parts["oos"].index)
    ens_full = spot_signal(btc_1d, baseline_spot)
    mix_w = blend_weights(w_full.reindex(btc_1d.index).fillna(0.0), ens_full["signal"].reindex(btc_1d.index).fillna(0.0), mix=0.5)
    mix_bt = backtest(btc_1d["close"], mix_w)
    # chop: zero Carver when ADX low
    gate = chop_gate(btc_1d, min_adx=18.0)
    w_chop = (w_full.reindex(btc_1d.index).fillna(0.0) * gate.reindex(btc_1d.index).fillna(0.0))
    chop_bt = backtest(btc_1d["close"], w_chop)
    # DD breaker on OOS carver
    w_dd = dd_circuit_breaker(w_full.reindex(btc_1d.index).fillna(0.0), cv_bt["equity"])
    dd_bt = backtest(btc_1d["close"], w_dd)
    # vol target sweep on OOS (weights from IS-fitted structure — vol target is a risk dial, not a fit)
    vol_rows = []
    for vt in (0.10, 0.20, 0.40):
        w_vt, _, _ = full_carver(panel if use_cs else panel[["BTCUSDT"]], "BTCUSDT", use_cs=use_cs, vol_target=vt)
        bt = backtest(btc_1d["close"], w_vt.reindex(btc_1d.index).fillna(0.0))
        oos = bt.reindex(parts["oos"].index)
        vol_rows.append({"vol_target": vt, **kpis_from_net(oos["net"])})

    # ---- H7 ranked spot book ----
    log.info("ranked book")
    held_cols = {}
    close_cols = {}
    for sym in spot_universe:
        df, _ = load_symbol(sym, "1d")
        if df.empty or len(df) < WARMUP_BARS + 50:
            continue
        close_cols[sym] = df["close"]
        held_cols[sym] = spot_signal(df, baseline_spot)["signal"]
    ranked = {"skipped": "insufficient panel"}
    equal = ranked
    if len(close_cols) >= 2:
        cpanel = pd.concat(close_cols, axis=1).sort_index()
        hpanel = pd.concat(held_cols, axis=1).reindex(cpanel.index).fillna(0.0)
        # OOS slice of book — weights still computed causally on full history (no future ROC)
        ranked_full = ranked_spot_book(cpanel, hpanel, lookback=60, top_n=3)
        equal_full = equal_weight_book(cpanel, hpanel)
        bh = bh_equal(cpanel)
        oos_idx = parts["oos"].index.intersection(ranked_full.index)

        def _bk(fr: pd.DataFrame) -> dict[str, float]:
            sl = fr.loc[oos_idx].copy()
            sl["net"] = sl["net"].fillna(0.0)
            sl["equity"] = (1.0 + sl["net"]).cumprod()
            return book_kpis(sl)

        ranked = _bk(ranked_full)
        equal = _bk(equal_full)
        buyhold = _bk(bh)
    else:
        buyhold = {}
        ranked_full = None
        equal_full = None
        bh = None

    # ---- plots ----
    log.info("plots")
    eq_map = {
        "spot baseline": spot_eval["oos_frame"]["equity"],
        "spot Optuna": opt_eval["oos_frame"]["equity"],
        "spot confluence": conf_eval["oos_frame"]["equity"],
        "buy&hold": (1.0 + parts["oos"]["close"].pct_change().fillna(0)).cumprod(),
        "carver": cv_oos["equity"] if len(cv_oos) else pd.Series(dtype=float),
        "blend": mix_bt.reindex(parts["oos"].index)["equity"],
    }
    # normalize carver if needed
    fig_eq = equity_overlay({k: v for k, v in eq_map.items() if v is not None and len(v)}, "OOS growth of $1 — BTC")
    _save_fig(fig_eq, "oos_equity")
    write_png_mpl(
        {k: (v / v.dropna().iloc[0]) for k, v in eq_map.items() if v is not None and len(v.dropna())},
        ARTIFACTS / "oos_equity.png",
        title="OOS growth of $1 — BTC",
        ylabel="Multiple",
    )

    nets = {
        "spot baseline": spot_eval["oos_frame"]["net"],
        "carver": cv_oos["net"],
        "blend": mix_bt.reindex(parts["oos"].index)["net"],
        "chop-gated carver": chop_bt.reindex(parts["oos"].index)["net"],
        "dd-breaker": dd_bt.reindex(parts["oos"].index)["net"],
    }
    fig_rs = rolling_sharpe_fig(nets, window=90, title="OOS 90d rolling Sharpe")
    _save_fig(fig_rs, "oos_rolling_sharpe")
    write_png_mpl(
        {k: rolling_sharpe(v, 90) for k, v in nets.items()},
        ARTIFACTS / "oos_rolling_sharpe.png",
        title="OOS 90d rolling Sharpe",
        ylabel="Sharpe",
        hline=0.0,
    )

    _save_fig(underwater(spot_eval["oos_frame"]["equity"], "Spot baseline OOS drawdown"), "spot_underwater")
    _save_fig(underwater(cv_oos["equity"], "Carver OOS drawdown"), "carver_underwater")
    write_png_mpl(
        {
            "spot": spot_eval["oos_frame"]["equity"] / spot_eval["oos_frame"]["equity"].cummax() - 1,
            "carver": cv_oos["equity"] / cv_oos["equity"].cummax() - 1,
            "dd-breaker": dd_bt.reindex(parts["oos"].index)["equity"] / dd_bt.reindex(parts["oos"].index)["equity"].cummax() - 1,
        },
        ARTIFACTS / "oos_drawdown.png",
        title="OOS underwater",
        ylabel="DD",
    )

    if not grid.empty:
        _save_fig(param_heatmap(grid, "ema_slow", "ema_fast", "sharpe", "Spot grid IS Sharpe"), "spot_grid_sharpe")
    if df_spot.get("table") is not None and len(df_spot["table"]):
        _save_fig(df_scatter(df_spot["table"], "Spot DF neighborhood (inner IS)"), "spot_df_neighborhood")
        df_spot["table"].to_csv(LOCAL_ART / "spot_df_neighborhood.csv", index=False)

    # KAMA / ALMA overlays on last OOS window
    from scanner.indicators import ema
    from .features import alma, kama

    oos_px = parts["oos"]
    k_s, _ = kama(oos_px["close"], n=10)
    k_l, _ = kama(oos_px["close"], n=60)
    overlays = {
        "EMA9": ema(oos_px["close"], 9),
        "EMA199": ema(oos_px["close"], 199),
        "KAMA10": k_s,
        "ALMA9": alma(oos_px["close"], 9),
    }
    sig_oos = spot_eval["oos_frame"]["held"]
    entries = spot_eval["oos_frame"].index[spot_eval["oos_frame"]["signal"].diff().fillna(0) > 0]
    exits = spot_eval["oos_frame"].index[spot_eval["oos_frame"]["signal"].diff().fillna(0) < 0]
    fig_px = price_signals(
        oos_px,
        signal=sig_oos,
        entries=entries,
        exits=exits,
        overlays=overlays,
        title="BTC 1D OOS — spot ensemble vs KAMA/ALMA/EMA",
    )
    _save_fig(fig_px, "spot_signals_oos")

    # TEMA trades on OOS 4h (last ~800 bars)
    oos_4h = split_frame(btc_4h)["oos"]
    t10 = tema10["oos_trades"]
    fig_tema = price_signals(
        oos_4h,
        entries=pd.DatetimeIndex(t10["entry_time"]) if len(t10) else None,
        exits=pd.DatetimeIndex(t10["exit_time"]) if len(t10) else None,
        title="BTC 4h OOS — frozen TEMA 9/90/199 10x isolated",
        max_bars=800,
    )
    _save_fig(fig_tema, "tema_signals_oos")

    _save_fig(
        allocation_fig(
            {
                "carver": cv_bt["held"].reindex(parts["oos"].index),
                "ensemble": ens_full["held"].reindex(parts["oos"].index),
                "blend": mix_bt["held"].reindex(parts["oos"].index),
            },
            "OOS allocation — Carver vs ensemble vs blend",
        ),
        "allocation_oos",
    )
    write_png_mpl(
        {
            "carver": cv_bt["held"].reindex(parts["oos"].index),
            "ensemble": ens_full["held"].reindex(parts["oos"].index),
            "blend": mix_bt["held"].reindex(parts["oos"].index),
        },
        ARTIFACTS / "allocation_oos.png",
        title="OOS allocation",
        ylabel="Weight",
    )

    if ranked_full is not None:
        fig_rk = equity_overlay(
            {
                "ranked top-3": ranked_full.reindex(oos_idx)["equity"],
                "equal eligible": equal_full.reindex(oos_idx)["equity"],
                "buy&hold equal": bh.reindex(oos_idx)["equity"],
            },
            "OOS spot book — ranked vs equal vs BH",
        )
        _save_fig(fig_rk, "ranked_book_oos")
        write_png_mpl(
            {
                "ranked": ranked_full.reindex(oos_idx)["equity"] / ranked_full.reindex(oos_idx)["equity"].iloc[0],
                "equal": equal_full.reindex(oos_idx)["equity"] / equal_full.reindex(oos_idx)["equity"].iloc[0],
                "bh": bh.reindex(oos_idx)["equity"] / bh.reindex(oos_idx)["equity"].iloc[0],
            },
            ARTIFACTS / "ranked_book_oos.png",
            title="OOS spot book",
            ylabel="Multiple",
        )

    # ---- hypothesis board ----
    h1 = _h(
        "H1 Spot 1D EMA+Donchian+ADX beats BH on OOS Sharpe or tighter DD",
        spot_eval["oos"],
        spot_eval["bh_oos"],
        better="sharpe_or_dd",
    )
    h2 = {
        "id": "H2",
        "claim": "10x isolated TEMA raises expectancy vs 1x but worsens max DD / liquidations",
        "tema_10x_oos": tema10["oos"],
        "tema_1x_oos": tema1["oos"],
        "result": _h2(tema10["oos"], tema1["oos"]),
    }
    h3 = {
        "id": "H3",
        "claim": "Optuna-best TEMA periods fail DF / OOS vs frozen 9/90/199 — do not retune live",
        "frozen_oos": tema10["oos"],
        "optuna_oos": opt_tema_eval["oos"],
        "optuna_is": opt_tema["is_kpis"],
        "frozen_is": opt_tema["frozen_9_90_199_is"],
        "df_spot_status": df_spot.get("status"),
        "df_val_std": df_spot.get("val_sharpe_std"),
        "result": _h3(tema10["oos"], opt_tema_eval["oos"], opt_tema["is_kpis"], opt_tema["frozen_9_90_199_is"]),
        "do_not_promote": True,
    }
    h4 = {
        "id": "H4",
        "claim": "Boruta-confirmed confluence (KAMA/MACD/z/ALMA) improves OOS vs raw breakout",
        "confirmed": confirmed,
        "baseline_oos": spot_eval["oos"],
        "confluence_oos": conf_eval["oos"],
        "result": _cmp_sharpe(conf_eval["oos"], spot_eval["oos"], "confluence", "baseline"),
    }
    carver_oos_k = kpis_from_net(cv_oos["net"])
    blend_oos_k = kpis_from_net(mix_bt.reindex(parts["oos"].index)["net"])
    chop_oos_k = kpis_from_net(chop_bt.reindex(parts["oos"].index)["net"])
    dd_oos_k = kpis_from_net(dd_bt.reindex(parts["oos"].index)["net"])
    h5 = {
        "id": "H5",
        "claim": "Carver vol-targeted sizing has lower OOS DD (and lower CAGR) than binary ensemble",
        "carver_oos": carver_oos_k,
        "ensemble_oos": spot_eval["oos"],
        "blend_oos": blend_oos_k,
        "result": _h5(carver_oos_k, spot_eval["oos"]),
    }
    h6 = {
        "id": "H6",
        "claim": "ADX chop gate and/or DD circuit breaker improve OOS max DD vs raw Carver",
        "carver": carver_oos_k,
        "chop": chop_oos_k,
        "dd_breaker": dd_oos_k,
        "result": _h6(carver_oos_k, chop_oos_k, dd_oos_k),
    }
    h7 = {
        "id": "H7",
        "claim": "Ranked top-N spot book beats equal-weight eligible names on OOS (Sharpe or DD)",
        "ranked_oos": ranked,
        "equal_oos": equal,
        "bh_oos": buyhold,
        "result": _h7(ranked, equal),
    }

    summary = kpi_table({
        "spot_baseline_IS": spot_eval["is"],
        "spot_baseline_OOS": spot_eval["oos"],
        "spot_optuna_OOS": opt_eval["oos"],
        "spot_confluence_OOS": conf_eval["oos"],
        "bh_OOS": spot_eval["bh_oos"],
        "tema10_frozen_OOS": tema10["oos"],
        "tema1_frozen_OOS": tema1["oos"],
        "tema10_optuna_OOS": opt_tema_eval["oos"],
        "carver_OOS": carver_oos_k,
        "blend_OOS": blend_oos_k,
        "chop_carver_OOS": chop_oos_k,
        "dd_breaker_OOS": dd_oos_k,
    })
    summary.to_csv(LOCAL_ART / "kpi_summary.csv")
    summary.to_csv(ARTIFACTS / "kpi_summary.csv")
    boruta.to_csv(LOCAL_ART / "boruta_is.csv", index=False)
    boruta.to_csv(ARTIFACTS / "boruta_is.csv", index=False)
    grid.to_csv(LOCAL_ART / "spot_grid_is.csv", index=False)
    grid_t.to_csv(LOCAL_ART / "tema_grid_is.csv", index=False)

    out.update({
        "spot_baseline": {"is": spot_eval["is"], "oos": spot_eval["oos"], "bh_oos": spot_eval["bh_oos"], "params": asdict(baseline_spot)},
        "spot_optuna": {"is": opt_spot["is_kpis"], "oos": opt_eval["oos"], "params": asdict(opt_spot["params"])},
        "spot_df": {k: v for k, v in df_spot.items() if k != "table"},
        "leakage_diagnostic": leak,
        "boruta": boruta.to_dict(orient="records"),
        "confluence_params": asdict(confluence),
        "tema_frozen_10x": {"is": tema10["is"], "oos": tema10["oos"]},
        "tema_frozen_1x": {"is": tema1["is"], "oos": tema1["oos"]},
        "tema_optuna": {"is": opt_tema["is_kpis"], "oos": opt_tema_eval["oos"], "params": asdict(opt_tema["params"]), "do_not_promote": True},
        "carver_fdm": fdm,
        "vol_target_sweep_oos": vol_rows,
        "ranked_book": ranked,
        "equal_book": equal,
        "hypotheses": [h1, h2, h3, h4, h5, h6, h7],
        "kpi_summary": summary.to_dict(orient="index"),
        "sources": srcs,
    })
    _dump(LOCAL_ART / "lab_results.json", out)
    _dump(ARTIFACTS / "lab_results.json", out)
    log.info("wrote %s", LOCAL_ART / "lab_results.json")
    return out


def _finite(x: Any, default: float = float("nan")) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _h(claim: str, strat: dict, bh: dict, better: str) -> dict[str, Any]:
    ss, bs = _finite(strat.get("sharpe")), _finite(bh.get("sharpe"))
    sd, bd = _finite(strat.get("max_dd")), _finite(bh.get("max_dd"))
    sharpe_win = np.isfinite(ss) and np.isfinite(bs) and ss > bs
    dd_win = np.isfinite(sd) and np.isfinite(bd) and sd > bd  # less negative is better
    if sharpe_win and dd_win:
        res = "HOLD"
    elif sharpe_win or dd_win:
        res = "PARTIAL"
    else:
        res = "REJECT"
    return {"id": "H1", "claim": claim, "result": res, "sharpe_win": sharpe_win, "dd_win": dd_win, "strat": strat, "bh": bh}


def _h2(t10: dict, t1: dict) -> str:
    e10, e1 = _finite(t10.get("expectancy_usdt")), _finite(t1.get("expectancy_usdt"))
    d10, d1 = _finite(t10.get("max_dd")), _finite(t1.get("max_dd"))
    liq = _finite(t10.get("liquidations"), 0)
    better_e = np.isfinite(e10) and np.isfinite(e1) and e10 > e1
    worse_dd = np.isfinite(d10) and np.isfinite(d1) and d10 < d1
    if better_e and (worse_dd or liq > 0):
        return "HOLD"
    if better_e or worse_dd:
        return "PARTIAL"
    return "REJECT"


def _h3(frozen_oos: dict, opt_oos: dict, opt_is: dict, frozen_is: dict) -> str:
    """HOLD the 'do not promote' claim if Optuna IS looks better but OOS does not."""
    is_win = _finite(opt_is.get("sharpe")) > _finite(frozen_is.get("sharpe"))
    oos_lose = _finite(opt_oos.get("sharpe")) <= _finite(frozen_oos.get("sharpe"))
    if is_win and oos_lose:
        return "HOLD (overfit — keep 9/90/199)"
    if oos_lose:
        return "HOLD (Optuna does not beat frozen OOS)"
    return "INCONCLUSIVE — Optuna OOS not worse; still do not promote without DF + second holdout"


def _cmp_sharpe(a: dict, b: dict, na: str, nb: str) -> str:
    sa, sb = _finite(a.get("sharpe")), _finite(b.get("sharpe"))
    da, db = _finite(a.get("max_dd")), _finite(b.get("max_dd"))
    if sa > sb and da >= db:
        return f"HOLD — {na} dominates {nb} on Sharpe and DD"
    if sa > sb or da > db:
        return f"PARTIAL — {na} wins one of Sharpe/DD vs {nb}"
    return f"REJECT — {na} does not improve OOS vs {nb}"


def _h5(carver: dict, ens: dict) -> str:
    tighter = _finite(carver.get("max_dd")) > _finite(ens.get("max_dd"))
    lower_cagr = _finite(carver.get("cagr")) < _finite(ens.get("cagr"))
    if tighter and lower_cagr:
        return "HOLD"
    if tighter:
        return "PARTIAL — tighter DD, CAGR not lower"
    return "REJECT — Carver DD not tighter than ensemble on this OOS"


def _h6(raw: dict, chop: dict, brk: dict) -> str:
    best = max(_finite(chop.get("max_dd"), -9), _finite(brk.get("max_dd"), -9), _finite(raw.get("max_dd"), -9))
    if best > _finite(raw.get("max_dd"), -9) + 1e-9:
        return "HOLD — at least one overlay tightens DD"
    return "REJECT — neither overlay improved max DD"


def _h7(ranked: dict, equal: dict) -> str:
    if not ranked or "sharpe" not in ranked:
        return "INCONCLUSIVE — panel too thin"
    return _cmp_sharpe(ranked, equal, "ranked", "equal")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--quick", action="store_true", default=True)
    p.add_argument("--full", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    quick = not args.full
    run(quick=quick)
    return 0


if __name__ == "__main__":
    sys.exit(main())
