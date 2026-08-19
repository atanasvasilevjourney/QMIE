# QMIE frozen walk-forward — Triple EMA 9/90/199

Sprint 1 measurement of the **live scoring math** (not a parameter search).
Parquet stays local (`python/backtest/results/`, gitignored). This file is
the canonical table.

**Do not retune `W_*` or EMA lengths on this sample.** The one-variable
proposal is in [`strategy/reviews/2026-08-17.md`](../strategy/reviews/2026-08-17.md)
(first freeze) and [`strategy/reviews/2026-08-19.md`](../strategy/reviews/2026-08-19.md)
(re-print; same knob, still not applied).

## Engine identity

| Field | Value |
|---|---|
| Engine | 7-component score, weights 20 / 15 / 15 / 15 / 20 / 10 / 5 |
| Stack | Triple EMA **9 / 90 / 199** (`W_SUPERTREND`); close vs EMA199 (`W_EMA`) |
| Other votes | RSI(14), ADX/DMI(14), HTF TMA, S/R ATR room, ATR% bonus |
| Commit | `88d93cb` (`feat: replace Supertrend + EMA200 with Triple EMA 9/90/199`) |
| Outcome model | First touch of info-only SL 1.5×ATR or TP 2.5×ATR, max 100 bars |
| Data | Binance Vision USDT-M monthly klines (not live `fapi`) |

Supertrend-era numbers from an earlier window are **not** comparable
unless that engine is re-run from its own commit. Do not mix them into
this table.

## Command (frozen)

```bash
cd python
pip install -r requirements.txt -r backtest/requirements.txt
python -m backtest.run \
  --start 2024-01-01 --end 2026-08-18 --split 2025-01-01 \
  --min-adx 20 --min-atr-pct 0.4 --max-atr-pct 4.0
```

`--end` defaults to yesterday. August 2026 Vision monthly zips were
unpublished at run time, so last bar in the parquet is **2026-07-31**.

Defaults: 10 USDT-M names (`BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT
DOGEUSDT ADAUSDT AVAXUSDT LINKUSDT DOTUSDT`), TFs `1h` `4h`.

| Run | 2026-08-17 | 2026-08-19 re-print |
|---|---|---|
| CLI `--end` | yesterday (2026-08-16) | 2026-08-18 |
| Data last bar | 2026-07-31 | 2026-07-31 (Aug zip still unpublished) |
| Split | IS `< 2025-01-01` · OOS `≥ 2025-01-01` | same |
| Post-filters | ATR% 0.4–4.0, then ADX ≥ 20 | same |
| Raw signals | 137,592 | **137,592 (identical)** |
| After ATR | 132,989 (−4,603) | same |
| After ADX | 96,146 (−36,843) | same |
| Runtime | 2030 s | 2018 s |
| Parquet (gitignored) | `backtest_20260817_155852.parquet` | `backtest_20260819_114324.parquet` |

IS/OOS grade tables, 1h vs 4h slices, and gate ablation **matched bit-for-bit**
on the re-print (same Vision months, same TMA engine at `88d93cb`). Tables
below are that frozen sample.

Live `.env` at measurement time still used wider gates
(`SIG_MIN_ADX=0`, `SIG_MIN_ATR_PCT=0.10`, `SIG_MAX_ATR_PCT=8.0`) and
`SCAN_TIMEFRAMES=1h,4h`. Tables below are the **measurement protocol**,
not the live defaults.

## In-sample (`< 2025-01-01`, gated)

36152 signals.

| Grade | Signals | Closed | Win % | Avg RR | Expectancy R | PF | SQN | Sharpe | Sortino | Max DD R | Avg bars |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A+ | 2113 | 2108 | 37.7% | 1.67 | +0.006 | 1.01 | 0.21 | 0.07 | 0.12 | −151.0 | 11.4 |
| A | 4673 | 4667 | 41.2% | 1.67 | +0.098 | 1.17 | 5.12 | 1.30 | 2.64 | −174.9 | 11.3 |
| B | 13534 | 13522 | 41.0% | 1.67 | +0.093 | 1.16 | 8.25 | 1.92 | 3.74 | −384.1 | 11.5 |
| C | 15832 | 15799 | 41.4% | 1.67 | +0.105 | 1.18 | 10.03 | 2.41 | 4.80 | −346.2 | 11.9 |
| **A/A+** | **6786** | **6775** | **40.1%** | 1.67 | **+0.070** | **1.12** | 4.38 | 0.96 | 1.91 | −312.5 | 11.3 |

IS ATR-trailing stop (same entries): A+ trail E[R] +0.068 · A +0.120 ·
B +0.064 · C +0.083. Trail does not beat fixed TP/SL on A/A+ enough to
change the engine.

## Out-of-sample (`≥ 2025-01-01`, gated)

59994 signals. This is the decision sample.

