"""Write the three research notebooks. Run: python research/notebooks/_build.py"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cell(md: bool, src: str) -> dict:
    return {
        "cell_type": "markdown" if md else "code",
        "metadata": {},
        "source": [line + "\n" for line in src.strip("\n").split("\n")],
        **({} if md else {"outputs": [], "execution_count": None}),
    }


def nb(cells: list[dict]) -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "cells": cells,
    }


SETUP = r'''
import sys
from pathlib import Path
ROOT = Path.cwd()
if ROOT.name == "notebooks":
    ROOT = ROOT.parent.parent
elif (ROOT / "research").exists():
    pass
elif (ROOT / "python" / "research").exists():
    ROOT = ROOT / "python"
sys.path.insert(0, str(ROOT))
print("python root", ROOT)
'''


def write(name: str, cells: list[dict]) -> None:
    path = HERE / name
    path.write_text(json.dumps(nb(cells), indent=1))
    print("wrote", path)


write("01_crypto_trend_lab.ipynb", [
    cell(True, """# 01 — Crypto trend lab (spot + 4h TEMA)

Research only. QMIE remains signal-only. **Do not retune live `W_*`.** Frozen TEMA is 9/90/199.

## Protocol (this is the test, not a fit story)

The request “2018–2023 OOS, 2023→now IS” trains on the **future**. That is a leakage diagnostic, not a valid holdout. This lab fits **IS 2019-09 → 2022-12** and never tunes on **OOS 2023 → today**. Vision USDT-M starts ~2019-09, not 2018. `WARMUP_BARS = 220`. Positions are `signal.shift(1)`.

## Hypotheses in this notebook

| Id | Claim |
|---|---|
| H1 | Spot 1D EMA+Donchian+ADX beats buy-and-hold on OOS Sharpe **or** tighter DD |
| H2 | 10× isolated TEMA raises expectancy vs 1× but worsens max DD / liquidations |
| H3 | Optuna-best TEMA periods fail DF / OOS vs frozen 9/90/199 — **do not promote** |
| H4 | Boruta-confirmed confluence (KAMA / MACD / z-score / ALMA) improves OOS vs raw breakout |

Promote-to-live requires IS Sharpe **and** DF neighborhood **and** OOS holdout. None of these cells write scanner weights.
"""),
    cell(False, SETUP),
    cell(False, """
from research.trend_lab.protocol import SPLIT, WARMUP_BARS
from research.trend_lab.data import CORE, coverage_table, load_symbol
from research.trend_lab.evaluate import eval_spot, eval_tema, reverse_split_diagnostic
from research.trend_lab.features import feature_frame
from research.trend_lab.optimize import boruta_select, df_neighborhood_score, grid_spot, grid_tema, optimize_spot, optimize_tema, trend_label
from research.trend_lab.protocol import inner_validation_start, split_frame
from research.trend_lab.spot_system import SpotParams, spot_signal
from research.trend_lab.tema_system import TemaParams
from research.trend_lab.plots import df_scatter, equity_overlay, param_heatmap, price_signals, rolling_sharpe_fig, underwater
from scanner.indicators import ema
from research.trend_lab.features import alma, kama
import pandas as pd

print(SPLIT)
print("warmup", WARMUP_BARS)
print(SPLIT.requested_note)
"""),
    cell(False, """
cov = coverage_table(CORE[:5], ("1d", "4h"))
display(cov)
"""),
    cell(False, """
btc_1d, src_1d = load_symbol("BTCUSDT", "1d")
btc_4h, src_4h = load_symbol("BTCUSDT", "4h")
print("1d", src_1d, len(btc_1d), btc_1d.index[0] if len(btc_1d) else None, "→", btc_1d.index[-1] if len(btc_1d) else None)
print("4h", src_4h, len(btc_4h), btc_4h.index[0] if len(btc_4h) else None, "→", btc_4h.index[-1] if len(btc_4h) else None)
parts = split_frame(btc_1d)
print("IS bars", len(parts["is"]), "OOS bars", len(parts["oos"]))
"""),
    cell(True, """## Boruta on IS only

