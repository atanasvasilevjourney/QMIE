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
/workspace/.venv/bin/pytest tests/research/test_trend_lab.py -q
/workspace/.venv/bin/python -m research.trend_lab.run_lab --quick
```

Notebooks (from `python/`, kernel with `python/` on `sys.path`):

- `research/notebooks/01_crypto_trend_lab.ipynb` — data, spot, TEMA, Optuna, Boruta, DF
- `research/notebooks/02_carver_vs_ensemble.ipynb` — sizing vs timing, vol dial, blend
- `research/notebooks/04_carver_btc_qqq_gld.ipynb` — ranked Carver on BTC/QQQ/GLD, ~10% DD dial, Sharpe 1.4–1.5 goal + walk-forward

Artifacts: `python/research/artifacts/` and `/opt/cursor/artifacts/`.

Ranked Carver book (BTC / QQQ / GLD):

```bash
cd /workspace/python
/workspace/.venv/bin/python -m research.trend_lab.run_carver_book
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

Hypothesis board: H1 PARTIAL (tighter DD than BH, worse Sharpe). H2 HOLD. H3 INCONCLUSIVE (Optuna TEMA OOS Sharpe 0.34 vs frozen 0.33 — do not promote). H4 REJECT (AND-confluence hurt). H5 PARTIAL (Carver tighter DD; CAGR was *not* lower this bull OOS). H6 HOLD (chop gate). H7 HOLD (ranked top-3).

DF neighborhood on inner-IS (2022 winter): Optuna neighbors did not clear a Sharpe≥0.5 pool with positive val Sharpe. That is the overfit warning even when 2023–26 OOS later looked fine.
