# QMIE Development Status — August 2026

Deep research of the tree as of `master` @ `2ef6029`, plus Sprint 0
fixes landed in this branch. This is an engineering assessment, not a
marketing summary.

**Headline: the live scanner is ~90% of a shippable alert product.
The *intended* system (scanner + proven edge + live feedback) is
~80% complete after the journal + ranked allocation + review CLI
(was ~75% after Sprint 0 wiring).**

### Sprint 0 already in this branch

- CI installs `python/backtest/requirements.txt` (unblocks collection)
- `fetch_premium_index` uses session timeout; Bybit implemented; tests added
- Engine restored to original 7 components (ribbon / structure / sweep **cut**)
- README / CLAUDE.md / architecture.md describe the 7-component engine

Still open in Sprint 0: `docs/deployment.md`, daily cap
`sig_max_signals_per_symbol_per_day`. Sprint 1 write-up:
`docs/backtest-baseline.md` (TMA 9/90/199). One-knob proposal
(`SCAN_TIMEFRAMES=4h`) is not applied.

---

## 1. Completeness score

Two different questions get two different numbers. Mixing them is how
teams over-claim.

| Frame | Score | What it means |
|---|---|---|
| **A. Original scanner product** (alerts on closed 1H/4H bars, Discord/Telegram, Pine visualizer, SQLite audit) | **~90%** | You can deploy this today and get A/A+ alerts. Remaining work is hygiene, config wiring, and a live bug in the funding filter. |
| **B. Intended system** (A + measured historical edge + live-vs-backtest loop + operator discipline) | **~82%** | Frozen TMA OOS is in `docs/backtest-baseline.md`. Combined A/A+ PF 1.21 misses the 1.3 gate; 4h A/A+ PF 1.61 passes. Journal exists; live vs OOS drift waits on `JOURNAL_OOS_WIN_PCT` after the 4h knob. |

### Weighted breakdown of frame B (intended system)

| Workstream | Weight | Done | Contribution | Evidence |
|---|---|---|---|---|
| Live scanner core (engine, scheduler, exchanges, universe) | 30 | 92% | 27.6 | Code + 100+ unit tests; funding filter currently dead |
| Pine visualizer parity | 10 | 88% | 8.8 | 7-component math present; daily-trend label on chart |
| Notifiers + HTTP API | 10 | 85% | 8.5 | Discord/Telegram + `/health` `/signals` `/scan/once`; no HTTP tests |
| Backtest harness (data, runner, CLI, dashboard) | 15 | 90% | 13.5 | Full pipeline; no committed results parquet |
| Backtest robustness (equity, DD, MC, quantstats) | 10 | 80% | 8.0 | Implemented in `app.py` / `run.py`; trailing-stop variant missing |
| Live feedback loop (paper, grade-distribution drift) | 10 | 0% | 0.0 | Phase 4 not started |
| Ops / CI / docs | 10 | 70% | 7.0 | Docker works; CI workflow now installs backtest extras; docs catching up |
| Trade journal / fill attribution | 5 | 0% | 0.0 | README lists it as "still build"; not started |
| **Total** | **100** | | **~75** | |

### What "90% scanner" does *not* mean

It does **not** mean 90% win rate, 90% of a broker bot, or 90% of a
multi-asset platform. QMIE is deliberately alert-only. Execution,
forex/equities, and LLM trading are out of scope and should stay there.

---

## 2. What is actually built (and working)

### 2.1 Live scanner — production-shaped

The original design is in place and has been extended past the README:

- Bar-close scheduler with 5s grace (`scanner/scheduler.py`)
- Binance + Bybit public REST, in-progress candle dropped
- 7-component score (Supertrend + EMA200 + RSI + ADX + HTF + S/R + Volatility)
- Grades A+ / A / B / C / REJECT
- Daily-trend label (1D EMA200) on Discord/Telegram
- ATR%, ADX, and funding-rate *gates* on the live path
- Dedup keyed on `symbol|tf|side|bar_close_ts`
- SQLite persistence, optional Redis TTL
- Docker Compose (app + Redis), GitHub Actions workflow *exists*

