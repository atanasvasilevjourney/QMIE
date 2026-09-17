# Crypto trend lab (research only)

QMIE stays a **signal-only** scanner. This package does not dispatch alerts,
does not retune live `W_*`, and does not send leverage to a venue.
Frozen live TEMA stack remains **9 / 90 / 199**. Optuna winners stay in
this lab until a second holdout + DF neighborhood both clear — they are
never written into `scanner/signal_engine.py`.

## Protocol

The operator asked for “2018–2023 OOS, 2023→now IS”. That **trains on the
future**. The lab inverts it:

| Slice | Window | Use |
|---|---|---|
| IS (fit) | 2019-09-01 → 2022-12-31 | grid, Optuna, Boruta, DF neighborhood |
| Inner val | last 20% of IS | DF stability only |
| OOS | 2023-01-01 → today | never tune |

USDT-M Vision starts ~2019-09, not 2018. `WARMUP_BARS=220`. Held position
is `signal.shift(1)`. OOS indicators are seeded with the last 220 IS bars.

## Two approaches

1. **Spot book (radar / daily expansion analog)** — 1D, leverage 1. Fast EMA
   above slow EMA, prior-window Donchian breakout, ADX/+DI, RSI cap,
   optional KAMA/MACD/z-score/ALMA AND-gates. Prior-box stay-in. No ATR TP.
2. **4h TEMA 10x isolated** — frozen 9/90/199, agreement `>= 1`, SL 1.5×ATR /
   TP 2.5×ATR, same-bar both → SL, loss capped at stake.

Plus **Carver** continuous vol-targeted sizing vs the binary ensemble, a
blend, an ADX chop gate, a causal DD circuit breaker, and a ranked top-N
spot book (lookback ROC, cluster_max=1).

## Run

```bash
cd /workspace/python
/workspace/.venv/bin/pip install -r research/requirements.txt   # sklearn, optuna, plotly
/workspace/.venv/bin/pytest tests/research/ -q
/workspace/.venv/bin/python -m research.trend_lab.run_lab --quick
```

Notebooks (from `python/`, kernel with `python/` on `sys.path`):

- `research/notebooks/01_crypto_trend_lab.ipynb` — data, spot, TEMA, Optuna, Boruta, DF
- `research/notebooks/02_carver_vs_ensemble.ipynb` — sizing vs timing, vol dial, blend
- `research/notebooks/03_portfolio_kpis.ipynb` — ranked spot book + hypothesis board
- `research/notebooks/04_carver_btc_qqq_gld.ipynb` — ranked Carver on BTC/QQQ/GLD, ~10% DD dial
- `research/notebooks/05_tema_validation.ipynb` — frozen 4h TEMA equity, honest DD, daily-marked KPIs
- `research/notebooks/06_tema_robustness_sensitivity.ipynb` — walk-forward, DF neighborhood, SL/TP and ADX/ATR grids (IS only)
- `research/notebooks/07_tema_carver_sizing.ipynb` — Carver as a lagged sizer on frozen TEMA tickets

Artifacts: `python/research/artifacts/` and `/opt/cursor/artifacts/`.

Ranked Carver book (BTC / QQQ / GLD):

```bash
cd /workspace/python
/workspace/.venv/bin/python -m research.trend_lab.run_carver_book
```

TEMA-only lab (validation + robustness + Carver overlay). KPIs are
**daily-marked**. The `$10k+$100` DD is an artifact — read the 1%
compounding and full-wallet curves. Scale ref for Carver is mean lagged
weight at IS entries so OOS average stake ≈ binary.

```bash
cd /workspace/python
/workspace/.venv/bin/python -m research.trend_lab.run_tema_lab
```

## Promote-to-live rule

IS Sharpe **and** DF neighborhood (inner-IS val Sharpe std) **and** OOS
holdout. Never promote from a reverse split. Never change Pine / `W_*`
from this lab.

