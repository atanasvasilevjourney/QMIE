"""Write the research notebooks. Run: python research/notebooks/_build.py"""
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


write("05_tema_validation.ipynb", [
    cell(True, """# 05 — TEMA validation (short-term 4h book)

Frozen live stack **9 / 90 / 199**, agreement `>= 1`, isolated **10×**, SL 1.5×ATR / TP 2.5×ATR, same-bar both → SL. QMIE stays signal-only. **Do not retune live `W_*`.**

This notebook is the hedge-fund read of *this* book only — not spot, not the BTC/QQQ/GLD Carver trio.

## Protocol

| Slice | Window | Use |
|---|---|---|
| IS | 2019-09-01 → 2022-12-31 | describe, never steal OOS for a story |
| OOS | 2023-01-01 → today | the test |
| Warmup | 220 4h bars | OOS indicators seeded from last 220 IS bars |

Vision USDT-M 4h starts ~2020-01, not 2018.

## How to read equity and drawdown

KPIs are **daily-marked** (`ann=365`). A 4h bar Sharpe with `ann=365` understates vol.

The lab default `$10k account + $100 isolated stake` makes max DD look tiny (~3%). That is **not** control — it is a 1% wallet. This notebook also compounds:

* **1% compounding** — each ticket risks 1% of *current* equity as isolated margin (prop-like).
* **Full isolated wallet** — the whole account is the stake. One 1.5×ATR SL at 10× is a mid-teens hit, not a rounding error.

## H8

Frozen TEMA has a usable OOS path with controlled DD once stake is honest.
"""),
    cell(False, SETUP),
    cell(False, """
import pandas as pd
from research.trend_lab.evaluate import eval_tema
from research.trend_lab.data import load_symbol
from research.trend_lab.metrics import kpi_table
from research.trend_lab.plots import equity_overlay, price_signals, rolling_sharpe_fig, underwater
from research.trend_lab.protocol import SPLIT, WARMUP_BARS, split_frame
from research.trend_lab.tema_robust import daily_kpis
from research.trend_lab.tema_system import TemaParams, compound_trades, daily_equity, tema_bar_equity

print("IS", SPLIT.is_start, "→", SPLIT.is_end)
print("OOS", SPLIT.oos_start, "→", SPLIT.oos_end)
print("warmup", WARMUP_BARS)
print("frozen 9/90/199 10× isolated — Optuna does not belong in this notebook")
"""),
    cell(False, """
btc, src = load_symbol("BTCUSDT", "4h")
print("BTC 4h", src, len(btc), btc.index[0], "→", btc.index[-1])
parts = split_frame(btc)
p10 = TemaParams(leverage=10.0)
p1 = TemaParams(leverage=1.0)
t10 = eval_tema(btc, p10)
t1 = eval_tema(btc, p1)
oos_idx, is_idx = parts["oos"].index, parts["is"].index

comp_1pct = compound_trades(t10["oos_trades"], start_eq=10_000.0, risk_frac=0.01, leverage=10.0, cost_bps=p10.cost_bps)
comp_full = compound_trades(t10["oos_trades"], start_eq=10_000.0, risk_frac=1.0, leverage=10.0, cost_bps=p10.cost_bps)

def deq(idx, tr, start=10_000.0):
    return daily_equity(tema_bar_equity(idx, tr, start_eq=start)["equity"])

board = kpi_table({
    "frozen_10x_IS_daily": t10["is_daily"],
    "frozen_10x_OOS_daily": t10["oos_daily"],
    "frozen_1x_OOS_daily": t1["oos_daily"],
    "compound_1pct_OOS": daily_kpis(oos_idx, comp_1pct),
    "compound_full_wallet_OOS": daily_kpis(oos_idx, comp_full),
})
display(board.round(3))
print("IS trades", len(t10["is_trades"]), "OOS trades", len(t10["oos_trades"]))
if len(t10["oos_trades"]):
    display(t10["oos_trades"]["outcome"].value_counts().to_frame("n"))
    display(t10["oos_trades"][["r", "pnl", "bars"]].describe().round(3))
"""),
    cell(False, """
eq_art = deq(oos_idx, t10["oos_trades"])
eq_1x = deq(oos_idx, t1["oos_trades"])
eq_1pct = deq(oos_idx, comp_1pct)
eq_full = deq(oos_idx, comp_full)
eq_is = deq(is_idx, t10["is_trades"])

equity_overlay({
    "$10k+$100 10× (artifact)": eq_art,
    "1× same trades": eq_1x,
    "1% compounding": eq_1pct,
    "full isolated wallet": eq_full,
}, "OOS TEMA 9/90/199 — daily-marked equity").show()
rolling_sharpe_fig({
    "artifact": eq_art.pct_change().fillna(0),
    "1%": eq_1pct.pct_change().fillna(0),
    "full wallet": eq_full.pct_change().fillna(0),
}, 90, "OOS 90d rolling Sharpe").show()
underwater(eq_art, "OOS DD — $10k+$100 (understated)").show()
underwater(eq_1pct, "OOS DD — 1% compounding").show()
underwater(eq_full, "OOS DD — full isolated wallet").show()
equity_overlay({"IS frozen 10×": eq_is}, "IS TEMA — daily-marked").show()
underwater(eq_is, "IS DD — $10k+$100").show()
price_signals(
    parts["oos"],
    entries=pd.DatetimeIndex(t10["oos_trades"]["entry_time"]) if len(t10["oos_trades"]) else None,
    exits=pd.DatetimeIndex(t10["oos_trades"]["exit_time"]) if len(t10["oos_trades"]) else None,
    title="BTC 4h OOS — frozen TEMA entries",
    max_bars=800,
).show()
"""),
    cell(True, """## How to read this

If OOS Sharpe on the $100-stake book is ~0.3 and DD is −3%, **do not** call that a 10× edge with tight risk. Leverage scaled expectancy (H2 in notebook 01); it did not invent a Sharpe. The full-wallet curve is the honest “what if this *were* the book.” 1% compounding is the honest “what if we size like a desk.”

0 liquidations on this sample is a KPI, not a guarantee — isolated cap is load-bearing (`pnl >= -stake`).

Promote-to-live still needs DF + OOS vs frozen 9/90/199. This notebook does not search.
"""),
])