Pine `quant_visualizer.pine` v2.0 carries the same 7 weights and
aggregate formula. That is load-bearing: chart marks must match alerts.

### 2.2 Backtest harness — further along than `tasks/todo.md` admits

`python/backtest/` is a real product, not a stub:

| Capability | Status |
|---|---|
| Binance Vision ZIP download + parquet cache | Done |
| Rolling 400-bar walk through `compute_signal` | Done (O(n), lesson L001) |
| WIN/LOSS/OPEN vs ATR SL/TP, conservative same-bar = LOSS | Done |
| Walk-forward `--split` | Done |
| ATR / ADX post-filters | Done |
| Expectancy R, profit factor, SQN, MAE/MFE | Done |
| Equity curve, max DD, Monte Carlo 1000×, Sharpe/Sortino | Done |
| Streamlit dashboard (filters, monthly heatmap, signal log) | Done |
| Trailing-stop variant | **Not done** |
| Full quantstats HTML tearsheet | Partial (Sharpe/Sortino only) |

`tasks/todo.md` still lists equity curve / DD / Monte Carlo / quantstats
as Phase 3 *next up*. Those landed in `b9162aa` (2026-05-18). The
backlog is stale; do not re-implement them.

### 2.3 Test inventory

This branch collected **155 tests**, all passing locally. Master CI last
collected 138 then aborted on missing `requests`. Approximate split:

| Suite | Tests (approx.) | Role |
|---|---|---|
| `test_indicators.py` | ~30 | RMA seed, ST, ATR, RSI, ADX |
| `test_signal_engine.py` | ~27 | Side/grade, ST majority, daily_trend |
| `test_scheduler.py` | ~15 | Grace window, daily_df routing |
| `test_dispatcher.py` | ~13 | Dedup, grade filter, notifier isolation |
| `test_exchange_clients.py` | ~13 | Parse, retry, factory |
| `test_security.py` | 12 | HMAC, replay, idempotency |
| `test_config.py` | 10 | Env + weight-sum validator (still 7-weight) |
| `tests/backtest/` | ~23 | Loader + outcome evaluation |

REVIEW.md's "118 tests / 83% coverage" is **out of date** (written
2026-05-15, before backtest). Ribbon / structure / sweep votes were
added later and **cut** in this branch.

---

## 3. What is broken, stale, or silently unfinished

Ordered by how much they hurt *trust* or *forward motion*.

### P0 — CI was red for every push since 15 May 2026 — **fixed this branch**

Latest master run (`26032583617`, commit `2ef6029`):

```
ModuleNotFoundError: No module named 'requests'
ERROR tests/backtest/test_data_loader.py
```

`.github/workflows/tests.yml` now installs `requests` + `pyarrow` (the
imports the backtest *unit tests* need). Do not `pip install -r
backtest/requirements.txt` next to runtime deps: `streamlit==1.35.0`
required `numpy<2` and conflicted with `numpy==2.1.2`. Dashboard extras
are loosened to `streamlit>=1.40` for local use.

### P0 — Funding-rate filter was dead on the live path — **fixed this branch**

`BinanceClient.fetch_premium_index` used `self._timeout` while the client
stores `self.timeout`. Every call raised `AttributeError`, which
`scan_one` swallowed ("fail open"). The filter never suppressed a
crowded-side BUY/SELL.

This branch: session timeout, 5xx retry matching klines, Bybit maps
`fundingRate` → `lastFundingRate`, ABC requires the method, unit tests
cover Binance 4xx/5xx and Bybit mapping.

### P1 — Config / engine / docs disagreed on the scoring contract — **mostly fixed this branch**

The engine and Pine are 7-component, weights total **100**
(20+15+15+15+20+10+5). `validate_runtime()` expects ~100.

Remaining: Pine daily-trend label still missing; leftover broker
tables in `db.py` / `models.py`.

### P1 — Docs and leftover broker-edition debris