## Quick-run board (BTC, Vision native 1d/4h from 2020-01, OOS 2023→2026-08)

Not a license to retune the scanner. 1d archive starts 2020-01, not 2019-09.

| Book | OOS Sharpe | OOS CAGR | OOS max DD |
|---|---:|---:|---:|
| Buy-and-hold BTC | 1.03 | 45% | −53% |
| Spot baseline (EMA9/199 + Donchian + ADX) | 0.35 | 5% | −28% |
| Spot Optuna (IS-fit) | 0.82 | 16% | −24% |
| Spot + KAMA AND-gate | 0.22 | 2% | −29% |
| Carver vol-target 20% | 1.24 | 18% | −11% |
| 50/50 blend | 0.84 | 12% | −15% |
| Frozen TEMA 9/90/199 10× isolated | 0.33 | 1.8%* | −3.2%* |
| Frozen TEMA 1× | 0.33 | 0.2%* | −0.3%* |

\*TEMA CAGR/DD are on a $10k account with $100 isolated stake — not full-port. Expectancy $2.93 / trade at 10× vs $0.29 at 1×; 0 liquidations on this OOS. Same trade list, scaled.

## TEMA-only lab (daily-marked, BTC 4h, OOS 2023→2026-08)

Same frozen 9/90/199 book. `ann=365` on **daily** marks. 233 OOS trades, win 44.2%, E[R] $3.02, mean R +0.17, median R −1.0, 0 liquidations, ~12 bars hold.

| Book | OOS Sharpe | OOS CAGR | OOS max DD |
|---|---:|---:|---:|
| $10k + $100 isolated 10× | 0.85 | 1.9% | −3.2% |
| 1% compounding (same tickets) | 0.83 | 1.9% | −3.4% |
| 1× leverage, same tickets | 0.83 | 0.2% | −0.3% |
| Full isolated wallet (stake = 100% equity) | 0.81 | **−43%** | **−99.7%** |
| Binary TEMA (Carver overlay control) | 0.85 | 1.9% | −3.2% |
| Inverse-vol size (IS-normalized) | **0.94** | 2.5% | −3.0% |
| Daily Carver forecast size | 0.39 | 0.8% | −2.5% |
| 4h Carver forecast size | 0.10 | 0.2% | −5.4% |
| Skip if daily held < 0.05 | 0.53 | 0.9% | −2.1% |

Walk-forward (frozen params, $100 stake): 2021 Sharpe 0.18; **2022 −0.98** (still −2.7% DD on the tiny wallet); 2023 **1.77**; 2024–26 0.39. Inner-IS DF val Sharpe is **negative** around 9/90/199. IS SL/TP peak is 1.5/3.5 — do not promote a wider TP from IS.

H8 **ARTIFACT**: the −3% DD is a 1% wallet. Full-stake 10× is ruin (Kelly of this ticket is ~10% of bankroll; 100% is 10× Kelly). H9 **no-promote**: 2022 fold loses, DF val is negative. H10 **no-promote**: looser ADX and wider TP win IS only. H11 **PARTIAL**: inverse-vol can size the stake; Carver *forecast* corr(fc, trade ret) ≈ **−0.06**, hit 46% — do not ship Strat 17–19 onto TEMA.

Hypothesis board: H1 PARTIAL (tighter DD than BH, worse Sharpe). H2 HOLD. H3 INCONCLUSIVE (Optuna TEMA OOS Sharpe 0.34 vs frozen 0.33 — do not promote). H4 REJECT (AND-confluence hurt). H5 PARTIAL (Carver tighter DD; CAGR was *not* lower this bull OOS). H6 HOLD (chop gate). H7 HOLD (ranked top-3).

DF neighborhood on inner-IS (2022 winter): Optuna neighbors did not clear a Sharpe≥0.5 pool with positive val Sharpe. That is the overfit warning even when 2023–26 OOS later looked fine.