Labels are next-10-bar sign of return. The last 10 IS bars are dropped so the label never uses OOS closes. Shadows are permuted copies of the same features. Confirmed = beat max shadow in ≥95% of iterations.
"""),
    cell(False, """
is_1d = parts["is"]
feats = feature_frame(is_1d).iloc[WARMUP_BARS:]
y = trend_label(is_1d["close"], horizon=10).reindex(feats.index)
boruta = boruta_select(feats.iloc[:-10], y.iloc[:-10], n_iter=8, n_estimators=80)
display(boruta)
confirmed = boruta.loc[boruta.decision.eq("confirmed"), "feature"].tolist()
print("confirmed", confirmed)
"""),
    cell(True, """## Approach 1 — spot (leverage 1)

Radar analog: fast EMA > slow EMA, **prior-window** Donchian breakout, ADX ≥ min and +DI > −DI, RSI cap, hold while above prior box. Grid + Optuna (or random search if Optuna is missing) fit **IS only**. DF neighborhood is scored on the last 20% of IS, never OOS.
"""),
    cell(False, """
baseline = SpotParams()
grid = grid_spot(is_1d)
display(grid.head(8))
opt = optimize_spot(is_1d, n_trials=16)
print("engine", opt.get("engine"), opt["params"])
base_ev = eval_spot(btc_1d, baseline)
opt_ev = eval_spot(btc_1d, opt["params"])
conf_p = SpotParams(
    use_kama="kama_cross" in confirmed or "kama_er" in confirmed,
    use_macd="macd_hist" in confirmed,
    use_zscore="zscore_20" in confirmed,
    use_alma="alma_slope" in confirmed,
)
conf_ev = eval_spot(btc_1d, conf_p)
summary = pd.DataFrame({
    "baseline_IS": base_ev["is"], "baseline_OOS": base_ev["oos"],
    "optuna_OOS": opt_ev["oos"], "confluence_OOS": conf_ev["oos"],
    "BH_OOS": base_ev["bh_oos"],
}).T
display(summary.round(3))
"""),
    cell(False, """
inner = inner_validation_start(is_1d.index)
center = {
    "ema_fast": float(opt["params"].ema_fast),
    "ema_slow": float(opt["params"].ema_slow),
    "donchian": float(opt["params"].donchian),
    "min_adx": float(opt["params"].min_adx),
}
steps = {k: [v-d, v, v+d] for (k, v), d in zip(center.items(), (2, 10, 5, 2))}

def run_fn(ohlcv, p):
    fr = spot_signal(ohlcv, SpotParams(ema_fast=int(p["ema_fast"]), ema_slow=int(p["ema_slow"]), donchian=int(p["donchian"]), min_adx=float(p["min_adx"])))
    return fr[["net", "equity"]]

dfn = df_neighborhood_score(is_ohlcv=is_1d, inner_val_start=inner, center=center, neighbor_steps=steps, run_fn=run_fn, min_is_sharpe=0.5)
print(dfn["status"], "val_sharpe_std", dfn.get("val_sharpe_std"), "n_stable", dfn.get("n_stable"))
if dfn.get("table") is not None and len(dfn["table"]):
    df_scatter(dfn["table"], "Spot DF neighborhood (inner IS)").show()
param_heatmap(grid, "ema_slow", "ema_fast", "sharpe", "Spot grid IS Sharpe").show()
"""),
    cell(False, """
equity_overlay({
    "spot baseline": base_ev["oos_frame"]["equity"],
    "spot Optuna": opt_ev["oos_frame"]["equity"],
    "confluence": conf_ev["oos_frame"]["equity"],
    "buy&hold": (1 + parts["oos"]["close"].pct_change().fillna(0)).cumprod(),
}, "OOS growth of $1 — BTC spot").show()
rolling_sharpe_fig({"spot": base_ev["oos_frame"]["net"], "optuna": opt_ev["oos_frame"]["net"]}, 90, "OOS 90d rolling Sharpe").show()
underwater(base_ev["oos_frame"]["equity"], "Spot baseline OOS DD").show()