| Item | Reality |
|---|---|
| README / CLAUDE.md / architecture.md | 7-component (ribbon / structure / sweep **cut**) |
| `docs/deployment.md` | Linked from README, **file missing** |
| `signal_engine.py` docstring | Points at `pine/quant_strategy.pine` (does not exist; file is `quant_visualizer.pine`) |
| `models.py` / `db.py` | Still carry `OrderIntent`, `orders` table, `daily_pnl` from the deleted broker edition |
| `sig_max_signals_per_symbol_per_day` | Defined, **never enforced** |
| Pine daily-trend | Server/notifiers show it; **visualizer does not** |
| `REDIS_URL` in compose | Redis service exists; `.env.example` has it commented — restart re-fires alerts |

### P1 — No published backtest result in the repo

The harness can answer "does A-grade beat C-grade?" The repo has no
`results/*.parquet` (gitignored, correctly) and no write-up of a
canonical run. Until someone runs 2y × 10 symbols with a frozen split
date and pastes the summary table, **the grade system is a hypothesis**.

That is the original REVIEW.md #1 extension. The code landed; the
*measurement* did not.

### P2 — Coverage and test holes

- `main.py` HTTP surface: 0% (called out in REVIEW.md, still true)
- Scheduler ADX / funding / ATR gates: untested
- `app.py` Streamlit: untested (acceptable)
- `fetch_premium_index`: untested (and currently crashes)
- No parity golden-file test (same OHLCV → Python score == Pine score)

### P2 — Scaling / ops cliffs (known, not urgent at 30 symbols)

- REST polling, not WebSocket (fine ≤ ~50 symbols × 2 TFs)
- Notifier failures are logged, not retried
- SQLite is enough; Postgres is a later swap
- Docker memory cap 512MB — backtest must **not** run in that container

---

## 4. What we should *not* build next

These keep coming up. They are the wrong next move.

1. **Order execution / broker adapters.** Deleted on purpose. Re-adding
   them turns QMIE into a different product and a different risk
   profile. Do not.
2. **Weight hyperopt / "AI" scoring.** The backtest spec forbids fitting
   weights on the same data used to report hit rate. Measure first.
   If OOS expectancy is negative, *then* discuss a frozen walk-forward
   refit with a holdout you never touch.
3. **Re-implementing Phase 3 charts.** Already in `backtest/app.py`.
4. **Forex / indices / equities.** One scoring engine, one microstructure.
5. **WebSocket ingest** until the universe is actually > ~50 symbols.
   Premature.

---

## 5. Recommended development sequence

Do these in order. Each step unblocks the next. Do not skip to paper
trading while CI is red and the live funding filter is a no-op.

### Sprint 0 — Make the current tree honest (unblocks everything)

1. **Green CI.** Install `backtest/requirements.txt` in the workflow.
   Confirm 155 tests collect and pass.
2. **Fix `fetch_premium_index`.** Use `self.timeout`. Add the method to
   the `ExchangeClient` ABC (Bybit: `/v5/market/tickers` funding field
   or fail-open *explicitly*). Add tests: 5xx retry, attribute exists,
   4xx raises.
3. **Scoring weights (done, then reversed).** Ribbon / structure /
   sweep were briefly extra votes (~128). They were **cut** after a
   keep-or-cut decision. Runtime now expects **~100** on the original
   seven weights. Do not re-add those three without a frozen OOS that
   shows they help.
4. **Doc sync.** README, CLAUDE.md, architecture.md: 7-component
   table. Fix the `quant_strategy.pine` typo. Add a short
   `docs/deployment.md` or remove the README link.
5. **Drop or enforce `sig_max_signals_per_symbol_per_day`.** Dead config
   is how operators think they are protected.

Exit criterion: CI green on master; `pytest` locally ~2s; env weights
sum to ~100; README describes the 7-component engine that actually
runs. Ribbon / structure / sweep stay **out**.

### Sprint 1 — Prove or kill the grading hypothesis

