# QMIE Code Review & Test Pass

## Audit findings

Five real issues, ordered by severity. Pure cosmetic / style nits omitted.

### 1. (HIGH) Triple-Supertrend dropped 2/3 majority signals silently

`signal_engine.py` and `quant_visualizer.pine` both required
`agreement >= 2` to score the Supertrend component. With three ±1
votes, the sum is in `{-3, -1, +1, +3}` — never ±2. So `>= 2` only
matched ±3 (all three agree). A 2/3 majority signal received a zero
Supertrend score, even though it was the engine's strongest single
component (weight=20).

**Fix:** Lowered the threshold to `>= 1` and scaled the contribution
by `|agreement|/3`. Now ±3 contributes 100% strength, ±1 contributes
33%. Applied symmetrically on Python and Pine sides so the visualizer
stays in lockstep. A regression test (`test_partial_supertrend_agreement_scored`)
pins the new behaviour.

### 2. (MEDIUM) RMA seeding diverged from Pine

`indicators.py` used `pandas.ewm(adjust=False, min_periods=length)`
which seeds with `x[0]`. Pine's `ta.rma` seeds with `SMA(0..length-1)`
at index `length-1`. The recurrences match, but the seed difference
propagates through the warmup window. Concrete measurement: ~0.23
divergence on the first valid bar, decayed to ~0.016 after 36 bars.

For live signals (we score bar 298 of a 300-bar window, fully
decayed), the impact is zero. For chart-history visual parity with
the Pine indicator, it's visible. Cheap to fix correctly.

**Fix:** Manual SMA-seeded recurrence in `rma()`. Unit tests pin the
exact values: `test_pine_seed_is_sma_of_first_window`,
`test_recurrence_matches_pine`.

### 3. (MEDIUM) No transient-error retry on the exchange client

A single Binance 503 (which happens) killed that symbol's scan pass.
With 30 symbols, even a 1% transient rate means a few symbols fail
silently per pass.

**Fix:** Single retry on 5xx / connection error / timeout, with 250ms
backoff. 4xx still raises immediately (real client errors).
Tests: `test_5xx_retries_once_then_succeeds`, `test_5xx_twice_raises`,
`test_4xx_raises_immediately`.

### 4. (MEDIUM) No config validators — bad envs ship silently

A typo'd `SCAN_MIN_ALERT_GRADE=AA` would log a warning at startup but
the rest of the system kept running with a default. Unbalanced weight
sums (e.g. someone bumps `W_SUPERTREND` from 20 → 40 without re-balancing
others) silently rescale the score axis.

**Fix:** `Settings.validate_runtime()` returns warnings for: weight sum
outside 95–105, busy-loop interval (<5s), invalid grade, invalid data
source. `main.py` lifespan logs them at startup. Tests:
`test_lopsided_weights_warns`, `test_invalid_grade_warns`, etc.

### 5. (LOW) Pine v6: discard variable `_` reused in same function scope

In `htfAgreementCalc()` I used `[_, dA] = ta.supertrend(...)` three
times. Pine v6 does not allow re-declaring `_` in the same scope —
each is a fresh variable but shadowing within a function body fails
to compile.

**Fix:** Unique discard names: `[_l1, dA]`, `[_l2, dB]`, `[_l3, dC]`.

### Other things checked, no fix needed

* **DB schema:** `idempotency_key TEXT NOT NULL UNIQUE` already
  auto-indexes. `recent_signals` orders by `id DESC` (PK = clustered).
  No DB scaling cliff at the current data volume.
* **Pydantic v2 `extra="allow"`:** does support attribute access
  (`getattr(model, "extra_field")`). The dual `getattr or model_dump.get`
  fallback in dispatcher/discord/telegram was dead code — simplified.
* **Idempotency atomicity:** asyncio is single-threaded; the
  `seen_or_mark` check-then-set is atomic by virtue of no `await`
  between check and set. Verified with `test_concurrent_same_key_only_one_wins`.
* **Bar-close week alignment:** `1w` bars in the schedule loop would
  align to Thursday UTC midnight (Unix epoch was Thursday) instead
  of the exchange's actual Sunday/Monday convention. We don't scan
  weekly — issue is moot for the current default config. Documented.
* **HTF stale data:** `fetch_klines` drops the last (in-progress)
  candle, so HTF data is always confirmed-only. No staleness risk.

---

## HTF Daily Trend Filter (2026-05-15)

Added a `daily_trend` field (`"bullish"` / `"bearish"` / `"unknown"`) to every
scan result, computed from EMA200 on 1D klines. Displayed as an informational
label in both Discord and Telegram alerts.

### What was built

| Component | Change |
|---|---|
| `scanner/signal_engine.py` | `daily_trend` field on `ScanResult`; `daily_df` param on `compute_signal()` |
| `scanner/scheduler.py` | Supplies `daily_df` in `scan_one()` — reuses `htf_df` for 4H scans (HTF=1D), fetches 1D separately for 1H scans |
| `scanner/dispatcher.py` | Injects `daily_trend` into `TVSignal` dict alongside `chart_url` |
| `notifiers/discord.py` | "Daily Trend" embed field after HTF |
| `notifiers/telegram.py` | "Daily Trend" line after HTF |

**Design:** EMA200 requires ≥ 200 rows — if `daily_df` is `None` or too short,
`daily_trend` stays `"unknown"` (safe default, never blocks an alert).

