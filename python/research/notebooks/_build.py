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
    "$10k+$100 10×": eq_art,
    "1× same trades": eq_1x,
    "1% compounding": eq_1pct,
}, "OOS TEMA 9/90/199 — 1% isolated book (daily-marked)").show()
equity_overlay({"full isolated wallet": eq_full}, "OOS TEMA — full isolated wallet (ruin path)").show()
rolling_sharpe_fig({
    "1% book": eq_1pct.pct_change().fillna(0),
    "$100 stake": eq_art.pct_change().fillna(0),
}, 90, "OOS 90d rolling Sharpe — 1% book").show()
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

write("08_donchian_avwap_ranked_validation.ipynb", [
    cell(True, """# 08 — Donchian + Anchored VWAP + Ranked allocation (validation)

**Research only.** Validates the master-spec *approach* on daily USDT-M Vision klines (same archive as `trend_lab`). This is **not** live execution, not GA, and not a survivorship-clean top-100 universe.

## Honest framing

- Long-only trend is **upside convexity + exit optionality**, not symmetric long-vol (that needs shorts or options).
- This notebook uses a **fixed liquid basket** (~11 symbols). Missing delisted alts **inflates** any positive result vs a true top-N universe.
- Fills: **next-bar** (`shift(1)`). Features use **prior-window** Donchian (`shift(1)` rolling). OOS is **2023→today**; fit window is **2019-09→2022-12** (chronological — never train on the future).

## Pre-registered checks in this notebook

| Id | Test |
|---|---|
| H2 | AVWAP filter (`above_avwap`) vs same book without AVWAP gate |
| H4 | Ranked top-K vs equal-weight on the same active set |
| H5 | BTC regime filter ON vs OFF (gross cap when OFF) |
| Placebo | Permuted entry flags — real book Sharpe should beat placebo band |

Leakage: **+1 bar feature shift** should hurt Sharpe vs baseline.
"""),
    cell(False, SETUP),
    cell(False, """
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from research.trend_lab.data import DEFAULT_UNIVERSE, load_symbol
from research.trend_lab.metrics import kpis, kpis_from_net, max_dd
from research.trend_lab.protocol import SPLIT, WARMUP_BARS, split_frame
from scanner.indicators import atr

ANN = 365
COST_BPS = 10.0
"""),
    cell(False, """
@dataclass(frozen=True)
class ConvexParams:
    n_entry: int = 55
    n_exit: int = 20
    atr_stop_mult: float = 3.0
    compression_window: int = 60
    compression_pct_max: float = 40.0  # only enter if width pct <= this (coiled)
    avwap_anchor: str = "breakout_bar"  # breakout_bar | swing_low
    use_avwap_gate: bool = True
    use_compression_gate: bool = True
    top_k: int = 5
    rank_decay_exp: float = 1.0
    target_vol_ann: float = 0.25
    rebalance_rule: str = "W-SUN"
    regime_filter: bool = True
    gross_cap_off_regime: float = 0.30
    min_strength: float = 0.5
    single_name_cap: float = 0.25
    exec_lag: int = 1


def donchian_dual(df: pd.DataFrame, n_entry: int, n_exit: int) -> pd.DataFrame:
    hi = df["high"].shift(1).rolling(n_entry, min_periods=n_entry).max()
    lo = df["low"].shift(1).rolling(n_exit, min_periods=n_exit).min()
    mid = (hi + lo) / 2.0
    width = (hi - lo) / (df["close"] + 1e-12)
    return pd.DataFrame({"upper": hi, "lower": lo, "mid": mid, "width": width}, index=df.index)


def compression_percentile(width: pd.Series, window: int) -> pd.Series:
    def _pct(x: np.ndarray) -> float:
        if len(x) < 2:
            return np.nan
        last = x[-1]
        return float((x[:-1] <= last).mean() * 100.0)

    return width.rolling(window, min_periods=window).apply(_pct, raw=True)


def avwap_from_anchor(df: pd.DataFrame, anchor_ts: pd.Timestamp, end_ts: pd.Timestamp) -> float:
    sl = df.loc[anchor_ts:end_ts]
    if sl.empty:
        return float("nan")
    tp = (sl["high"] + sl["low"] + sl["close"]) / 3.0
    vol = sl["volume"].replace(0, np.nan)
    if vol.notna().sum() == 0:
        return float(sl["close"].iloc[-1])
    return float((tp * vol).sum() / vol.sum())


def swing_low_ts(df: pd.DataFrame, before: pd.Timestamp, lookback: int = 20) -> pd.Timestamp:
    sl = df.loc[:before].tail(lookback + 1)
    if sl.empty:
        return before
    i = sl["low"].idxmin()
    return pd.Timestamp(i)


def coin_features(df: pd.DataFrame, p: ConvexParams) -> pd.DataFrame:
    don = donchian_dual(df, p.n_entry, p.n_exit)
    atr_s = atr(df, 14)
    atr_pct = atr_s / (df["close"] + 1e-12)
    comp_pct = compression_percentile(don["width"], p.compression_window)
    breakout = df["close"] > don["upper"]
    exit_lower = df["close"] < don["lower"]
    dist_upper = (df["close"] - don["upper"]) / (atr_s + 1e-12)
    return pd.DataFrame({
        "close": df["close"],
        "upper": don["upper"],
        "lower": don["lower"],
        "mid": don["mid"],
        "width": don["width"],
        "comp_pct": comp_pct,
        "atr": atr_s,
        "atr_pct": atr_pct,
        "breakout": breakout.astype(float),
        "exit_lower": exit_lower.astype(float),
        "dist_upper": dist_upper,
    }, index=df.index)


def trend_strength(feats: pd.DataFrame, avwap_dist: pd.Series) -> pd.Series:
    z = avwap_dist.replace([np.inf, -np.inf], np.nan)
    z = (z - z.expanding(min_periods=20).mean()) / (z.expanding(min_periods=20).std(ddof=0) + 1e-12)
    vol_exp = feats["width"].pct_change(5).replace([np.inf, -np.inf], np.nan)
    score = feats["dist_upper"].fillna(0) + 0.5 * z.fillna(0) + 0.25 * vol_exp.fillna(0)
    return score.rename("strength")


def btc_regime(btc: pd.DataFrame, n_entry: int) -> pd.Series:
    don = donchian_dual(btc, n_entry, max(5, n_entry // 3))
    on = (btc["close"] > don["mid"]).astype(float)
    return on.rename("regime")


def _seed_avwap_cum(df: pd.DataFrame, anchor_ts: pd.Timestamp, end_ts: pd.Timestamp) -> tuple[float, float]:
    sl = df.loc[anchor_ts:end_ts]
    tp = (sl["high"] + sl["low"] + sl["close"]) / 3.0
    vol = sl["volume"].astype(float)
    return float((tp * vol).sum()), float(vol.sum())


def simulate_coin_path(df: pd.DataFrame, p: ConvexParams, rebalance_days: set) -> pd.DataFrame:
    \"\"\"Daily in/out: entries on rebalance days only; risk exits any day. Incremental AVWAP.\"\"\"
    feats = coin_features(df, p)
    idx = df.index
    n = len(idx)
    eligible = np.zeros(n, dtype=float)
    strength = np.zeros(n, dtype=float)
    dist_upper = feats["dist_upper"].to_numpy(dtype=float)
    breakout = feats["breakout"].to_numpy(dtype=float)
    comp_pct = feats["comp_pct"].to_numpy(dtype=float)
    exit_lower = feats["exit_lower"].to_numpy(dtype=float)
    atr_a = feats["atr"].to_numpy(dtype=float)
    close_a = feats["close"].to_numpy(dtype=float)

    in_pos = False
    entry_px = np.nan
    cum_pv, cum_v = 0.0, 0.0

    for i, ts in enumerate(idx):
        if in_pos and cum_v > 0:
            av = cum_pv / cum_v
            dist_av = (close_a[i] - av) / (atr_a[i] + 1e-12)
            strength[i] = dist_upper[i] + 0.5 * dist_av
        else:
            strength[i] = dist_upper[i] if np.isfinite(dist_upper[i]) else 0.0

        stop_hit = (
            in_pos
            and np.isfinite(entry_px)
            and np.isfinite(atr_a[i])
            and close_a[i] < entry_px - p.atr_stop_mult * atr_a[i]
        )
        if in_pos and (exit_lower[i] == 1.0 or stop_hit):
            in_pos = False
            entry_px = np.nan
            cum_pv, cum_v = 0.0, 0.0

        want = (
            ts in rebalance_days
            and not in_pos
            and breakout[i] == 1.0
            and np.isfinite(comp_pct[i])
            and strength[i] >= p.min_strength
        )
        if want and p.use_compression_gate and comp_pct[i] > p.compression_pct_max:
            want = False
        if want:
            anc = pd.Timestamp(ts) if p.avwap_anchor == "breakout_bar" else swing_low_ts(df, ts)
            av0 = avwap_from_anchor(df, anc, ts)
            dist0 = (close_a[i] - av0) / (atr_a[i] + 1e-12)
            if p.use_avwap_gate and dist0 < 0:
                want = False
            else:
                cum_pv, cum_v = _seed_avwap_cum(df, anc, ts)
        if want:
            in_pos = True
            entry_px = close_a[i]
        elif in_pos and cum_v > 0:
            row = df.loc[ts]
            tp = (row["high"] + row["low"] + row["close"]) / 3.0
            cum_pv += float(tp) * float(row["volume"])
            cum_v += float(row["volume"])

        eligible[i] = 1.0 if in_pos else 0.0

    return pd.DataFrame({"eligible": eligible, "strength": strength}, index=idx)


def rank_weights(names: list[str], strengths: dict[str, float], vols: dict[str, float], p: ConvexParams) -> dict[str, float]:
    if not names:
        return {}
    ranked = sorted(names, key=lambda n: strengths.get(n, -1e9), reverse=True)
    ranked = [n for n in ranked if strengths.get(n, 0) >= p.min_strength][: p.top_k]
    if not ranked:
        return {}
    raw = np.array([(len(ranked) - i) ** p.rank_decay_exp for i in range(len(ranked))], dtype=float)
    inv_vol = np.array([1.0 / max(vols.get(n, 1e-6), 1e-6) for n in ranked], dtype=float)
    w = raw * inv_vol
    w = w / w.sum()
    cap = p.single_name_cap
    if cap < 1:
        w = np.minimum(w, cap)
        if w.sum() > 0:
            w = w / w.sum()
    return {n: float(wi) for n, wi in zip(ranked, w)}


def vol_scale_weights(weights: dict[str, float], port_vol: float, target: float) -> dict[str, float]:
    if port_vol <= 0 or not weights:
        return weights
    scale = min(1.0, target / port_vol)
    return {k: v * scale for k, v in weights.items()}


def common_index(ohlcv: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    idx = None
    for df in ohlcv.values():
        idx = df.index if idx is None else idx.intersection(df.index)
    idx = pd.DatetimeIndex(idx).sort_values()
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return idx


def precompute_paths(
    ohlcv: dict[str, pd.DataFrame], p: ConvexParams, idx: pd.DatetimeIndex, rebalance_days: set
) -> dict[str, pd.DataFrame]:
    out = {}
    for sym, df in ohlcv.items():
        out[sym] = simulate_coin_path(df.loc[idx], p, rebalance_days)
    return out


def run_book_from_paths(
    ohlcv: dict[str, pd.DataFrame],
    btc: pd.DataFrame,
    p: ConvexParams,
    idx: pd.DatetimeIndex,
    rebalance_days: set,
    paths: dict[str, pd.DataFrame],
    *,
    ranked: bool = True,
    permute_seed: int | None = None,
) -> pd.DataFrame:
    regime = btc_regime(btc, p.n_entry).reindex(idx).ffill().fillna(0)
    syms = list(ohlcv.keys())
    elig = pd.DataFrame({s: paths[s]["eligible"] for s in syms}, index=idx)
    stren = pd.DataFrame({s: paths[s]["strength"] for s in syms}, index=idx)
    if permute_seed is not None:
        rng = np.random.default_rng(permute_seed)
        for s in syms:
            v = elig[s].to_numpy().copy()
            rng.shuffle(v)
            elig[s] = v

    rets = pd.DataFrame({s: ohlcv[s]["close"].loc[idx].pct_change().fillna(0) for s in syms})
    vol20 = rets.rolling(20).std(ddof=1)
    held = pd.DataFrame(0.0, index=idx, columns=syms)
    last = pd.Series(0.0, index=syms)

    for ts in idx:
        if ts in rebalance_days:
            names = [s for s in syms if elig.at[ts, s] > 0]
            w: dict[str, float] = {}
            if names:
                strengths = {s: float(stren.at[ts, s]) for s in names}
                vols = {s: float(vol20.at[ts, s]) if pd.notna(vol20.at[ts, s]) else 1e-6 for s in names}
                w = rank_weights(names, strengths, vols, p) if ranked else {s: 1.0 / len(names) for s in names}
                gross = sum(w.values())
                reg = float(regime.at[ts])
                if p.regime_filter and reg < 0.5:
                    gross = min(gross, p.gross_cap_off_regime)
                elif not p.regime_filter:
                    gross = min(gross, p.gross_cap_off_regime)
                if gross > 0:
                    w = {k: v * gross / sum(w.values()) for k, v in w.items()}
                port_vol = float(
                    np.sqrt(sum((float(vol20.at[ts, s]) or 0) ** 2 * (w.get(s, 0) ** 2) for s in w))
                ) * np.sqrt(ANN)
                w = vol_scale_weights(w, port_vol, p.target_vol_ann)
            last = pd.Series(0.0, index=syms)
            for s, wi in w.items():
                last[s] = wi
        for s in syms:
            held.at[ts, s] = float(last[s]) if elig.at[ts, s] > 0 else 0.0

    held_exec = held.shift(p.exec_lag).fillna(0)
    gross_ret = (held_exec * rets).sum(axis=1)
    turnover = held_exec.diff().abs().fillna(held_exec.abs()).sum(axis=1)
    net = gross_ret - turnover * (COST_BPS / 1e4)
    return pd.DataFrame({"net": net, "equity": (1 + net).cumprod(), "turnover": turnover, "gross": gross_ret})


def run_book(
    ohlcv: dict[str, pd.DataFrame],
    btc: pd.DataFrame,
    p: ConvexParams,
    *,
    ranked: bool = True,
    permute_entries: bool = False,
    seed: int = 42,
) -> pd.DataFrame:
    idx = common_index(ohlcv)
    rebalance_days = set(pd.Series(1, index=idx).resample(p.rebalance_rule).last().dropna().index)
    paths = precompute_paths(ohlcv, p, idx, rebalance_days)
    return run_book_from_paths(
        ohlcv,
        btc,
        p,
        idx,
        rebalance_days,
        paths,
        ranked=ranked,
        permute_seed=seed if permute_entries else None,
    )


def block_bootstrap_diff(a: pd.Series, b: pd.Series, block: int = 20, n: int = 120, seed: int = 0) -> tuple[float, float, float]:
    \"\"\"Paired bootstrap on aligned net returns: mean(a) - mean(b). Returns (obs, p_two_sided, ci95_low).\"\"\"
    df = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    if len(df) < block * 3:
        return float("nan"), float("nan"), float("nan")
    obs = float(df["a"].mean() - df["b"].mean())
    rng = np.random.default_rng(seed)
    n_obs = len(df)
    boots = []
    for _ in range(n):
        starts = rng.integers(0, max(1, n_obs - block + 1), size=max(1, n_obs // block))
        ix = []
        for s in starts:
            ix.extend(range(s, min(s + block, n_obs)))
        ix = ix[:n_obs]
        samp = df.iloc[ix]
        boots.append(float(samp["a"].mean() - samp["b"].mean()))
    boots = np.array(boots)
    p = float(2 * min((boots >= 0).mean(), (boots <= 0).mean()))
    ci_low = float(np.percentile(boots, 2.5))
    return obs, p, ci_low
"""),
    cell(False, """
# Load daily OHLCV (Vision USDT-M). Survivorship: survivors only — interpret KPIs as optimistic.
symbols = [s for s in DEFAULT_UNIVERSE if s != "BTCUSDT"]
btc_df, btc_src = load_symbol("BTCUSDT", "1d")
ohlcv = {}
sources = {"BTCUSDT": btc_src}
for sym in symbols:
    df, src = load_symbol(sym, "1d")
    if len(df) < WARMUP_BARS:
        print("skip", sym, len(df))
        continue
    ohlcv[sym] = df
    sources[sym] = src
print("loaded", len(ohlcv), "alts + BTC regime", btc_src, "bars", len(btc_df))
"""),
    cell(False, """
base = ConvexParams()
idx = common_index(ohlcv)
rebalance_days = set(pd.Series(1, index=idx).resample(base.rebalance_rule).last().dropna().index)
paths_avwap = precompute_paths(ohlcv, base, idx, rebalance_days)
paths_no_avwap = precompute_paths(ohlcv, ConvexParams(use_avwap_gate=False), idx, rebalance_days)

book_rank_avwap = run_book_from_paths(ohlcv, btc_df, base, idx, rebalance_days, paths_avwap, ranked=True)
book_eq_avwap = run_book_from_paths(ohlcv, btc_df, base, idx, rebalance_days, paths_avwap, ranked=False)
book_no_avwap = run_book_from_paths(
    ohlcv, btc_df, ConvexParams(use_avwap_gate=False), idx, rebalance_days, paths_no_avwap, ranked=True
)
book_no_regime = run_book_from_paths(
    ohlcv, btc_df, ConvexParams(regime_filter=False), idx, rebalance_days, paths_avwap, ranked=True
)

cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
is_net = book_rank_avwap.loc[: cut - pd.Timedelta(days=1), "net"]
oos_net = book_rank_avwap.loc[cut:, "net"]

summary = pd.DataFrame({
    "rank_avwap_IS": kpis_from_net(is_net),
    "rank_avwap_OOS": kpis_from_net(oos_net),
    "equal_avwap_OOS": kpis_from_net(book_eq_avwap.loc[cut:, "net"]),
    "rank_no_avwap_OOS": kpis_from_net(book_no_avwap.loc[cut:, "net"]),
    "rank_no_regime_OOS": kpis_from_net(book_no_regime.loc[cut:, "net"]),
}).T
display(summary.round(4))
"""),
    cell(False, """
# H2 / H4 / H5 — paired bootstrap on daily net (OOS)
cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
oos_a = book_rank_avwap.loc[cut:, "net"]
oos_b = book_no_avwap.loc[cut:, "net"]
oos_eq = book_eq_avwap.loc[cut:, "net"]
oos_reg = book_no_regime.loc[cut:, "net"]

h2 = block_bootstrap_diff(oos_a, oos_b, block=15, seed=1)
h4 = block_bootstrap_diff(oos_a, oos_eq, block=15, seed=2)
h5 = block_bootstrap_diff(book_rank_avwap.loc[cut:, "net"], oos_reg, block=15, seed=3)

hyp = pd.DataFrame([
    {"id": "H2_avwap", "obs_mean_diff": h2[0], "p_approx": h2[1], "ci95_low": h2[2],
     "pass_rule": "obs>0 and p<0.05 (exploratory — not lockbox)"},
    {"id": "H4_ranked", "obs_mean_diff": h4[0], "p_approx": h4[1], "ci95_low": h4[2],
     "pass_rule": "ranked net mean > equal-weight"},
    {"id": "H5_regime", "obs_mean_diff": h5[0], "p_approx": h5[1], "ci95_low": h5[2],
     "pass_rule": "regime ON improves DD or Calmar (check KPI table)"},
])
display(hyp.round(5))
"""),
    cell(False, """
# Placebo distribution (permute eligible flags; reuses path cache)
cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
real_sh = float(kpis_from_net(book_rank_avwap.loc[cut:, "net"])["sharpe"])
placebo = []
for seed in range(12):
    pb = run_book_from_paths(
        ohlcv, btc_df, base, idx, rebalance_days, paths_avwap, ranked=True, permute_seed=seed
    )
    placebo.append(float(kpis_from_net(pb.loc[cut:, "net"])["sharpe"]))
placebo = np.array(placebo)
print("OOS Sharpe real", round(real_sh, 3), "placebo median", round(float(np.median(placebo)), 3),
      "pctile real", round(float((placebo < real_sh).mean()), 3))
"""),
    cell(False, """
# Leakage sanity: +1 bar lag on OHLC (features see stale prices; Sharpe should drop)
lagged = {s: df.shift(1).dropna() for s, df in ohlcv.items()}
btc_lag = btc_df.shift(1).dropna()
book_lag = run_book(lagged, btc_lag, base, ranked=True)
cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
sh_ok = float(kpis_from_net(book_rank_avwap.loc[cut:, "net"])["sharpe"])
sh_lag = float(kpis_from_net(book_lag.loc[cut:, "net"])["sharpe"])
print("OOS Sharpe baseline", round(sh_ok, 3), "lagged OHLC", round(sh_lag, 3), "degraded", sh_lag < sh_ok)
"""),
    cell(True, """## Readout

- If **OOS Sharpe** is not above the **placebo** band, treat edge as unproven (sample is small; costs are constant bps, not sqrt-impact).
- **H2/H4/H5** bootstrap p-values are exploratory; full pre-registration lives in `hypotheses.py` (not built in this notebook-only pass).
- Next hardening steps: spot Vision loader, rolling top-N universe with delists, weekly/monthly rebalance grid, sqrt slippage, nested walk-forward — STAGES 1–4 of the master spec.
"""),
])