oos = parts["oos"]
ks, _ = kama(oos["close"], 10)
overlays = {"EMA9": ema(oos["close"], 9), "EMA199": ema(oos["close"], 199), "KAMA10": ks, "ALMA9": alma(oos["close"], 9)}
entries = base_ev["oos_frame"].index[base_ev["oos_frame"]["signal"].diff().fillna(0) > 0]
exits = base_ev["oos_frame"].index[base_ev["oos_frame"]["signal"].diff().fillna(0) < 0]
price_signals(oos, signal=base_ev["oos_frame"]["held"], entries=entries, exits=exits, overlays=overlays, title="BTC 1D OOS — spot vs KAMA/ALMA/EMA").show()
"""),
    cell(True, """## Approach 2 — 4h TEMA, isolated 10×

Same-bar SL and TP → SL. Loss capped at stake. Frozen 9/90/199 is always reported. Optuna search is **research**; `do_not_promote=True`.
"""),
    cell(False, """
t10 = eval_tema(btc_4h, TemaParams(leverage=10.0))
t1 = eval_tema(btc_4h, TemaParams(leverage=1.0))
gt = grid_tema(split_frame(btc_4h)["is"], leverage=10.0)
display(gt)
ot = optimize_tema(split_frame(btc_4h)["is"], n_trials=12, leverage=10.0)
ot_ev = eval_tema(btc_4h, ot["params"])
print("do_not_promote", ot["do_not_promote"], "engine", ot.get("engine"))
tema_tbl = pd.DataFrame({
    "frozen_10x_IS": t10["is"], "frozen_10x_OOS": t10["oos"],
    "frozen_1x_OOS": t1["oos"], "optuna_10x_OOS": ot_ev["oos"],
    "frozen_10x_IS_opt_report": ot["frozen_9_90_199_is"], "optuna_10x_IS": ot["is_kpis"],
}).T
display(tema_tbl.round(3))
oos4 = split_frame(btc_4h)["oos"]
price_signals(oos4, entries=pd.DatetimeIndex(t10["oos_trades"]["entry_time"]) if len(t10["oos_trades"]) else None,
              exits=pd.DatetimeIndex(t10["oos_trades"]["exit_time"]) if len(t10["oos_trades"]) else None,
              title="BTC 4h OOS — frozen TEMA 9/90/199 10x isolated", max_bars=800).show()
"""),
    cell(True, """## Leakage diagnostic (do not select from this)

Train on 2023→now, test on 2019–2022. If this looks better than the chronological OOS, that is **overfit theatre**, not edge.
"""),
    cell(False, """
leak = reverse_split_diagnostic(btc_1d, baseline)
print(leak["note"])
display(pd.DataFrame({"fit_on_future": leak["fit_on_future"], "test_on_past": leak["test_on_past"]}).T.round(3))
"""),
])

write("02_carver_vs_ensemble.ipynb", [
    cell(True, """# 02 — Carver trend system vs ensembles

Two philosophies, same BTC book, same costs, `exec_lag=1`.

* **Ensemble (QMIE spot analog):** binary flag, full-port when on, flat when off. Times turns; lumpy DD.
* **Carver:** continuous forecast → vol-targeted size. Always allocated at some (possibly tiny) weight. Surfs the trend.
* **Blend:** 50/50 unlagged mix, then lagged once in the backtest. Diversifies timing vs sizing.

The vol target is the **master dial**. Raise it and both return and DD scale; the *shape* of the curve stays the same. That is the prop-firm use case in the source note — QMIE still does not send orders.

## Hypotheses

| Id | Claim |
|---|---|
| H5 | Carver has lower OOS DD (and usually lower CAGR) than the binary ensemble |
| H6 | ADX chop gate and/or a causal DD circuit breaker tighten OOS max DD vs raw Carver |
"""),
    cell(False, SETUP),
    cell(False, """
