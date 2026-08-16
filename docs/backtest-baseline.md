# QMIE Backtest Baseline (Sprint 1 — frozen OOS)

**Run date:** 2026-08-16  
**Harness:** `python -m backtest.run` (same `compute_signal` as live; no weight search)  
**Decision:** A/A+ clear the Sprint 1 gate → **proceed to Sprint 2**. Do **not** retune `W_*` on this sample.

---

## Command (reproduce)

```bash
cd python
python -m backtest.run \
  --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT DOGEUSDT ADAUSDT AVAXUSDT LINKUSDT DOTUSDT \
  --tf 1h 4h \
  --start 2024-01-01 \
  --end 2026-08-15 \
  --split 2025-01-01 \
  --min-adx 20 \
  --min-atr-pct 0.4 \
  --max-atr-pct 4.0
```

| Knob | Value | Why |
|---|---|---|
| Symbols | 10 default USDT-M names | Matches CLI defaults / Sprint 1 plan |
| Timeframes | `1h`, `4h` | Live scanner defaults |
| Window | 2024-01-01 → 2026-08-15 | ~2.6y of Binance Vision monthly klines |
| Split | `2025-01-01` | IS = calendar 2024; OOS = 2025-01-01 onward |
| Filters | ADX ≥ 20, ATR% ∈ [0.4, 4.0] | Sweet-spot gates (not the wide live defaults 0.10–8.0) |
| Engine | Frozen 7-component weights (sum 100) | No hyperopt on this sample |

Outcome model: first touch of fixed TP or SL within 100 bars (same-bar both → LOSS).  
RR at signal is ~1.67 (engine TP/SL geometry). Trailing-stop columns are a secondary view on the *same* signals.

Raw (pre-filter) signals: **112,496**. After ATR+ADX filters: **90,590**.  
Elapsed wall time for this run: **~68 min** (cold cache downloads from `data.binance.vision`).

Parquet output is local-only (`python/backtest/results/`, gitignored). Do not commit it.

---

## In-sample (< 2025-01-01) — 33,929 signals

| Grade | Signals | Closed | Win % | Avg RR | Expectancy R | Prof.Factor | SQN | Sharpe | Sortino | Max DD R | Avg MAE | Avg MFE | Avg bars |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A+ | 1665 | 1662 | 38.6% | 1.67 | **+0.030** | 1.05 | 0.95 | 0.39 | 0.64 | -117.6 | 0.98 | 1.23 | 10.5 |
| A | 4380 | 4373 | 43.1% | 1.67 | **+0.149** | 1.26 | 7.46 | 1.86 | 4.33 | -129.5 | 0.92 | 1.30 | 11.6 |
| B | 12441 | 12423 | 42.4% | 1.67 | +0.131 | 1.23 | 11.04 | 2.51 | 5.61 | -204.2 | 0.94 | 1.28 | 11.0 |
| C | 15443 | 15417 | 41.8% | 1.67 | +0.115 | 1.20 | 10.83 | 2.49 | 4.90 | -421.2 | 0.95 | 1.25 | 11.6 |

ATR-trailing stop (same signals):

| Grade | Closed | Trail Win % | Trail E[R] | Avg bars |
|---|---:|---:|---:|---:|
| A+ | 1665 | 38.7% | +0.069 | 5.7 |
| A | 4380 | 43.9% | +0.131 | 6.4 |
| B | 12441 | 41.3% | +0.126 | 6.1 |
| C | 15443 | 40.2% | +0.078 | 6.5 |

---

## Out-of-sample (≥ 2025-01-01) — 56,661 signals  ← **frozen decision table**

| Grade | Signals | Closed | Win % | Avg RR | Expectancy R | Prof.Factor | SQN | Sharpe | Sortino | Max DD R | Avg MAE | Avg MFE | Avg bars |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A+ | 2966 | 2959 | 44.7% | 1.67 | **+0.193** | **1.35** | 7.93 | 1.75 | 3.80 | -131.0 | 0.90 | 1.29 | 9.9 |
| A | 7809 | 7789 | 44.5% | 1.67 | **+0.187** | **1.34** | 12.48 | 2.00 | 5.04 | -201.6 | 0.88 | 1.30 | 10.9 |
| B | 21237 | 21194 | 41.7% | 1.67 | +0.113 | 1.19 | 12.51 | 1.80 | 3.96 | -461.9 | 0.94 | 1.27 | 10.7 |
| C | 24649 | 24587 | 38.5% | 1.67 | +0.028 | 1.04 | 3.33 | 0.55 | 0.96 | -789.4 | 0.98 | 1.19 | 11.1 |

ATR-trailing stop (same signals):

| Grade | Closed | Trail Win % | Trail E[R] | Avg bars |
|---|---:|---:|---:|---:|
| A+ | 2964 | 42.6% | +0.110 | 5.7 |
| A | 7807 | 44.3% | +0.155 | 6.0 |
| B | 21232 | 40.8% | +0.102 | 6.1 |
| C | 24621 | 38.5% | +0.054 | 6.7 |

### OOS A/A+ by timeframe

| TF | Closed | Win % | Expectancy R |
|---|---:|---:|---:|
| 1h | 9169 | 42.9% | +0.145 |
| 4h | 1579 | **54.3%** | **+0.448** |

4H carries most of the edge. 1H is still positive but noisier and dominates the alert count.

---

## Sprint 1 decision gate

From `docs/development-status.md`:

| Gate | Result |
|---|---|
| A/A+ OOS expectancy > 0 | Yes (A+ **+0.193**, A **+0.187**) |
| A/A+ OOS PF ≥ 1.3 | Yes (A+ **1.35**, A **1.34**) |
| A/A+ beat C on OOS | Yes (C E[R] **+0.028**, PF **1.04**) |

**Verdict: proceed to Sprint 2** (live journal loop / drift vs this baseline).  
**Do not** retune scoring weights on this sample. Ribbon / structure / sweep stay cut.

### Suggested live follow-ups (operator, not automatic)

1. Set `JOURNAL_OOS_WIN_PCT` ≈ **44.5** (blended OOS A/A+ win rate) once ≥ 30 closed journal fills exist, so drift alerts have a baseline.
2. Consider aligning live `SCAN_MIN_ALERT_GRADE` / ATR / ADX defaults with the filters that were actually measured (`min-adx 20`, ATR% 0.4–4.0) — today `strategy/baseline.yaml` still has `sig_min_adx: 0.0` and wider ATR.
3. Prefer **4H** for discretionary size when both TFs fire; treat 1H as higher-frequency confirmation / smaller weight.

### Caveats

- Max DD in R-units is large because this is an unlevered firehose of *every* A/A+/B/C signal, not the ranked swing book (`ALLOC_MODE=ranked`). Live alert count is much smaller.
- OOS win% (~44–45% for A/A+) is below `strategy/goals.yaml` `success.min_win_pct` (48). The Sprint 1 gate is expectancy + PF, not that goal. Expectancy clears because RR ≈ 1.67.
- Historical data source is Binance Vision (`data.binance.vision`), not the live fapi REST path. Same symbols/TFs; different delivery.
- IS A+ was weak (+0.030 E[R]); OOS A+ improved. That is evidence of sample noise, not a license to fit weights to OOS.