write("09_catching_crypto_trends.ipynb", [
    cell(True, """# 09 — Catching Crypto Trends (Zarattini et al., SSRN 5209907)

**Final research approach (paper replica on QMIE data).** Implements the published **Combo** model:

- **9 Donchian horizons:** 5, 10, 20, 30, 60, 90, 150, 250, 360 days (close-based channels)
- **Entry:** close at upper band; **exit:** close below **mid-band trailing stop** (stop = max(prior stop, mid), never lowered)
- **Sizing:** target **25%** ann. vol via **90-day** return σ, cap **2×**
- **Combo:** equal-weight average of sub-model weights
- **Portfolio:** **top N** names by **median daily dollar volume** (prior 30 days), **monthly** rotation, **equal capital** per name
- **Costs:** **10 bps** + **20%** weight-change rebalance threshold (per paper Section 5–7)

**Data:** Binance Vision USDT-M daily (same as `trend_lab`). This is **not** CoinMarketCap’s full survivorship panel — headline stats are **not** comparable 1:1 to the paper until CMC replication exists.

**Execution discipline:** weights applied with **`shift(1)`** (next-bar) to avoid same-bar fill optimism.

Reference: [SSRN 5209907](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5209907)
"""),
    cell(False, SETUP),
    cell(False, """
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from scipy import stats

from research.trend_lab.data import load_symbol
from research.trend_lab.metrics import kpis_from_net, max_dd, cagr
from research.trend_lab.protocol import SPLIT

HORIZONS = (5, 10, 20, 30, 60, 90, 150, 250, 360)
VOL_TARGET = 0.25
SIGMA_DAYS = 90
LEV_CAP = 2.0
COST_BPS = 10.0
REBAL_THRESH = 0.20
TOP_N = 20
EXEC_LAG = 1
ANN = 365

CANDIDATES = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ADAUSDT",
    "TRXUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "UNIUSDT",
    "ATOMUSDT", "ETCUSDT", "FILUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "NEARUSDT",
    "INJUSDT", "SUIUSDT", "SEIUSDT", "TIAUSDT", "ZECUSDT", "HYPEUSDT", "XLMUSDT", "ENAUSDT",
]
"""),
    cell(False, """
def donchian_close(close: pd.Series, n: int) -> pd.DataFrame:
    \"\"\"Paper-style channels on close (includes current bar in rolling window).\"\"\"
    up = close.rolling(n, min_periods=n).max()
    dn = close.rolling(n, min_periods=n).min()
    mid = (up + dn) / 2.0
    return pd.DataFrame({"up": up, "dn": dn, "mid": mid})


def combo_net(close: pd.Series) -> pd.Series:
    \"\"\"Single-pass Combo: all horizons updated in one bar loop.\"\"\"
    c = close.to_numpy(dtype=float)
    n_bars = len(c)
    sigma = close.pct_change().rolling(SIGMA_DAYS).std(ddof=1).to_numpy(dtype=float) * np.sqrt(ANN)
    mids = {}
    ups = {}
    for n in HORIZONS:
        ch = donchian_close(close, n)
        mids[n] = ch["mid"].to_numpy(dtype=float)
        ups[n] = ch["up"].to_numpy(dtype=float)
    nh = len(HORIZONS)
    in_pos = np.zeros(nh, dtype=bool)
    trail = np.full(nh, np.nan)
    w_exec = np.zeros(nh)
    w_combo = np.zeros(n_bars)
    for i in range(n_bars):
        ci = c[i]
        sig = sigma[i]
        for j, n in enumerate(HORIZONS):
            mid = mids[n][i]
            up = ups[n][i]
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
                w_tgt = min(LEV_CAP, VOL_TARGET / sig)
            if abs(w_tgt - w_exec[j]) > REBAL_THRESH:
                w_exec[j] = w_tgt
        w_combo[i] = w_exec.mean()
    w_s = pd.Series(w_combo, index=close.index)
    ret = close.pct_change().fillna(0.0)
    held = w_s.shift(EXEC_LAG).fillna(0.0)
    turnover = held.diff().abs().fillna(held.abs())
    return (held * ret - turnover * (COST_BPS / 1e4)).rename("net")


def ann_alpha_vs_btc(net: pd.Series, btc_close: pd.Series) -> tuple[float, float, float]:
    b = btc_close.pct_change().reindex(net.index).fillna(0.0)
    p = net.reindex(b.index).fillna(0.0)
    if len(p.dropna()) < 50:
        return float("nan"), float("nan"), float("nan")
    beta, alpha_d, _, _, _ = stats.linregress(b.values, p.values)
    alpha_ann = float(alpha_d * ANN)
    return alpha_ann, float(beta), float(stats.pearsonr(b, p)[0])
"""),
    cell(False, """
# Load Vision daily OHLCV (parallel; cache warm after first run)
from concurrent.futures import ThreadPoolExecutor, as_completed

def _load_one(sym: str):
    df, src = load_symbol(sym, "1d", start=date(2015, 1, 1))
    return sym, df, src

ohlcv: dict[str, pd.DataFrame] = {}
min_bars = max(HORIZONS) + SIGMA_DAYS + 10
with ThreadPoolExecutor(max_workers=6) as ex:
    futs = {ex.submit(_load_one, sym): sym for sym in CANDIDATES}
    for fut in as_completed(futs):
        sym, df, src = fut.result()
        if len(df) < min_bars:
            continue
        ohlcv[sym] = df
        print(sym, len(df), src)
print("tradable with enough history:", len(ohlcv))
"""),
    cell(False, """
# Per-asset Combo net returns
net_by_sym = {sym: combo_net(df["close"]) for sym, df in ohlcv.items()}
net_panel = pd.DataFrame(net_by_sym).sort_index()
dollar_vol = pd.DataFrame(
    {s: ohlcv[s]["close"] * ohlcv[s]["volume"] for s in ohlcv}
).reindex(net_panel.index)

# Monthly top-N by prior 30-day median dollar volume (point-in-time)
idx = net_panel.index
month_starts = pd.Series(1, index=idx).resample("MS").first().dropna().index
membership: dict[pd.Timestamp, list[str]] = {}
for ms in month_starts:
    prior = dollar_vol.loc[ms - pd.Timedelta(days=30): ms - pd.Timedelta(days=1)]
    if prior.empty:
        continue
    med = prior.median().dropna().sort_values(ascending=False)
    membership[ms] = list(med.head(TOP_N).index)

# Daily portfolio: equal-weight across active names for that month
port_net = pd.Series(0.0, index=idx)
counts = pd.Series(0, index=idx)
active_sets = []
for ts in idx:
    ms = max([m for m in month_starts if m <= ts], default=None)
    if ms is None or ms not in membership:
        continue
    active = [s for s in membership[ms] if s in net_panel.columns and pd.notna(net_panel.at[ts, s])]
    if not active:
        continue
    port_net.at[ts] = float(net_panel.loc[ts, active].mean())
    counts.at[ts] = len(active)
    active_sets.append((ts, len(active)))

port_net = port_net.rename("net")
btc = ohlcv["BTCUSDT"]["close"].reindex(idx).ffill()
btc_net = btc.pct_change().fillna(0.0)
"""),
    cell(False, """
# Full-sample and OOS KPIs (chronological split at SPLIT.oos_start)
cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
full_k = kpis_from_net(port_net)
oos_k = kpis_from_net(port_net.loc[cut:])
is_k = kpis_from_net(port_net.loc[: cut - pd.Timedelta(days=1)])
btc_oos = kpis_from_net(btc_net.loc[cut:])
alpha_full, beta_full, corr_full = ann_alpha_vs_btc(port_net, btc)
alpha_oos, beta_oos, corr_oos = ann_alpha_vs_btc(port_net.loc[cut:], btc.loc[cut:])

summary = pd.DataFrame({
    "Combo_topN_full": full_k,
    "Combo_topN_IS": is_k,
    "Combo_topN_OOS": oos_k,
    "BTC_BH_OOS": btc_oos,
}).T
display(summary.round(4))

print("Ann. alpha vs BTC (lin. reg on daily net): full", round(alpha_full, 4), "OOS", round(alpha_oos, 4))
print("Beta vs BTC: full", round(beta_full, 3), "OOS", round(beta_oos, 3))
print("Mean active names:", round(float(counts.replace(0, np.nan).mean()), 1))
"""),
    cell(False, """
# Equity vs vol-matched BTC (OOS)
eq = (1.0 + port_net).cumprod()
eq_btc = (1.0 + btc_net).cumprod()
vol_p = float(port_net.loc[cut:].std(ddof=1) * np.sqrt(ANN))
vol_b = float(btc_net.loc[cut:].std(ddof=1) * np.sqrt(ANN))
scale = vol_p / vol_b if vol_b > 0 else 1.0
eq_btc_s = (1.0 + btc_net * scale).cumprod()

cmp = pd.DataFrame({
    "Combo_topN": eq.loc[cut:],
    "BTC_vol_scaled": eq_btc_s.loc[cut:],
}).dropna()
display(cmp.tail(1).round(4))
print("OOS max DD Combo", round(max_dd(eq.loc[cut:]), 4), "BTC scaled", round(max_dd(eq_btc_s.loc[cut:]), 4))
print("OOS CAGR Combo", round(cagr(eq.loc[cut:]), 4), "BTC scaled", round(cagr(eq_btc_s.loc[cut:]), 4))
"""),
    cell(False, """
# Single-asset BTC Combo (paper Table 1 analogue; Vision data, 10bps, 20% threshold, exec lag 1)
btc_combo = net_by_sym["BTCUSDT"]
btc_k = {
    "full": kpis_from_net(btc_combo),
    "OOS": kpis_from_net(btc_combo.loc[cut:]),
}
display(pd.DataFrame(btc_k).T.round(4))
"""),
    cell(True, """## Fixed top 20 by market cap (no rotation)

**Operator list:** large-cap liquid USDT-M perps; **#19 = ENA**, **#20 = SUI**. Rank 17 uses **NEAR** (`SHIBUSDT` has no Vision daily file). **No monthly rotation** — equal-weight Combo each day (names without history yet are skipped).

⚠️ Fixed cap-weighted *today* on full history is still **survivorship/selection bias** unless membership is point-in-time.
"""),
    cell(False, """
MCAP_TOP20 = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "TRXUSDT", "ZECUSDT", "DOGEUSDT",
    "HYPEUSDT", "ADAUSDT", "LINKUSDT", "XLMUSDT", "UNIUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT",
    "NEARUSDT", "DOTUSDT", "ENAUSDT", "SUIUSDT",
]
FIXED_TOP20 = MCAP_TOP20
print("Fixed mcap top 20 (#19 ENA, #20 SUI):", FIXED_TOP20)

fixed_cols = [c for c in FIXED_TOP20 if c in net_panel.columns]
sub_fixed = net_panel[fixed_cols]
n_fixed = sub_fixed.notna().sum(axis=1).replace(0, np.nan)
port_fixed = (sub_fixed.sum(axis=1, skipna=True) / n_fixed).fillna(0.0).rename("net")

fixed_full = kpis_from_net(port_fixed)
fixed_oos = kpis_from_net(port_fixed.loc[cut:])
fixed_is = kpis_from_net(port_fixed.loc[: cut - pd.Timedelta(days=1)])
a_fix, b_fix = ann_alpha_vs_btc(port_fixed.loc[cut:], btc.loc[cut:])

display(pd.DataFrame({
    "fixed_top20_full": fixed_full,
    "fixed_top20_IS": fixed_is,
    "fixed_top20_OOS": fixed_oos,
    "rotating_topN_OOS": oos_k,
}).T.round(4))

from scipy import stats as sp_stats
oos_daily = port_fixed.loc[cut:].dropna()
_, p_mean = sp_stats.ttest_1samp(oos_daily, 0.0)
print("OOS ann alpha vs BTC", round(a_fix, 4), "beta", round(b_fix, 3))
print("Mean names contributing", round(float(n_fixed.mean()), 2))
print("OOS mean daily net", round(float(oos_daily.mean()), 6), "H0 mean=0 p-value", round(float(p_mean), 4))
"""),
    cell(True, """## Readout vs paper (SSRN 5209907)

| Metric (top-20 book, net) | Paper ~2015–Mar 2025 | This notebook |
|---|---:|---:|
| Sharpe | **1.57** | see table above |
| CAGR | **~18%** | see table above |
| Max DD | **~11%** | see table above |
| Alpha vs BTC | **10.8%** / yr | see print above |

**Gaps:** CMC survivorship panel, exact same-bar execution, and broader alt history. Treat this as **QMIE Vision replication**, not a claim to reproduce Concretum’s exact numbers.

**Not long-vol:** this is **trend + vol targeting + rotation**, same economic story as the paper — not options straddle long-vol.
"""),
    cell(False, """
# Optional: export last KPI snapshot for CI / agents (no secrets)
import json
from pathlib import Path
snap = {
    "model": "Combo_topN_SSRN5209907_replica",
    "data": "binance_vision_usdt_m_1d",
    "n_symbols_loaded": len(ohlcv),
    "top_n": TOP_N,
    "full": full_k,
    "oos": oos_k,
    "alpha_ann_vs_btc_full": alpha_full,
    "alpha_ann_vs_btc_oos": alpha_oos,
    "btc_combo_oos": btc_k["OOS"],
}
out = Path("/opt/cursor/artifacts/catching_crypto_trends_results.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(snap, indent=2, default=float))
print("wrote", out)
"""),
])