from research.trend_lab.allocation import blend_weights, chop_gate
from research.trend_lab.carver import backtest, dd_circuit_breaker, full_carver
from research.trend_lab.data import CORE, load_panel, load_symbol
from research.trend_lab.metrics import kpis
from research.trend_lab.plots import allocation_fig, equity_overlay, rolling_sharpe_fig, underwater
from research.trend_lab.protocol import WARMUP_BARS, split_frame
from research.trend_lab.spot_system import SpotParams, spot_signal
import pandas as pd

btc, _ = load_symbol("BTCUSDT", "1d")
parts = split_frame(btc)
panel, srcs = load_panel(CORE[:4], "1d")
print("panel", list(panel.columns), srcs)
w, fc, fdm = full_carver(panel, "BTCUSDT", use_cs=panel.shape[1] >= 3)
print("FDM", round(fdm, 3))
cv = backtest(btc["close"], w.reindex(btc.index).fillna(0.0))
ens = spot_signal(btc, SpotParams())
mix = backtest(btc["close"], blend_weights(w.reindex(btc.index).fillna(0.0), ens["signal"], mix=0.5))
gate = chop_gate(btc, 18.0)
chop = backtest(btc["close"], w.reindex(btc.index).fillna(0.0) * gate.reindex(btc.index).fillna(0.0))
brk = backtest(btc["close"], dd_circuit_breaker(w.reindex(btc.index).fillna(0.0), cv["equity"]))

def oos(bt):
    sl = bt.reindex(parts["oos"].index)
    return kpis(sl["net"], sl["equity"])

rows = {
    "ensemble_OOS": kpis(ens.reindex(parts["oos"].index)["net"], ens.reindex(parts["oos"].index)["equity"]),
    "carver_OOS": oos(cv),
    "blend_OOS": oos(mix),
    "chop_carver_OOS": oos(chop),
    "dd_breaker_OOS": oos(brk),
}
display(pd.DataFrame(rows).T.round(3))
"""),
    cell(False, """
vol_rows = []
for vt in (0.10, 0.20, 0.40):
    wv, _, _ = full_carver(panel, "BTCUSDT", use_cs=panel.shape[1] >= 3, vol_target=vt)
    bt = backtest(btc["close"], wv.reindex(btc.index).fillna(0.0)).reindex(parts["oos"].index)
    vol_rows.append({"vol_target": vt, **kpis(bt["net"], bt["equity"])})
display(pd.DataFrame(vol_rows).round(3))

oos_eq = {
    "ensemble": ens.reindex(parts["oos"].index)["equity"],
    "carver": cv.reindex(parts["oos"].index)["equity"],
    "blend": mix.reindex(parts["oos"].index)["equity"],
    "chop": chop.reindex(parts["oos"].index)["equity"],
    "dd-breaker": brk.reindex(parts["oos"].index)["equity"],
}
equity_overlay(oos_eq, "OOS growth — Carver vs ensemble").show()
rolling_sharpe_fig({k: v.pct_change().fillna(0) for k, v in oos_eq.items()}, 90, "OOS 90d rolling Sharpe").show()
underwater(cv.reindex(parts["oos"].index)["equity"], "Carver OOS DD").show()
allocation_fig({
    "carver": cv["held"].reindex(parts["oos"].index),
    "ensemble": ens["held"].reindex(parts["oos"].index),
    "blend": mix["held"].reindex(parts["oos"].index),
}, "OOS allocation (lagged weights)").show()
"""),
    cell(True, """## How to read this

If Carver’s OOS CAGR looks “emasculating” next to the ensemble, that is the product, not a bug: vol targeting sells headline return for a smoother path. The ensemble will usually win **timing** on a single name when the flag is well fitted. Carver wins **mandate fit** when a daily-loss cap exists.

Trend following still needs a trend. Sideways OOS will flatten both books; the chop gate is allowed to stay flat. Do not engineer that away by fitting ADX on OOS.
"""),
])

write("03_portfolio_kpis.ipynb", [
    cell(True, """# 03 — Portfolio KPIs, ranked spot book, hypothesis board

Hedge-fund read: Sharpe, Sortino, Calmar, Ulcer, max DD, CAGR, turnover, names held. Ranked allocation is the QMIE allocator idea on **daily spot** (lookback ROC, top-3, cluster_max=1). It does not execute. `quantity` stays 0 in production.

