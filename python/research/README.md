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
- `research/notebooks/03_portfolio_kpis.ipynb` — ranked book, DD KPIs, hypothesis board

Artifacts: `python/research/artifacts/` and `/opt/cursor/artifacts/`.

## Promote-to-live rule

IS Sharpe **and** DF neighborhood (inner-IS val Sharpe std) **and** OOS
holdout. Never promote from a reverse split. Never change Pine / `W_*`
from this lab.