write("10_donchian_carver_cross_sectional.ipynb", [
    cell(True, """# 10 — Donchian Combo × Carver × cross-sectional rank

**One notebook, two questions** (fixed **mcap top 20**, Vision 1d, #19 ENA / #20 SUI — same as notebook 09):

1. **Donchian + Carver** — per-asset **50/50 blend**, **Carver gated by Donchian** (`carver × 1{donchian>1%}`), vs each engine alone (equal-weight 20 names).
2. **Donchian + cross-sectional** — apply **`carver_book`** ranked layer (60d ROC, **top 5**, portfolio vol target) to **Donchian weights**, **Carver weights**, and the blends.

**Carver source:** `HedgeFund_WiP/carver_engine_with_cross_sectional.ipynb` → `trend_lab/carver.py` + `carver_book.py`.

**Costs / execution:** 10 bps turnover, `shift(1)` weights. OOS split: `SPLIT.oos_start` (2023-01-01).

Research only — does not change live QMIE scanner weights.
"""),
    cell(False, SETUP),
    cell(False, """
from __future__ import annotations

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
from research.trend_lab.donchian_combo import (
    COST_BPS, EXEC_LAG, MCAP_TOP20, combo_weight_series, equal_weight_portfolio,
)
from research.trend_lab.metrics import kpis_from_net
from research.trend_lab.protocol import SPLIT

ANN = 365
MIN_BARS = 370
START_CAP = 100_000.0
cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
"""),
    cell(False, """
def load_panel(symbols: list[str]) -> pd.DataFrame:
    def _one(sym: str):
        df, _ = load_symbol(sym, "1d", start=date(2015, 1, 1))
        return sym, df

    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(_one, symbols))
    ok = {s: df["close"] for s, df in rows if len(df) >= MIN_BARS}
    panel = pd.DataFrame(ok).sort_index()
    print("panel", panel.shape, "from", panel.index[0], "to", panel.index[-1])
    return panel

panel = load_panel(MCAP_TOP20)
"""),
    cell(False, """
# Raw weight panels
w_don = pd.DataFrame({s: combo_weight_series(panel[s]) for s in panel.columns})
w_car = carver_weight_panel(panel, use_cs=True, ann_days=ANN)
w_blend = pd.DataFrame(
    {s: blend_weights(w_car[s], w_don[s], mix=0.5) for s in panel.columns},
    index=panel.index,
)
w_gate = w_car * (w_don > 0.01).astype(float)
print("mean lagged Donchian weight OOS", float(w_don.loc[cut:].shift(EXEC_LAG).mean().mean()))
print("mean lagged Carver weight OOS", float(w_car.loc[cut:].shift(EXEC_LAG).mean().mean()))
"""),
    cell(True, """## Part 1 — Donchian channel breakout + Carver (equal-weight 20)

Per-name weights are combined **before** the equal-weight portfolio step.
"""),
    cell(False, """
part1_books = {
    "donchian_combo_eq20": equal_weight_portfolio(w_don, panel),
    "carver_engine_eq20": equal_weight_portfolio(w_car, panel),
    "blend_50_50_eq20": equal_weight_portfolio(w_blend, panel),
    "gate_carver_if_donchian_eq20": equal_weight_portfolio(w_gate, panel),
}

def kpi_row(name: str, net: pd.Series) -> dict:
    oos = net.loc[cut:].fillna(0.0)
    k = kpis_from_net(oos)
    pnl = float(START_CAP * ((1.0 + oos).prod() - 1.0))
    return {"book": name, "oos_sharpe": k["sharpe"], "oos_cagr": k["cagr"],
            "oos_max_dd": k["max_dd"], "oos_pnl_100k": pnl}

part1 = pd.DataFrame([kpi_row(n, s) for n, s in part1_books.items()]).sort_values("oos_sharpe", ascending=False)
display(part1.round(4))
"""),
    cell(True, """## Part 2 — Cross-sectional ranked book (ROC 60, top 5)

Same **`book_from_raw_weights`** as ranked Carver desk research: rank by 60d return among names with raw weight > 0, keep top 5, scale to Carver vol target (20% crypto default in engine).
"""),
    cell(False, """
cs = BookParams(vol_target=VOL_TARGET, lookback=60, top_n=5, cost_bps=COST_BPS, exec_lag=EXEC_LAG)

part2_books = {
    "donchian_cs_top5": book_from_raw_weights(panel, w_don, cs)["net"],
    "carver_cs_top5": book_from_raw_weights(panel, w_car, cs)["net"],
    "blend_cs_top5": book_from_raw_weights(panel, w_blend, cs)["net"],
    "gate_cs_top5": book_from_raw_weights(panel, w_gate, cs)["net"],
}

part2 = pd.DataFrame([kpi_row(n, s) for n, s in part2_books.items()]).sort_values("oos_sharpe", ascending=False)
display(part2.round(4))

# Baselines side-by-side (OOS)
compare = pd.concat([
    part1.assign(layer="eq20"),
    part2.assign(layer="cs_top5"),
], ignore_index=True)
display(compare.sort_values("oos_sharpe", ascending=False).round(4))
"""),
    cell(False, """
# OOS equity curves ($100k start at OOS open)
eq_rows = {}
for label, net in {**part1_books, **part2_books}.items():
    oos = net.loc[cut:].fillna(0.0)
    eq_rows[label] = START_CAP * (1.0 + oos).cumprod()
eq_df = pd.DataFrame(eq_rows).dropna(how="all")
display(eq_df.tail(3).round(0))

out = Path("/opt/cursor/artifacts/donchian_carver_cs_notebook10.json")
payload = {
    "universe": list(panel.columns),
    "oos_start": str(cut.date()),
    "part1_donchian_plus_carver": part1.to_dict(orient="records"),
    "part2_cross_sectional": part2.to_dict(orient="records"),
}
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2, default=float))
print("wrote", out)
"""),
    cell(True, """## Readout

- **Donchian-only eq20** is the conservative baseline (~−8% OOS max DD in prior runs).
- **Donchian + CS top5** concentrates into momentum leaders — higher CAGR / Sharpe but **deeper drawdowns** (~−20% class).
- **Carver + Donchian blend** sits between; gating Carver on Donchian trend reduces turnover when breakout flat.

Re-run CLI: `python -m research.trend_lab.run_donchian_carver_hybrid`
"""),
])