**9 new tests** added across `test_signal_engine.py`, `test_scheduler.py`, and
`test_dispatcher.py`. No regressions.

---

## Test suite

118 tests, organised by module. Run with `cd python && pytest`.

```
tests/test_indicators.py        24 tests   RMA/EMA/RSI/ADX/ATR/Supertrend/Pivots
tests/test_signal_engine.py     27 tests   scenarios + edge cases + grade thresholds + daily_trend
tests/test_scheduler.py         15 tests   bar-close detection, off-by-one prevention, daily_df routing
tests/test_dispatcher.py        13 tests   dedup, grade filter, TV deep link, daily_trend propagation
tests/test_exchange_clients.py  13 tests   parsing, in-progress drop, retry, errors
tests/test_security.py          12 tests   HMAC, age, idempotency
tests/test_config.py            10 tests   env parsing + validators
                                ─────
                                 118 passing
```

### Coverage

```
scanner/indicators.py        96%
scanner/signal_engine.py     90%
scanner/dispatcher.py        94%
scanner/exchange_clients.py  73%
scanner/scheduler.py         68%
config.py                    99%
security.py                  89%
models.py                    96%
TOTAL                        83%
```

Load-bearing modules (indicators / signal engine / dispatcher) above
90%. `main.py` is 0% because the FastAPI lifespan / endpoints would
need a `httpx.AsyncClient` test client — out of scope for this pass,
worth adding when there's reason to change the HTTP surface.

### What the tests pin

The most valuable kind of test is one that catches a real bug in the
future. Each module has at least one regression test:

* **Indicators:** SMA-seeded RMA values; ATR=0 on flat input; RSI
  bounded 0-100; Supertrend line below price in uptrend.
* **Signal engine:** SIDE matches regime; SL/TP geometry correct
  (R:R = tp_mult/sl_mult); HTF alignment doesn't lower score;
  partial-agreement scores non-zero (the bug fixed in this pass);
  `daily_trend` bullish/bearish/unknown boundary conditions.
* **Scheduler:** No scan inside the 5s grace window; no double-scan
  same closed bar; correct boundary alignment for 1h/4h; 4H scan
  reuses htf_df as daily_df; 1H scan fetches 1D separately.
* **Dispatcher:** Grade filtering; bar-close dedup; chart_url
  injection; failing notifier doesn't kill the others; `daily_trend`
  propagated to notifiers.
* **Exchange:** in-progress candle dropped on both Binance & Bybit;
  5xx retried once, 4xx raised; symbol `.P` suffix stripped.
* **Security:** valid HMAC passes, tampered body fails, future-dated
  timestamps rejected (anti-replay).

---

## Comparison to similar OSS projects

| Project | Focus | What QMIE has that they don't | What they have that QMIE doesn't |
|---|---|---|---|
| **freqtrade** | Full algo trading bot, executes orders | Simpler ops surface; manual-entry safety | Backtest engine, hyperopt, strategy registry, dry-run mode |
| **hummingbot** | Market making, multi-exchange | n/a | Order management, inventory tracking, spread strategies |
| **jesse** | Backtesting framework, code-as-strategy | Real-time deployment recipe | Walk-forward, Monte Carlo, robust backtest infra |
| **CCXT** | Unified exchange API | We deliberately use raw REST for predictability | 100+ exchanges, full auth flows, websocket streams |

QMIE's distinguishing position: **alert-only, audit-forward, Pine
visualizer parity.** It's the smallest possible system that turns a
discretionary trader into a screen-watching trader with a 30-symbol
universe, without taking on execution risk. That niche isn't well
served by any of the above — they're either full automation systems
or pure backtest libraries. The closest analogue is the various
"TradingView webhook → Discord" bridges floating around GitHub, none
of which do server-side scanning or audit persistence.

If you wanted to grow QMIE, the highest-leverage extensions in
priority order would be:

1. **Backtest harness** — feed historical klines through `compute_signal`
   bar-by-bar to compute hit rate per grade. Without this, the grading
   system is a hypothesis, not a measured edge.
2. **WebSocket kline ingest** — current REST polling caps at ~150
   symbols. WS unlocks 500+ at near-zero marginal cost.
3. **Trade journal endpoint** — POST `{signal_id, fill_price, size,
   exit_price}` so the server can join alerts with manual fills and
   compute attribution without a separate spreadsheet.

---

## Changed files in this review pass

```
python/scanner/indicators.py        SMA-seeded RMA; triple-ST returns line+dir series
python/scanner/signal_engine.py     Lower ST agreement threshold; reuse triple result; daily_trend field
python/scanner/scheduler.py         Supply daily_df to compute_signal
python/scanner/exchange_clients.py  Retry-once on 5xx / connection error
python/scanner/dispatcher.py        Simplified extra-field access; inject daily_trend
python/notifiers/discord.py         Simplified extra-field access; Daily Trend embed field
python/notifiers/telegram.py        Simplified extra-field access; Daily Trend line
python/config.py                    validate_runtime() warnings
python/main.py                      Emit config warnings at startup
pine/quant_visualizer.pine          Threshold + unique discard names
python/pytest.ini                   NEW
python/tests/                       NEW (8 files, 118 tests)
.github/workflows/tests.yml         NEW (CI)
.gitignore                          NEW
REVIEW.md                           This doc
```