write("06_tema_robustness_sensitivity.ipynb", [
    cell(True, """# 06 — TEMA robustness and parameter sensitivity

Same frozen 9/90/199 book. **Fit never sees OOS.** Inner-IS (last 20% of IS) is the DF neighborhood. 2022 is a *stress fold*, not a training window.

## H9 / H10

* Walk-forward years do not reverse the frozen book; nearby periods do not stably beat 9/90/199 on inner-IS.
* SL/TP and ADX/ATR grids are a plateau around 1.5 / 2.5 and ADX 20 — not a one-cell peak that wants a live retune.

Optuna stays `do_not_promote=True`. A hotter IS Sharpe that dies on DF or OOS is overfit theatre.
"""),
    cell(False, SETUP),
    cell(False, """
import pandas as pd
from research.trend_lab.data import load_symbol
from research.trend_lab.evaluate import eval_tema
from research.trend_lab.optimize import optimize_tema
from research.trend_lab.plots import df_scatter, param_heatmap
from research.trend_lab.protocol import split_frame
from research.trend_lab.tema_robust import (
    FROZEN, frozen_neighborhood, sensitivity_gates, sensitivity_periods,
    sensitivity_sl_tp, walk_forward,
)
from research.trend_lab.tema_system import TemaParams

btc, src = load_symbol("BTCUSDT", "4h")
print("BTC 4h", src, len(btc))
parts = split_frame(btc)
is_4h = parts["is"]
print("IS bars", len(is_4h), "OOS bars", len(parts["oos"]))
"""),
    cell(True, """## Walk-forward

Each fold: frozen params, OOS window seeded with 220 IS bars from *before* that fold. No vol dial, no Optuna inside the fold.
"""),
    cell(False, """
wf = walk_forward(btc, FROZEN)
display(wf.round(3))
print("2022 stress row:")
display(wf.loc[wf["stress"]].round(3) if "stress" in wf else "no stress flag")
"""),
    cell(True, """## Sensitivity (IS only)

Frozen 9/90/199 / 1.5 / 2.5 / ADX 20 is always a row. Rank is not a license to promote the top cell.
"""),
    cell(False, """
per = sensitivity_periods(is_4h)
sltp = sensitivity_sl_tp(is_4h)
gates = sensitivity_gates(is_4h)
display(per.round(3))
display(sltp.head(8).round(3))
display(gates.round(3))
param_heatmap(sltp, "sl_atr", "tp_atr", "sharpe", "IS Sharpe — SL vs TP (periods frozen)").show()
param_heatmap(sltp, "sl_atr", "tp_atr", "max_dd", "IS max DD — SL vs TP").show()
param_heatmap(gates, "min_adx", "min_atr_pct", "sharpe", "IS Sharpe — ADX vs ATR% gate").show()
print("frozen periods rank", int(per.reset_index(drop=True).index[per.reset_index(drop=True)["frozen"]].tolist()[0] + 1) if per["frozen"].any() else None)
"""),
    cell(True, """## DF neighborhood (inner IS)

Among neighbors with train Sharpe ≥ 0.3, we want a *pool* whose val Sharpe std is small — a plateau. An empty pool or a single spike is a no-promote.
"""),
    cell(False, """
dfn_p = frozen_neighborhood(is_4h, which="periods")
dfn_e = frozen_neighborhood(is_4h, which="exits")
print("periods", dfn_p["status"], "val_std", dfn_p.get("val_sharpe_std"), "n_stable", dfn_p.get("n_stable"))
print("exits  ", dfn_e["status"], "val_std", dfn_e.get("val_sharpe_std"), "n_stable", dfn_e.get("n_stable"))
if dfn_p.get("table") is not None and len(dfn_p["table"]):
    df_scatter(dfn_p["table"], "TEMA DF — fast/mid/slow (inner IS)").show()
if dfn_e.get("table") is not None and len(dfn_e["table"]):
    df_scatter(dfn_e["table"], "TEMA DF — SL/TP/ADX (inner IS)").show()
"""),
    cell(True, """## Optuna (research only)

Run if you want the H3 replay. The winner is **not** written into the scanner. Skip this cell in a quick pass.
"""),
    cell(False, """
# ot = optimize_tema(is_4h, n_trials=12, leverage=10.0)
# ot_ev = eval_tema(btc, ot["params"])
# print("do_not_promote", ot["do_not_promote"], ot.get("engine"), ot["params"])
# print("frozen IS", ot["frozen_9_90_199_is"])
# print("optuna IS", ot["is_kpis"])
# print("optuna OOS daily", ot_ev["oos_daily"])
print("Optuna cell left commented — frozen 9/90/199 is the live stack. Uncomment to replay H3.")
"""),
    cell(True, """## Verdict rule

Promote 9/90/199 *away* only if IS Sharpe **and** DF neighborhood **and** OOS all clear for the challenger. A prettier IS heatmap is not that.
"""),
])