write("11_donchian_nb08_carver.ipynb", [
    cell(True, """# 11 — Donchian (notebook 08 dual channel) × Carver

**Scope:** Only the **first Donchian research notebook** logic — **55/20 prior-bar channels**, breakout / lower-band (+ ATR stop) — blended with the **Carver engine** (`carver.py`). No SSRN 09 Combo, no cross-sectional rank book, no AVWAP/ranked weekly book in this file.

| Book | Meaning |
|------|---------|
| `donchian_nb08` | Daily Donchian 08 weights, equal-weight across universe |
| `carver` | Full Carver forecast weights per name |
| `blend_50_50` | Per-name 50/50 Donchian + Carver |
| `gate` | Carver × 1{Donchian weight > 1%} |

Universe: `DEFAULT_UNIVERSE` (~11 liquid alts + BTC in panel). Costs 10 bps, `shift(1)`. OOS from `SPLIT.oos_start`.

CLI: `python -m research.trend_lab.run_donchian_nb08_carver`
"""),
    cell(False, SETUP),
    cell(False, """
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from research.trend_lab.allocation import blend_weights
from research.trend_lab.carver_book import carver_weight_panel
from research.trend_lab.data import DEFAULT_UNIVERSE, load_symbol
from research.trend_lab.donchian_combo import COST_BPS, EXEC_LAG, equal_weight_portfolio
from research.trend_lab.donchian_nb08 import Donchian08Params, donchian_nb08_weight_panel
from research.trend_lab.metrics import kpis_from_net
from research.trend_lab.protocol import SPLIT, WARMUP_BARS

START_CAP = 100_000.0
cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
p = Donchian08Params()
"""),
    cell(False, """
symbols = ["BTCUSDT"] + [s for s in DEFAULT_UNIVERSE if s != "BTCUSDT"]
ohlcv = {}
for sym in symbols:
    df, src = load_symbol(sym, "1d", start=date(2015, 1, 1))
    if len(df) >= WARMUP_BARS:
        ohlcv[sym] = df
        print(sym, len(df), src)
panel = pd.DataFrame({s: df["close"] for s, df in ohlcv.items()}).sort_index()
"""),
    cell(False, """
w_don = donchian_nb08_weight_panel(ohlcv, p).reindex(panel.index).fillna(0.0)
w_car = carver_weight_panel(panel, use_cs=True, ann_days=365)
w_blend = pd.DataFrame({s: blend_weights(w_car[s], w_don[s], mix=0.5) for s in panel.columns}, index=panel.index)
w_gate = w_car * (w_don > 0.01).astype(float)

books = {
    "donchian_nb08_eq": equal_weight_portfolio(w_don, panel),
    "carver_eq": equal_weight_portfolio(w_car, panel),
    "blend_50_50_eq": equal_weight_portfolio(w_blend, panel),
    "gate_carver_if_donchian_eq": equal_weight_portfolio(w_gate, panel),
}

def row(name, net):
    oos = net.loc[cut:].fillna(0.0)
    k = kpis_from_net(oos)
    return {"book": name, "oos_sharpe": k["sharpe"], "oos_cagr": k["cagr"],
            "oos_max_dd": k["max_dd"], "oos_pnl_100k": float(START_CAP * ((1 + oos).prod() - 1))}

tbl = pd.DataFrame([row(n, s) for n, s in books.items()]).sort_values("oos_sharpe", ascending=False)
display(tbl.round(4))
"""),
    cell(False, """
out = Path("/opt/cursor/artifacts/donchian_nb08_carver_results.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"params": p.__dict__, "results": tbl.to_dict(orient="records")}, indent=2, default=float))
print("wrote", out)
"""),
    cell(True, """## Donchian only @ ~10% max DD (prop dial)

**IS-only** search on ``target_vol_ann`` (2023 split held out). Channels unchanged (55/20). Not Carver.
"""),
    cell(False, """
from research.trend_lab.donchian_nb08 import dial_target_vol_for_dd

is_end = cut - pd.Timedelta(days=1)
vt_dd, net_dd = dial_target_vol_for_dd(ohlcv, panel, is_end=is_end, target_dd=-0.10)
p_dd = Donchian08Params(target_vol_ann=vt_dd)
k_is = kpis_from_net(net_dd.loc[:is_end])
k_oos = kpis_from_net(net_dd.loc[cut:])
print("chosen target_vol_ann (IS dial)", vt_dd)
display(pd.DataFrame({"IS_10pct_dial": k_is, "OOS": k_oos}).T.round(4))
print("OOS PnL $100k", round(START_CAP * ((1 + net_dd.loc[cut:].fillna(0)).prod() - 1), 0))
"""),
])

