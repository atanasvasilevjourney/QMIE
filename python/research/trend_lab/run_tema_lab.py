"""TEMA-only lab: validation, robustness, Carver sizing.

Usage (from ``python/``)::

    python -m research.trend_lab.run_tema_lab
    python -m research.trend_lab.run_tema_lab --full
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

from .carver import VOL_TARGET
from .data import load_symbol
from .evaluate import eval_tema
from .metrics import kpi_table
from .optimize import optimize_tema
from .plots import (
    df_scatter,
    equity_overlay,
    param_heatmap,
    price_signals,
    rolling_sharpe_fig,
    underwater,
    write_html,
    write_png_mpl,
)
from .protocol import SPLIT, WARMUP_BARS, split_frame
from .tema_carver import overlay_pack
from .tema_robust import (
    FROZEN,
    daily_kpis,
    frozen_neighborhood,
    sensitivity_gates,
    sensitivity_periods,
    sensitivity_sl_tp,
    walk_forward,
)
from .tema_system import (
    TemaParams,
    compound_trades,
    daily_equity,
    tema_bar_equity,
    trade_stats,
)

log = logging.getLogger("tema_lab")
ART = Path("/opt/cursor/artifacts")
LOCAL = Path(__file__).resolve().parents[1] / "artifacts"


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
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    if isinstance(obj, pd.Series):
        return {str(k): _json_ready(v) for k, v in obj.to_dict().items()}
    if hasattr(obj, "__dataclass_fields__"):
        return _json_ready(asdict(obj))
    return obj


def _dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_ready(payload), indent=2, default=str))


def _save_fig(fig, stem: str) -> None:
    if fig is None:
        return
    for root in (ART, LOCAL):
        try:
            write_html(fig, root / f"{stem}.html")
        except Exception as exc:  # pragma: no cover
            log.warning("html %s: %s", stem, exc)


def _save_csv(df: pd.DataFrame, name: str) -> None:
    for root in (ART, LOCAL):
        try:
            root.mkdir(parents=True, exist_ok=True)
            df.to_csv(root / name, index=False)
        except Exception as exc:
            log.warning("csv %s: %s", name, exc)


def _bar_to_daily_eq(index: pd.DatetimeIndex, trades: pd.DataFrame, *, start_eq: float = 10_000.0) -> pd.Series:
    bar = tema_bar_equity(index, trades, start_eq=start_eq)
    return daily_equity(bar["equity"])


def _k_from_trades(index: pd.DatetimeIndex, trades: pd.DataFrame, *, start_eq: float = 10_000.0) -> dict[str, float]:
    return daily_kpis(index, trades, start_eq=start_eq)


def _verdict_carver(binary: dict, daily: dict, inv: dict, filt: dict) -> str:
    """Does Carver sizing improve OOS DD without wrecking Sharpe? Filter is a different list."""
    b_dd, d_dd = binary.get("max_dd"), daily.get("max_dd")
    b_sh, d_sh = binary.get("sharpe"), daily.get("sharpe")
    i_sh = inv.get("sharpe")
    if not all(np.isfinite(x) for x in (b_dd, d_dd, b_sh, d_sh) if x is not None):
        return "INCONCLUSIVE — not enough finite KPIs"
    tighter = float(d_dd) > float(b_dd)  # less negative
    sharpe_ok = float(d_sh) >= float(b_sh) - 0.15
    fc_helps = np.isfinite(i_sh) and float(d_sh) > float(i_sh) + 0.10
    if tighter and sharpe_ok and fc_helps:
        return "PASS — Carver size tightens DD and beats inverse-vol (forecast is doing work)"
    if tighter and sharpe_ok:
        return "PARTIAL — size tightens DD vs binary; forecast vs inv-vol is not a clear add. Do not promote."
    if tighter:
        return "PARTIAL — tighter DD but Sharpe slipped. Vol dial, not an edge. Do not promote."
    return "FAIL — Carver overlay does not control TEMA OOS drawdown vs binary. Keep constant stake."


def run(quick: bool = True) -> dict[str, Any]:
    ART.mkdir(parents=True, exist_ok=True)
    LOCAL.mkdir(parents=True, exist_ok=True)
    p10 = TemaParams(leverage=10.0)
    p1 = TemaParams(leverage=1.0)
    out: dict[str, Any] = {
        "protocol": {
            "is": f"{SPLIT.is_start} → {SPLIT.is_end}",
            "oos": f"{SPLIT.oos_start} → {SPLIT.oos_end}",
            "warmup_bars": WARMUP_BARS,
            "frozen": "9/90/199 SL 1.5×ATR TP 2.5×ATR agree>=1 isolated 10×",
            "kpis": "daily-marked equity, ann=365 — not 4h bars with ann=365",
            "promote": "IS Sharpe AND DF neighborhood AND OOS holdout. Never write into W_*.",
        }
    }

    btc, src = load_symbol("BTCUSDT", "4h")
    log.info("BTC 4h %s bars %s → %s source=%s", len(btc), btc.index[0], btc.index[-1], src)
    out["data"] = {"symbol": "BTCUSDT", "tf": "4h", "source": src, "bars": int(len(btc)),
                   "start": str(btc.index[0]), "end": str(btc.index[-1])}
    parts = split_frame(btc)
    t10 = eval_tema(btc, p10)
    t1 = eval_tema(btc, p1)

    # compounding: 1% wallet vs full isolated wallet (honest DD)
    oos_idx = parts["oos"].index
    is_idx = parts["is"].index
    comp_1pct = compound_trades(
        t10["oos_trades"], start_eq=10_000.0, risk_frac=0.01,
        leverage=p10.leverage, cost_bps=p10.cost_bps,
    )
    comp_full = compound_trades(
        t10["oos_trades"], start_eq=10_000.0, risk_frac=1.0,
        leverage=p10.leverage, cost_bps=p10.cost_bps,
    )
    k_1pct = _k_from_trades(oos_idx, comp_1pct)
    k_full = _k_from_trades(oos_idx, comp_full)
    k_is = t10["is_daily"]
    k_oos = t10["oos_daily"]
    k_oos_1x = t1["oos_daily"]

    board = kpi_table({
        "frozen_10x_IS_daily": k_is,
        "frozen_10x_OOS_daily": k_oos,
        "frozen_1x_OOS_daily": k_oos_1x,
        "compound_1pct_OOS": k_1pct,
        "compound_full_wallet_OOS": k_full,
    })
    out["validation"] = {
        "is": k_is,
        "oos": k_oos,
        "oos_1x": k_oos_1x,
        "compound_1pct": k_1pct,
        "compound_full_wallet": k_full,
        "is_trades": int(len(t10["is_trades"])),
        "oos_trades": int(len(t10["oos_trades"])),
        "note": (
            "$10k + $100 stake understates DD as a fraction of the book. "
            "compound_1pct = 1% of equity as isolated stake each ticket. "
            "compound_full_wallet = entire equity as isolated stake (violent)."
        ),
    }
    _save_csv(board.reset_index().rename(columns={"index": "book"}), "tema_validation_kpis.csv")

    # ---- plots: equity / DD / rolling Sharpe ----
    eq_oos_10 = _bar_to_daily_eq(oos_idx, t10["oos_trades"])
    eq_oos_1 = _bar_to_daily_eq(oos_idx, t1["oos_trades"])
    eq_oos_1pct = _bar_to_daily_eq(oos_idx, comp_1pct)
    eq_oos_full = _bar_to_daily_eq(oos_idx, comp_full)
    eq_is_10 = _bar_to_daily_eq(is_idx, t10["is_trades"])
    bh_oos = (1.0 + parts["oos"]["close"].resample("1D").last().dropna().pct_change().fillna(0.0)).cumprod()

    fig_eq = equity_overlay({
        "$10k+$100 10× (artifact)": eq_oos_10,
        "1× same trades": eq_oos_1,
        "1% compounding": eq_oos_1pct,
        "full isolated wallet": eq_oos_full,
    }, "OOS TEMA 9/90/199 — daily-marked equity")
    _save_fig(fig_eq, "tema_oos_equity")
    write_png_mpl(
        {
            "10x $100 stake": eq_oos_10 / eq_oos_10.iloc[0] if len(eq_oos_10) else eq_oos_10,
            "1% compound": eq_oos_1pct / eq_oos_1pct.iloc[0] if len(eq_oos_1pct) else eq_oos_1pct,
            "full wallet": eq_oos_full / eq_oos_full.iloc[0] if len(eq_oos_full) else eq_oos_full,
        },
        ART / "tema_oos_equity.png",
        title="OOS frozen TEMA — growth of $1",
        ylabel="Multiple",
    )
    write_png_mpl(
        {
            "10x $100 stake": eq_oos_10 / eq_oos_10.iloc[0] if len(eq_oos_10) else eq_oos_10,
            "1% compound": eq_oos_1pct / eq_oos_1pct.iloc[0] if len(eq_oos_1pct) else eq_oos_1pct,
            "full wallet": eq_oos_full / eq_oos_full.iloc[0] if len(eq_oos_full) else eq_oos_full,
        },
        LOCAL / "tema_oos_equity.png",
        title="OOS frozen TEMA — growth of $1",
        ylabel="Multiple",
    )
    _save_fig(underwater(eq_oos_10, "OOS TEMA DD — $10k+$100 (understated)"), "tema_oos_dd_artifact")
    _save_fig(underwater(eq_oos_1pct, "OOS TEMA DD — 1% compounding"), "tema_oos_dd_1pct")
    _save_fig(underwater(eq_oos_full, "OOS TEMA DD — full isolated wallet"), "tema_oos_dd_full")
    if len(eq_oos_full):
        dd_full = eq_oos_full / eq_oos_full.cummax() - 1.0
        write_png_mpl({"full wallet DD": dd_full}, ART / "tema_oos_dd_full.png", title="OOS TEMA full-wallet drawdown", ylabel="DD", hline=0.0)
        write_png_mpl({"full wallet DD": dd_full}, LOCAL / "tema_oos_dd_full.png", title="OOS TEMA full-wallet drawdown", ylabel="DD", hline=0.0)
    _save_fig(
        rolling_sharpe_fig({
            "10x $100": eq_oos_10.pct_change().fillna(0.0),
            "1% compound": eq_oos_1pct.pct_change().fillna(0.0),
            "full wallet": eq_oos_full.pct_change().fillna(0.0),
        }, 90, "OOS 90d rolling Sharpe (daily marks)"),
        "tema_oos_rolling_sharpe",
    )
    _save_fig(equity_overlay({"IS frozen 10×": eq_is_10}, "IS TEMA 9/90/199 — daily-marked"), "tema_is_equity")
    _save_fig(underwater(eq_is_10, "IS TEMA DD — $10k+$100"), "tema_is_dd")

    oos4 = parts["oos"]
    _save_fig(
        price_signals(
            oos4,
            entries=pd.DatetimeIndex(t10["oos_trades"]["entry_time"]) if len(t10["oos_trades"]) else None,
            exits=pd.DatetimeIndex(t10["oos_trades"]["exit_time"]) if len(t10["oos_trades"]) else None,
            title="BTC 4h OOS — frozen TEMA 9/90/199 entries",
            max_bars=800,
        ),
        "tema_oos_signals",
    )

    # ---- robustness ----
    wf = walk_forward(btc, FROZEN)
    _save_csv(wf, "tema_walk_forward.csv")
    out["walk_forward"] = wf.to_dict(orient="records")

    log.info("sensitivity IS")
    per = sensitivity_periods(parts["is"])
    sltp = sensitivity_sl_tp(parts["is"])
    gates = sensitivity_gates(parts["is"])
    _save_csv(per, "tema_sens_periods_is.csv")
    _save_csv(sltp, "tema_sens_sl_tp_is.csv")
    _save_csv(gates, "tema_sens_gates_is.csv")
    _save_fig(param_heatmap(sltp, "sl_atr", "tp_atr", "sharpe", "IS Sharpe — SL vs TP (frozen 9/90/199)"), "tema_sens_sl_tp_sharpe")
    _save_fig(param_heatmap(sltp, "sl_atr", "tp_atr", "max_dd", "IS max DD — SL vs TP"), "tema_sens_sl_tp_dd")
    _save_fig(param_heatmap(gates, "min_adx", "min_atr_pct", "sharpe", "IS Sharpe — ADX vs ATR% gate"), "tema_sens_gates_sharpe")
    out["sensitivity"] = {
        "periods_best": per.iloc[0].to_dict() if len(per) else {},
        "frozen_periods_rank": int(per["frozen"].to_numpy().nonzero()[0][0] + 1) if len(per) and per["frozen"].any() else None,
        "sltp_best": sltp.iloc[0].to_dict() if len(sltp) else {},
        "gates_best": gates.iloc[0].to_dict() if len(gates) else {},
    }

    log.info("DF neighborhood inner-IS")
    dfn_p = frozen_neighborhood(parts["is"], which="periods")
    dfn_e = frozen_neighborhood(parts["is"], which="exits")
    if dfn_p.get("table") is not None and len(dfn_p["table"]):
        _save_csv(dfn_p["table"], "tema_df_periods.csv")
        _save_fig(df_scatter(dfn_p["table"], "TEMA DF periods (inner IS)"), "tema_df_periods")
    if dfn_e.get("table") is not None and len(dfn_e["table"]):
        _save_csv(dfn_e["table"], "tema_df_exits.csv")
        _save_fig(df_scatter(dfn_e["table"], "TEMA DF SL/TP/ADX (inner IS)"), "tema_df_exits")
    out["df"] = {
        "periods": {k: v for k, v in dfn_p.items() if k != "table"},
        "exits": {k: v for k, v in dfn_e.items() if k != "table"},
    }

    opt_row = None
    if not quick:
        log.info("Optuna IS only — do not promote")
        ot = optimize_tema(parts["is"], n_trials=12, leverage=10.0)
        ot_ev = eval_tema(btc, ot["params"])
        opt_row = {
            "do_not_promote": True,
            "engine": ot.get("engine"),
            "params": asdict(ot["params"]),
            "is": ot["is_kpis"],
            "oos_daily": ot_ev["oos_daily"],
            "frozen_is": ot["frozen_9_90_199_is"],
        }
        out["optuna"] = opt_row

    # ---- Carver overlay ----
    log.info("Carver overlay on frozen TEMA")
    pack = overlay_pack(
        btc,
        t10["oos_trades"],
        t10["is_trades"]["entry_time"] if len(t10["is_trades"]) else pd.Index([]),
        base_stake=p10.stake,
        leverage=p10.leverage,
        cost_bps=p10.cost_bps,
        vol_target=VOL_TARGET,
    )
    pack_is = overlay_pack(
        btc,
        t10["is_trades"],
        t10["is_trades"]["entry_time"] if len(t10["is_trades"]) else pd.Index([]),
        base_stake=p10.stake,
        leverage=p10.leverage,
        cost_bps=p10.cost_bps,
        vol_target=VOL_TARGET,
    )
    carver_rows = {}
    eq_map = {}
    for name in ("binary", "carver_daily", "carver_4h", "inv_vol", "carver_filter"):
        tr = pack[name]
        carver_rows[f"{name}_OOS"] = _k_from_trades(oos_idx, tr)
        eq_map[name] = _bar_to_daily_eq(oos_idx, tr)
        carver_rows[f"{name}_IS"] = _k_from_trades(is_idx, pack_is[name])
    _save_csv(kpi_table(carver_rows).reset_index().rename(columns={"index": "book"}), "tema_carver_kpis.csv")
    _save_fig(equity_overlay(eq_map, "OOS TEMA — binary vs Carver size (IS-normalized stake)"), "tema_carver_oos_equity")
    write_png_mpl(
        {k: (v / v.iloc[0] if len(v) else v) for k, v in eq_map.items()},
        ART / "tema_carver_oos_equity.png",
        title="OOS TEMA binary vs Carver size",
        ylabel="Multiple",
    )
    write_png_mpl(
        {k: (v / v.iloc[0] if len(v) else v) for k, v in eq_map.items()},
        LOCAL / "tema_carver_oos_equity.png",
        title="OOS TEMA binary vs Carver size",
        ylabel="Multiple",
    )
    if len(eq_map.get("carver_daily", pd.Series(dtype=float))):
        _save_fig(underwater(eq_map["carver_daily"], "OOS TEMA Carver-daily size DD"), "tema_carver_oos_dd")
    _save_fig(
        rolling_sharpe_fig(
            {k: v.pct_change().fillna(0.0) for k, v in eq_map.items() if len(v)},
            90,
            "OOS 90d rolling Sharpe — TEMA ± Carver",
        ),
        "tema_carver_oos_sharpe",
    )

    # forecast skill at entry: corr(fc, trade ret) — should be ~0 if no timing alpha
    skill = {"n": 0, "corr_fc_ret": None, "hit_rate": None}
    if len(t10["oos_trades"]) and pack["fc_daily"] is not None:
        fcs, rets = [], []
        fc = pack["fc_daily"].sort_index()
        for _, r in t10["oos_trades"].iterrows():
            v = fc.asof(r["entry_time"])
            if v is not None and np.isfinite(v) and not pd.isna(v):
                fcs.append(float(v))
                rets.append(float(r["ret"]))
        if len(fcs) >= 8:
            skill = {
                "n": len(fcs),
                "corr_fc_ret": float(np.corrcoef(fcs, rets)[0, 1]),
                "hit_rate": float(np.mean((np.array(fcs) > 0) == (np.array(rets) > 0))),
            }

    carver_verdict = _verdict_carver(
        carver_rows["binary_OOS"],
        carver_rows["carver_daily_OOS"],
        carver_rows["inv_vol_OOS"],
        carver_rows["carver_filter_OOS"],
    )
    out["carver"] = {
        "refs": pack["refs"],
        "fdm": pack["fdm"],
        "kpis": carver_rows,
        "forecast_skill_oos": skill,
        "verdict": carver_verdict,
        "note": (
            "Scale ref is mean lagged Carver weight at IS entries so OOS average "
            "stake ≈ binary. Without that, a 12% mean weight shrinks DD for free."
        ),
    }

    # ---- hypotheses ----
    h8 = {
        "id": "H8",
        "claim": "Frozen TEMA 9/90/199 has a usable OOS equity path with controlled DD once stake is honest (1% compound or full wallet), not the $10k+$100 artifact",
        "oos_artifact": k_oos,
        "oos_1pct": k_1pct,
        "oos_full": k_full,
        "result": (
            "ARTIFACT" if abs(float(k_oos.get("max_dd") or 0)) < 0.06
            and abs(float(k_full.get("max_dd") or 0)) >= 0.12
            else ("HOLD" if np.isfinite(k_oos.get("sharpe")) and float(k_oos.get("sharpe")) > 0 else "WEAK")
        ),
    }
    h9 = {
        "id": "H9",
        "claim": "Walk-forward (esp. 2022) does not reverse frozen TEMA; nearby periods do not stably beat 9/90/199 on inner-IS DF",
        "walk_forward": wf.to_dict(orient="records"),
        "df_periods": {k: v for k, v in dfn_p.items() if k != "table"},
        "result": dfn_p.get("status", "unknown"),
        "do_not_promote": True,
    }
    h10 = {
        "id": "H10",
        "claim": "IS SL/TP and ADX/ATR grids are a plateau around 1.5/2.5 and ADX 20 — not a spike that wants a live retune",
        "sltp_best": out["sensitivity"]["sltp_best"],
        "gates_best": out["sensitivity"]["gates_best"],
        "result": "see heatmaps — frozen must sit in the plateau, not a one-cell peak",
        "do_not_promote": True,
    }
    h11 = {
        "id": "H11",
        "claim": "Carver can size TEMA tickets (lagged weight) and tighten OOS DD vs binary without needing the forecast vs inverse-vol",
        "verdict": carver_verdict,
        "skill": skill,
        "result": carver_verdict.split("—")[0].strip(),
        "do_not_promote": True,
    }
    out["hypotheses"] = [h8, h9, h10, h11]
    out["board"] = board.to_dict()

    _dump(LOCAL / "tema_lab_results.json", out)
    _dump(ART / "tema_lab_results.json", out)
    log.info("H8 %s | H11 %s", h8["result"], h11["result"])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TEMA-only trend lab")
    parser.add_argument("--quick", action="store_true", default=True)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(quick=not args.full)
    return 0


if __name__ == "__main__":
    sys.exit(main())