**Done (TMA 9/90/199).** Tables: `docs/backtest-baseline.md`. Proposal:
`strategy/reviews/2026-08-17.md` (`SCAN_TIMEFRAMES` `1h,4h` → `4h`, not
applied).

Canonical run (10 USDT-M, `1h`+`4h`, 2024-01-01 → 2026-08-16, split
2025-01-01, `--min-adx 20 --min-atr-pct 0.4 --max-atr-pct 4.0`):

- Combined A/A+ OOS: E[R] **+0.122**, PF **1.21**, beats C (+0.047) —
  expectancy pass, **PF miss** vs 1.3.
- **4h A/A+ OOS:** win 49.1%, E[R] +0.309, PF **1.61**, Sharpe 2.09 —
  gate pass. 1h is the drag (PF 1.14).
- A+ is worse than A. Do not raise min grade to A+. Do not retune `W_*`.
- Trailing ATR vs fixed 1.5/2.5: extra column only; keep fixed TP/SL.

Ribbon / structure / sweep stay **out**. Next live knob is 4h-only, then
(next cycle) `sig_min_adx` 0 → 20. Sprint 2 journal already exists;
set `JOURNAL_OOS_WIN_PCT` after the timeframe knob is applied (49.1 if
4h-only, 42.1 if 1h stays).

### Sprint 2 — Close the live loop (Phase 4, scoped tightly)

Do **not** build a broker. Build a paper ledger.

1. `POST /journal` `{signal_id, fill_price, size, exit_price, notes}`
   plus a `fills` table. Manual entries stay manual; the server
   learns what you actually took.
2. Nightly (or on `/scan/once` after each 4H close): compare last-N
   live A/A+ grade mix and win rate (from journal, not from
   hypothetical TP/SL) to the Sprint 1 OOS baseline. Alert Discord
   if live win rate drifts > 5 points — *after* you have ≥ 30 live
   fills, not before.
3. Persist `daily_trend` and `funding_rate` on the `signals` row
   (today they are extra fields on the notify payload only).

### Sprint 3 — Hardening (only after Sprint 1 says there is edge)

- Pine dashboard: daily-trend row (parity with Discord). Do **not**
  restore ribbon/structure/sweep rows.
- HTTP tests for `/health`, `/webhook` HMAC, `/scan/once`.
- Golden-file Pine-parity test on a 500-bar BTC fixture.
- Strip unused broker tables *or* document them as reserved.
- If universe grows past ~50 symbols: WebSocket klines.

---

## 6. Suggested "definition of done" for v1.0

Call the scanner **v1.0** when all of these are true:

- [ ] CI green on `master` (runtime + backtest deps)
- [ ] Funding filter works on Binance; Bybit behaviour documented
- [ ] Env weights match the 7-component engine and Pine
- [ ] README / CLAUDE.md describe the engine that runs
- [x] One frozen OOS backtest write-up exists (`docs/backtest-baseline.md`)
- [ ] Live `SCAN_MIN_ALERT_GRADE` / ATR / ADX defaults match the
      filters that were actually measured
- [ ] Operator can journal a fill against a signal id

Until the backtest write-up exists, treat the product as **v0.9 —
alerts work, edge unproven**.

---

## 7. Direct answers

**What % is developed successfully?**
~90% of the alert scanner; **~75% of the system this repo is now
trying to be** after Sprint 0 (was ~72% at research time). The last
25% is not more indicators. It is a frozen OOS number, a fill journal,
and leftover hygiene (`deployment.md`, daily signal cap).

**What can we improve?**
1. Confirm CI green on this branch.
2. Run and publish one walk-forward backtest (`docs/backtest-baseline.md`).
   Extra scoring votes (ribbon / structure / sweep) are already **out**.
3. Remaining hygiene: enforce or drop
   `sig_max_signals_per_symbol_per_day` if it still drifts from live
   behaviour. Journal already exists.

**How should we proceed?**
Sprint 0 is done in this branch. Next is Sprint 1 (measure OOS).
Do not re-open execution. Do not re-add scoring components until
Sprint 1 has a number.
