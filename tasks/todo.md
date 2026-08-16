# QMIE — Task Backlog

Source of truth for *what to do next*. Completeness research:
`docs/development-status.md` (2026-08-16).

**Current score:** live scanner ~90% · intended system (scanner +
measured edge + live feedback) ~80% (journal landed; OOS write-up still open).

Do **not** re-add ribbon / structure / sweep or re-open execution until
Sprint 1 has an OOS number.

---

## Sprint 0 — Make the current tree honest
- [x] CI: install `requests` + `pyarrow` so backtest tests collect
      (full `backtest/requirements.txt` conflicts with numpy 2)
- [x] Fix `BinanceClient.fetch_premium_index`; add method to Bybit + ABC; tests
- [x] Wire original-7 weights through `Settings`, `.env.example`,
      `main.py` `Weights(...)`. Validator target ~100
- [x] Doc sync: README, CLAUDE.md, architecture.md = 7-component;
      fix `quant_strategy.pine` typo; status doc added
- [x] `docs/deployment.md` runbook
- [x] Enforce `sig_max_signals_per_symbol_per_day` (0 = unlimited)

## Sprint 1 — Prove or kill the grading hypothesis
- [ ] Canonical walk-forward run (10 symbols, 1h+4h, split 2025-01-01,
      ADX≥20, ATR% 0.4–4.0) — running
- [ ] `docs/backtest-baseline.md` with IS/OOS table (no parquet in git)
- [x] Decision: **cut** ribbon+structure+sweep (operator keep-or-cut;
      engine restored to original 7, weights sum 100)
- [x] Trailing-stop variant vs fixed 1.5/2.5 ATR on the same signals

## Sprint 2 — Live loop (Phase 4, no broker)
- [x] `POST /journal` + `fills` table (signal_id, fill, size, exit)
- [x] Persist `daily_trend` and `funding_rate` on `signals`
- [x] Alert when live A/A+ win rate (from journal, n≥30) drifts >5 pts
      vs OOS baseline (`JOURNAL_OOS_WIN_PCT`; silent until that is set)
- [x] Pine dashboard: daily-trend row + alert JSON field
- [x] Ranked asset allocation (`ALLOC_MODE=ranked`): top N long/short,
      cluster cap, suggested weights on Discord/Telegram; `GET /allocation`
- [x] ARS-style rotation (`ALLOC_MODE=rotation`): lookback ROC, cash
      threshold, dual allocation, second BTC-weak defensive mode
      (`cash` / `paxg` / `paxg_then_cash`); `pine/asset_rotation.pine`
- [x] One-variable review CLI + Cursor agent (`python -m improve.review`,
      `strategy/goals.yaml`) — proposes, does not trade or write `.env`


## Sprint 3 — Hardening (only if Sprint 1 shows edge)
- [ ] HTTP tests for `/health`, `/webhook`, `/scan/once`
- [ ] Golden-file Pine-parity test (same OHLCV → same score)
- [ ] Strip or document leftover `orders` / `daily_pnl` broker tables
- [ ] WebSocket klines — only if universe > ~50 symbols

## Won't do (unless scope is explicitly changed)
- Order execution / broker adapters
- Hermes / Signum / HyperLiquid / Railway "oneshot" trading agents
- Weight hyperopt on the reporting sample
- Forex / indices / equities
- Re-implementing equity curve / Monte Carlo / SQN (already in
  `backtest/app.py` and `backtest/run.py`)

---

## Completed
- [x] Rolling window fix (O(n) bar walk)
- [x] Binance CSV header row detection
- [x] Windows Unicode fix
- [x] FutureWarning fix (pd.to_datetime)
- [x] Streamlit Styler cell limit fix
- [x] 10-symbol expansion (DOGE, ADA, AVAX, LINK, DOT)
- [x] Walk-forward --split flag
- [x] RR ratio + realized_r per signal
- [x] Expectancy R + Profit Factor in summary
- [x] MAE/MFE tracking in R units
- [x] SQN (Van Tharp) per grade
- [x] Monthly P&L heatmap in dashboard
- [x] Equity curve + cumulative R chart per grade
- [x] Max drawdown (peak-to-trough on equity curve)
- [x] Monte Carlo simulation (shuffle 1000×, P5/P50/P95)
- [x] quantstats Sharpe / Sortino on daily R (not full HTML tearsheet)
- [x] EMA ribbon + BOS/CHoCH + liquidity sweep scoring — **cut**
      (restored 7-component engine; see Sprint 1 keep-or-cut)
- [x] Funding-rate gate (live) — **code present, currently broken; Sprint 0**
- [x] ADX trend-strength gate (live + backtest CLI)
- [x] ATR volatility filter (backtest CLI + dashboard)
- [x] CLAUDE.md workflow instructions + framework recommendations
- [x] Development status research (`docs/development-status.md`)