write("07_tema_carver_sizing.ipynb", [
    cell(True, """# 07 — Can Carver size the TEMA book?

Two systems, one overlay.

* **TEMA** decides *when* (event-driven 4h, frozen 9/90/199, isolated 10×, SL/TP).
* **Carver** decides *how much* (continuous forecast → vol-targeted weight, `exec_lag=1`).

Carver does **not** change periods, SL, or TP. Entries/exits stay the frozen list unless we explicitly **filter** (skip ticket if lagged weight < 0.05).

## Honest size

BTC-only Carver mean weight is ~12%. If we set `stake *= weight` raw, DD shrinks because the book got smaller — that is not an overlay result. **Scale reference = mean lagged weight at IS entries**, so OOS average stake ≈ binary TEMA. Then we compare paths.

| Book | What it tests |
|---|---|
| binary | constant $100 isolated stake |
| carver_daily | daily Carver (no CS) as-of onto 4h entries, IS-normalized |
| carver_4h | same-timescale Carver on 4h bars (`ann=2190`) |
| inv_vol | always-long vol target (forecast pinned +10) |
| carver_filter | skip entry if daily held < 0.05 (changes the list) |

## H11

Carver can size TEMA tickets and tighten OOS DD vs binary. The *forecast* vs inverse-vol is the tell: if daily-Carver ≈ inv-vol, you bought a vol dial, not Strat 17–19 skill.

Forecast skill at entry: `corr(fc_t, trade.ret)` — ~0 means no timing alpha on this ticket list.
"""),
    cell(False, SETUP),
    cell(False, """
import numpy as np
import pandas as pd
from research.trend_lab.carver import VOL_TARGET
from research.trend_lab.data import load_symbol
from research.trend_lab.evaluate import eval_tema
from research.trend_lab.metrics import kpi_table
from research.trend_lab.plots import allocation_fig, equity_overlay, rolling_sharpe_fig, underwater
from research.trend_lab.protocol import split_frame
from research.trend_lab.tema_carver import overlay_pack
from research.trend_lab.tema_robust import daily_kpis
from research.trend_lab.tema_system import TemaParams, daily_equity, tema_bar_equity

btc, src = load_symbol("BTCUSDT", "4h")
parts = split_frame(btc)
p10 = TemaParams(leverage=10.0)
t10 = eval_tema(btc, p10)
print("OOS trades", len(t10["oos_trades"]), "IS trades", len(t10["is_trades"]))

pack = overlay_pack(
    btc, t10["oos_trades"], t10["is_trades"]["entry_time"],
    base_stake=p10.stake, leverage=p10.leverage, cost_bps=p10.cost_bps, vol_target=VOL_TARGET,
)
pack_is = overlay_pack(
    btc, t10["is_trades"], t10["is_trades"]["entry_time"],
    base_stake=p10.stake, leverage=p10.leverage, cost_bps=p10.cost_bps, vol_target=VOL_TARGET,
)
print("IS scale refs", pack["refs"], "FDM", pack["fdm"])

oos_idx, is_idx = parts["oos"].index, parts["is"].index
rows, eqs = {}, {}
for name in ("binary", "carver_daily", "carver_4h", "inv_vol", "carver_filter"):
    rows[f"{name}_OOS"] = daily_kpis(oos_idx, pack[name])
    rows[f"{name}_IS"] = daily_kpis(is_idx, pack_is[name])
    eqs[name] = daily_equity(tema_bar_equity(oos_idx, pack[name])["equity"])
display(kpi_table(rows).round(3))
"""),
    cell(False, """
equity_overlay(eqs, "OOS TEMA — binary vs Carver size (IS-normalized)").show()
rolling_sharpe_fig({k: v.pct_change().fillna(0) for k, v in eqs.items() if len(v)}, 90, "OOS 90d rolling Sharpe").show()
underwater(eqs["binary"], "OOS binary TEMA DD").show()
underwater(eqs["carver_daily"], "OOS Carver-daily size DD").show()
underwater(eqs["inv_vol"], "OOS inverse-vol size DD").show()
allocation_fig({
    "daily held (lagged)": pack["held_daily"].reindex(oos_idx),
    "4h held (lagged)": pack["held_4h"].reindex(oos_idx),
}, "OOS Carver weight on the 4h index").show()

# forecast skill on the frozen OOS ticket list
fcs, rets = [], []
fc = pack["fc_daily"].sort_index()
for _, r in t10["oos_trades"].iterrows():
    v = fc.asof(r["entry_time"])
    if v is not None and np.isfinite(v) and not pd.isna(v):
        fcs.append(float(v)); rets.append(float(r["ret"]))
if len(fcs) >= 8:
    corr = float(np.corrcoef(fcs, rets)[0, 1])
    hit = float(np.mean((np.array(fcs) > 0) == (np.array(rets) > 0)))
    print(f"OOS corr(fc, trade ret)={corr:.3f}  hit={hit:.3f}  n={len(fcs)}")
else:
    print("not enough overlapping forecasts")
print("mean OOS daily held", float(pack["held_daily"].reindex(oos_idx).mean()))
print("median OOS daily held", float(pack["held_daily"].reindex(oos_idx).median()))
"""),
    cell(True, """## How to implement (research → desk, still no broker)

1. Keep TEMA entries exactly as live (9/90/199, ADX/ATR/RSI gates, SL/TP).
2. At signal close, read **yesterday’s** Carver weight (daily last 4h close, `exec_lag=1`).
3. `stake_eff = stake_ref * clip(w / w_IS_mean, 0, 2.5)`. Isolated cap on `stake_eff`.
4. Do **not** skip the ticket from a weak forecast unless H11’s filter book clearly wins OOS *and* DF — that is a second change.
5. Do **not** write Carver into `W_*` or Pine. Sizing is not scoring.

If corr(fc, ret) ≈ 0 and Carver-daily ≈ inv-vol, ship a **vol dial** (smaller tickets in high vol), not a forecast engine.
"""),
])