## H7

Ranked top-N eligible names beat equal-weight eligible names on OOS Sharpe or DD.

After the board: if the crypto model is not robust under chronological OOS + DF, **do not ship parameter changes**.
"""),
    cell(False, SETUP),
    cell(False, """
import json
from pathlib import Path
import pandas as pd
from research.trend_lab.allocation import bh_equal, book_kpis, equal_weight_book, ranked_spot_book
from research.trend_lab.data import CORE, load_symbol
from research.trend_lab.plots import equity_overlay
from research.trend_lab.protocol import split_frame
from research.trend_lab.spot_system import SpotParams, spot_signal
from research.trend_lab.protocol import WARMUP_BARS

btc, _ = load_symbol("BTCUSDT", "1d")
parts = split_frame(btc)
close_cols, held_cols = {}, {}
for sym in CORE[:4]:
    df, _ = load_symbol(sym, "1d")
    if df.empty or len(df) < WARMUP_BARS + 50:
        continue
    close_cols[sym] = df["close"]
    held_cols[sym] = spot_signal(df, SpotParams())["signal"]
cpanel = pd.concat(close_cols, axis=1).sort_index()
hpanel = pd.concat(held_cols, axis=1).reindex(cpanel.index).fillna(0.0)
ranked = ranked_spot_book(cpanel, hpanel, lookback=60, top_n=3)
equal = equal_weight_book(cpanel, hpanel)
bh = bh_equal(cpanel)
oos_idx = parts["oos"].index.intersection(ranked.index)
tbl = pd.DataFrame({
    "ranked": book_kpis(ranked.loc[oos_idx]),
    "equal": book_kpis(equal.loc[oos_idx]),
    "buyhold": book_kpis(bh.loc[oos_idx]),
}).T
display(tbl.round(3))
equity_overlay({
    "ranked top-3": ranked.loc[oos_idx]["equity"],
    "equal eligible": equal.loc[oos_idx]["equity"],
    "buy&hold equal": bh.loc[oos_idx]["equity"],
}, "OOS spot book").show()
"""),
    cell(False, """
art = Path(ROOT) / "research" / "artifacts" / "lab_results.json"
if not art.exists():
    art = Path("/opt/cursor/artifacts/lab_results.json")
if art.exists():
    lab = json.loads(art.read_text())
    print("protocol", lab.get("protocol"))
    display(pd.DataFrame(lab.get("kpi_summary", {})).T.round(3) if lab.get("kpi_summary") else "no kpi_summary yet — run python -m research.trend_lab.run_lab --quick")
    for h in lab.get("hypotheses", []):
        print(f"{h.get('id')}  {h.get('result')}  — {h.get('claim')}")
else:
    print("No lab_results.json yet. From python/:  python -m research.trend_lab.run_lab --quick")
"""),
    cell(True, """## Professional caution

* **Overfit:** Optuna on 16–28 trials of a 7-knob space will find IS luck. DF neighborhood (KAMA notebook method) is the filter; if the stable pool is empty, the fit is a spike, not a plateau.
* **Lookahead / repaint:** Donchian uses `high.shift(1).rolling`. KAMA/ALMA/EMA are causal. Fills are next-bar (`held = signal.shift(1)`). TEMA entry uses the signal bar close; SL/TP on subsequent bars; same-bar both → SL.
* **10× isolated:** a −10% adverse move wipes the stake. Headline E[R] at 10× is not a 10× Sharpe. Liquidation count is a first-class KPI.
* **Chop:** ADX < ~18 is “no trade / size 0”, not a new oscillator to fit.
* **Cross-section:** five names is a toy book. Cluster_max stops doubling ETH-beta. This is still not a 50-name futures book.
* **Live engine:** 4h A/A+ TEMA 9/90/199 is the frozen measured edge. Daily TEMA A/A+ OOS loses. This lab does not add `1d` to `SCAN_TIMEFRAMES` and does not change Pine.
"""),
])