write("12_mentor_prop_hypothesis.ipynb", [
    cell(True, """# 12 — Mentor prop hypothesis (ensemble flag → Carver + canaries)

**Research only.** Tests the Bootcamp / Carver **deployment model** for prop firms (FTMO-style), not a live playbook.

## Mentor model (what we pre-register)

1. **Timing (M1):** binary **ensemble** (`spot_signal`) or **Donchian** breakout **flags** *when* to participate.
2. **Sizing (M2):** **Carver** continuous weights *how much* (vol-targeted).
3. **Basket:** **Decorrelated trio** BTC/QQQ/GLD (252d ann) vs **crypto-only** panel (365d ann) — **separate ledgers, never merged**.
4. **Macro:** simple **canaries** (QQQ/SPY, XLU/SPY) scale gross on the **trio** book only.
5. **Prop dial:** IS-only scale to **−8% max DD** proxy under 10% static loss / 5% daily loss.

## Hypotheses

| Id | Claim |
|----|--------|
| H1 | Gated Carver (ensemble **or** Donchian flag) has **lower OOS max DD** than always-on equal-weight Carver on the same universe |
| H2 | Trio ranked Carver shows **meaningful CS diversification** vs crypto-only (different DD/Corr — not higher Sharpe guaranteed) |
| H3 | **Mentor stack** `flag × Carver` on crypto beats always-on Carver on **FTMO proxy** (DD + worst day) at lower CAGR |
| H4 | Canary gross multiplier on trio **reduces OOS DD** vs unscaled trio Carver |
| H5 | After IS dial, report **days to +10%** on OOS for eval timeline (not a pass guarantee) |

Split: IS through `SPLIT.is_end`, OOS from `SPLIT.oos_start`. No tuning on OOS.
"""),
    cell(False, SETUP),
    cell(False, """
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from IPython.display import display

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
"""),
    cell(True, """## A — Crypto ledger (365d, Vision alts + BTC in panel)"""),
    cell(False, """
symbols = ["BTCUSDT"] + [s for s in DEFAULT_UNIVERSE if s != "BTCUSDT"]
ohlcv_c = {}
for sym in symbols:
    df, src = load_symbol(sym, "1d", start=date(2015, 1, 1))
    if len(df) >= WARMUP_BARS:
        ohlcv_c[sym] = df
        print(sym, len(df), src)
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
"""),
    cell(False, """
def eval_row(name: str, net: pd.Series, *, dial: bool = True) -> dict:
    net = net.fillna(0.0)
    sc, scaled = dial_return_scale_is(net, is_end) if dial else (1.0, net)
    oos = scaled.loc[cut:]
    k = kpis_from_net(oos)
    fd = ftmo_daily_stats(oos)
    d10 = days_to_profit_pct(oos, 0.10)
    return {
        "ledger": "crypto",
        "book": name,
        "is_scale": sc,
        "oos_sharpe": k["sharpe"],
        "oos_cagr": k["cagr"],
        "oos_max_dd": k["max_dd"],
        "oos_pnl_100k": float(START_CAP * ((1 + oos).prod() - 1)),
        "oos_days_to_10pct": d10,
        "ftmo_10pct_ok": k["max_dd"] > FTMO_MAX_DD,
        **fd,
    }

rows_c = [eval_row(n, s) for n, s in books_c.items()]
tbl_c = pd.DataFrame(rows_c).sort_values("oos_max_dd", ascending=False)
display(tbl_c.round(4))
h1 = (
    tbl_c.loc[tbl_c["book"] == "carver_always_on", "oos_max_dd"].iloc[0]
    > tbl_c.loc[tbl_c["book"] == "mentor_ensemble_x_carver", "oos_max_dd"].iloc[0]
)
print("H1 ensemble gate improves DD vs always-on Carver:", h1)
"""),
    cell(True, """## B — Trio ledger (BTC / QQQ / GLD, 252d, separate from crypto)"""),
    cell(False, """
panel_t, src_t = mixed_panel()
is_p = panel_t.loc[:is_end]
raw_w_t = carver_weight_panel(panel_t, use_cs=True, ann_days=ANN_SESSIONS)
picked = pick_vol_target(is_p, raw_w_t.reindex(is_p.index).fillna(0.0), lookback=60, top_n=2)
params = BookParams(vol_target=picked["vol_target"], lookback=60, top_n=2, cost_bps=2.0)
book_t = book_from_raw_weights(panel_t, raw_w_t, params)["net"]

# Ensemble flags on trio (close-only OHLCV proxy for Donchian on ETFs)
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
w_gate_t = mentor_gated_weights(w_car_t, flags_t)
net_gate_t = equal_weight_portfolio(w_gate_t, panel_t, cost_bps=2.0)

books_t = {"trio_ranked_carver": book_t, "trio_mentor_ensemble_x_carver": net_gate_t}
rows_t = [eval_row(n, s) | {"ledger": "trio"} for n, s in books_t.items()]
tbl_t = pd.DataFrame(rows_t)
display(tbl_t.round(4))
"""),
    cell(True, """## C — Canaries on trio (macro gross multiplier)"""),
    cell(False, """
spy, _ = load_etf("SPY")
qqq, _ = load_etf("QQQ")
xlu, _ = load_etf("XLU")
mult = canary_defensive_multiplier(spy, qqq, xlu).reindex(panel_t.index).ffill().fillna(1.0)
w_canary = apply_gross_multiplier(w_car_t, mult)
net_canary = equal_weight_portfolio(w_canary, panel_t, cost_bps=2.0)
row_can = eval_row("trio_carver_x_canary", net_canary) | {"ledger": "trio"}
display(pd.DataFrame([row_can]).round(4))
h4 = row_can["oos_max_dd"] > tbl_t.loc[tbl_t["book"] == "trio_ranked_carver", "oos_max_dd"].iloc[0]
print("H4 canary improves DD vs ranked Carver:", h4)
"""),
    cell(True, """## D — Combined hypothesis board + artifact"""),
    cell(False, """
all_rows = rows_c + rows_t + [row_can]
board = pd.DataFrame(all_rows)
board["recommended_prop"] = board["ftmo_10pct_ok"] & (board["worst_daily_loss_pct"] > -0.05)
display(board.sort_values(["recommended_prop", "oos_cagr"], ascending=[False, False]).round(4))

payload = {
    "mentor_model": "ensemble_or_donchian_flag_x_carver_size",
    "hypotheses": {"H1_ensemble_gate_dd": bool(h1), "H4_canary_dd": bool(h4)},
    "ledgers_separate": ["crypto", "trio"],
    "sources_trio": src_t,
    "results": board.to_dict(orient="records"),
}
out = Path("/opt/cursor/artifacts/mentor_prop_hypothesis.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2, default=float))
print("wrote", out)
"""),
    cell(True, """## Readout

- **Mentor prop** = **flag → Carver**, not Donchian-only or Carver-only by default.
- Compare **crypto** rows to **trio** rows separately; do not sum PnL.
- **`oos_days_to_10pct`** is bars from OOS start on the **scaled** book — see notebook 12 / FTMO runner for rolling pass time.
- Re-run: execute all cells, or `python -m research.trend_lab.run_mentor_prop_hypothesis`, or regenerate via `python research/notebooks/_build.py`.
"""),
])