| Grade | Signals | Closed | Win % | Avg RR | Expectancy R | PF | SQN | Sharpe | Sortino | Max DD R | Avg bars |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A+ | 4034 | 4024 | 40.0% | 1.67 | +0.066 | 1.11 | 3.22 | 0.64 | 1.20 | −205.7 | 11.1 |
| A | 8736 | 8720 | 43.0% | 1.67 | +0.147 | 1.26 | 10.41 | 1.53 | 3.66 | −295.2 | 11.2 |
| B | 23282 | 23205 | 39.4% | 1.67 | +0.051 | 1.08 | 5.99 | 0.88 | 1.68 | −671.9 | 10.9 |
| C | 23942 | 23860 | 39.3% | 1.67 | +0.047 | 1.08 | 5.60 | 0.99 | 1.71 | −662.1 | 11.3 |
| **A/A+** | **12770** | **12744** | **42.1%** | 1.67 | **+0.122** | **1.21** | 10.44 | 1.30 | 2.96 | −416.3 | 11.1 |

OOS ATR-trailing stop: A+ trail E[R] +0.023 · A +0.119 · B +0.063 ·
C +0.047. Fixed 1.5 / 2.5 ATR stays the info-only model.

### Sprint 1 gate (combined 1h+4h)

Declared in [`docs/development-status.md`](development-status.md):

- A/A+ OOS expectancy **> 0**: yes (**+0.122**)
- A/A+ beats C: yes (**+0.122 vs +0.047**; PF 1.21 vs 1.08)
- A/A+ OOS PF **≥ 1.3**: **no** (1.21)

Grading hypothesis is **directionally supported** (A is the best letter;
A/A+ beats C). A+ is **worse than A** — do not raise `SCAN_MIN_ALERT_GRADE`
to `A+`. Combined PF misses the 1.3 bar because **1h volume dominates**.

Vs [`strategy/goals.yaml`](../strategy/goals.yaml) on combined A/A+ OOS:
win 42.1% < 48 · E[R] +0.122 < 0.15 · Sharpe 1.30 ≥ 1.0 · DD is in R
units, not account %.

## 1h vs 4h (gated OOS) — the actual lever

| Slice | A/A+ closed | Win % | E[R] | PF | Sharpe |
|---|---:|---:|---:|---:|---:|
| **4h A/A+** | 2152 | **49.1%** | **+0.309** | **1.61** | **2.09** |
| 4h A | 1498 | 51.3% | +0.367 | 1.75 | 2.37 |
| 4h A+ | 654 | 44.0% | +0.174 | 1.31 | 0.96 |
| 4h C | 4511 | 38.6% | +0.030 | 1.05 | 0.41 |
| 1h A/A+ | 10592 | 40.6% | +0.084 | 1.14 | 0.89 |
| 1h C | 19349 | 39.4% | +0.051 | 1.08 | 1.00 |

4h A/A+ **passes** the Sprint 1 gate (E[R] > 0, PF ≥ 1.3, beats C) and
clears the numeric goals on win / E[R] / Sharpe. 1h A/A+ does not
(PF 1.14, win 40.6%, Sharpe 0.89) and is ~5× the 4h sample, so it
pulls the pooled PF under 1.3.

IS 4h A/A+ was weak (559 closed, E[R] +0.035, PF 1.06) with a tiny A+
n. That is why the split exists: we do **not** pick 4h from IS. The
frozen OOS is the decision.

## Gate ablation (A/A+ OOS only, not a new engine)

Post-filters on the same collected signals:

| Filter | Closed | Win % | E[R] | PF |
|---|---:|---:|---:|---:|
| Ungated (live-wide) | 15102 | 41.0% | +0.094 | 1.16 |
| ATR% 0.4–4.0 only | 14778 | 41.4% | +0.103 | 1.18 |
| ADX ≥ 20 only | 13061 | 41.6% | +0.110 | 1.19 |
| ATR + ADX (canonical) | 12744 | 42.1% | +0.122 | 1.21 |
| 4h ungated A/A+ | 2656 | 45.8% | +0.222 | 1.41 |
| 4h canonical A/A+ | 2152 | 49.1% | +0.309 | 1.61 |

ADX ≥ 20 and the ATR band help, but they are **smaller** than dropping
1h. Next cycle may take `sig_min_adx 0 → 20` after the timeframe knob
is measured live. **Do not change both in the same cycle.**

## Decision

1. Stop adding score components. Do not put ribbon / structure / sweep
   / Supertrend back. Do not import TQQQ notebook periods.
2. Combined 1h+4h A/A+ is a weak pass on expectancy and a fail on PF 1.3.
3. **One knob:** `SCAN_TIMEFRAMES` `1h,4h` → `4h`. See the review file.
   Not applied in this change (`.env` untouched).
4. After that knob is live, set `JOURNAL_OOS_WIN_PCT=49.1` (4h A/A+ OOS
   win rate) so drift alerts have a frozen baseline. Until then leave it
   unset, or use 42.1 if 1h stays on.

Reproduce slices from `python/backtest/results/latest.parquet` with the
same ATR/ADX cuts; do not commit that file.