write("14_us100_canary_stock_momentum.ipynb", [
    cell(True, """# 14 — US100 canary × S&P momentum (validation)

**Idea:** When **US100** ( **QQQ** proxy ) is in a bull regime (**> SMA200** and **Donchian breakout**), allow a **top-10 monthly momentum** book on **current S&P 500** members. When canary is off, stock gross = 0.

**Compare:**
- Ungated top-10 momentum
- Per-stock **> SMA200** filter (rotation style)
- US100 canary gated (both / Donchian-only / SMA200-only)

**Honesty:** Survivorship-biased index membership; not prop-safe at full gross. Research only.

CLI: `python -m research.trend_lab.run_us100_canary_validation`
"""),
    cell(False, SETUP),
    cell(False, """
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
from IPython.display import display

from research.trend_lab.data import load_etf
from research.trend_lab.equity_universe import load_equity_panel, sp500_tickers
from research.trend_lab.metrics import kpis_from_net
from research.trend_lab.momentum_rotation import RotationParams, monthly_top_momentum_weights, rotation_net_returns
from research.trend_lab.protocol import SPLIT
from research.trend_lab.us100_canary import us100_bull_canary

cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
is_end = cut - pd.Timedelta(days=1)
"""),
    cell(False, """
panel, _ = load_equity_panel(sp500_tickers(), start=date(2015, 1, 1))
qqq, qsrc = load_etf("QQQ")
qqq = qqq.reindex(panel.index).ffill()
canary = us100_bull_canary(qqq, mode="both")
print("stocks", panel.shape[1], "bars", len(panel), "QQQ", qsrc)
print("OOS canary ON %", round(float(canary.loc[cut:].mean()) * 100, 1))
"""),
    cell(False, """
def gated_net(panel, canary, p):
    w = monthly_top_momentum_weights(panel, p)
    mult = canary.reindex(panel.index).ffill().fillna(0.0)
    return rotation_net_returns(panel, w.mul(mult, axis=0), p)

p = RotationParams(top_n=10, use_sma200_filter=False)
p_stk = RotationParams(top_n=10, use_sma200_filter=True)
books = {
    "ungated": rotation_net_returns(panel, monthly_top_momentum_weights(panel, p), p),
    "per_stock_sma200": rotation_net_returns(panel, monthly_top_momentum_weights(panel, p_stk), p_stk),
    "us100_canary_both": gated_net(panel, canary, p),
    "us100_donchian_only": gated_net(panel, us100_bull_canary(qqq, mode="donchian"), p),
}
spy = load_etf("SPY")[0].reindex(panel.index).ffill().pct_change(fill_method=None).fillna(0.0)
books["SPY"] = spy
"""),
    cell(False, """
rows = []
for name, net in books.items():
    for label, sl in [("IS", net.loc[:is_end]), ("OOS", net.loc[cut:])]:
        rows.append({"book": name, "slice": label, **kpis_from_net(sl)})
tbl = pd.DataFrame(rows)
display(tbl[tbl["slice"] == "OOS"].set_index("book").round(4))
out = Path("/opt/cursor/artifacts/us100_canary_validation.json")
out.write_text(json.dumps({"results": rows}, indent=2, default=float))
print("wrote", out)
"""),
    cell(True, """## Readout

- **Raw OOS max DD ~−16%** on the strict canary book **fails** FTMO **10%** static max loss — canary alone is **not** prop-compliant.
- Apply **IS-only return scale** (see `run_us100_canary_validation` **OOS_prop_dial**): at **~0.18×** the gated book sits **~−3% OOS DD** but **~2.4% OOS CAGR** — safe, **slow** eval.
- For **quick prop**, use **US100/XAU/BTC Carver** (trio), not full-size stock momentum; use this sleeve as **regime-signed overlay** at **dialed** gross.
- Do **not** merge with trio Carver without separate vol budgets.
"""),
])

write("15_tema_macd_prop_grid.ipynb", [
    cell(True, """# 15 — TEMA + MACD prop grid (QQQ / GLD / BTC)

**Research only.** Brute-force **IS** grid maximizing **Calmar** with **max DD ≥ −10%** (FTMO static loss proxy).
**OOS 2023→** is never used to pick parameters.

- **Daily** bars; **1× leverage**, **1% risk/trade** compounding on $100k (`tema_macd_prop.py`).
- **MACD histogram > 0** gate optional per grid cell.
- **Not** live QMIE 4h TEMA 9/90/199 — do **not** promote grid winners to `scanner/signal_engine.py` without walk-forward + Pine parity review.

## Prop readout

After grid: check OOS **max_dd**, **worst_daily_loss_pct**, **calmar**. Tighten `max_dd_floor` to **−0.08** for buffer under 10% firm max loss.
"""),
    cell(False, SETUP),
    cell(False, """
from dataclasses import asdict
from pathlib import Path
import json

import pandas as pd

from research.trend_lab.protocol import SPLIT
from research.trend_lab.tema_macd_prop import (
    ANN_PROP,
    PROP_START_EQ,
    TemaMacdParams,
    brute_force_calmar_is,
    eval_tema_macd_prop,
    ftmo_proxy,
    load_trio_daily_ohlcv,
)

is_end = pd.Timestamp(SPLIT.is_end, tz="UTC")
cut = pd.Timestamp(SPLIT.oos_start, tz="UTC")
MAX_DD_FLOOR = -0.10
QUICK = True  # set False for larger grid (~2k combos / symbol)

ohlcv, sources = load_trio_daily_ohlcv()
print("sources", sources)
for k, df in ohlcv.items():
    print(k, df.index[0].date(), "→", df.index[-1].date(), len(df))
"""),
    cell(False, """
grid_rows = {}
best_params = {}
for sym, df in ohlcv.items():
    table, best = brute_force_calmar_is(
        df, is_end=is_end, quick=QUICK, max_dd_floor=MAX_DD_FLOOR, min_trades=8,
    )
    grid_rows[sym] = table
    best_params[sym] = best
    print(f"\\n=== {sym} IS grid top 5 (Calmar) ===")
    if table.empty:
        print("no combo passed filters")
        continue
    cols = ["calmar", "sharpe", "cagr", "max_dd", "n_trades", "use_macd", "fast", "mid", "slow", "sl_atr", "tp_atr", "min_adx"]
    print(table.head(5)[cols].to_string(index=False))
"""),
    cell(False, """
results = []
for sym, df in ohlcv.items():
    p = best_params[sym]
    if p is None:
        continue
    ev = eval_tema_macd_prop(df, p, is_end=is_end, ann=ANN_PROP)
    for slice_name, k in [("IS", ev["is"]), ("OOS", ev["oos"])]:
        fp = ftmo_proxy(ev["net"].loc[:is_end] if slice_name == "IS" else ev["net"].loc[cut:])
        results.append({
            "symbol": sym,
            "slice": slice_name,
            **k,
            **fp,
            "n_trades": ev["n_trades_full"],
            "params": ev["params"],
        })
res = pd.DataFrame(results)
display(res.drop(columns=["params"], errors="ignore").round(4))
"""),
    cell(False, """
# Equal-weight portfolio of daily nets (research ledger)
nets = []
for sym, df in ohlcv.items():
    p = best_params[sym]
    if p is None:
        continue
    ev = eval_tema_macd_prop(df, p, is_end=is_end)
    nets.append(ev["net"].rename(sym))
if nets:
    port = pd.concat(nets, axis=1).fillna(0.0).mean(axis=1)
    from research.trend_lab.metrics import kpis_from_net
    for label, sl in [("IS", port.loc[:is_end]), ("OOS", port.loc[cut:])]:
        k = kpis_from_net(sl, ann=ANN_PROP)
        fp = ftmo_proxy(sl)
        print(label, {**k, **fp})
"""),
    cell(False, """
out = Path("/opt/cursor/artifacts/tema_macd_prop_grid.json")
payload = {
    "protocol": {"is_end": str(is_end.date()), "oos_start": str(cut.date()), "max_dd_floor": MAX_DD_FLOOR},
    "sources": sources,
    "best_params": {k: asdict(v) for k, v in best_params.items() if v is not None},
    "results": results,
    "grid_top10": {k: v.head(10).to_dict(orient="records") for k, v in grid_rows.items() if not v.empty},
}
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2, default=float))
print("wrote", out)
"""),
    cell(True, """## Notes

- **Overfitting:** Calmar on IS with many knobs — always read **OOS** and walk-forward before prop.
- **ETF OHLC** is synthetic from close; BTC uses Vision OHLC.
- **TradingView:** export best params per symbol into Pine alerts (TEMA stack + MACD hist); no auto parity with this notebook until scripted.
- **vs trio Carver:** this is **discrete TEMA+MACD tickets**; Carver is **continuous vol book** — separate ledgers.
"""),
])
