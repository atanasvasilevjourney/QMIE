# QMIE — Task Backlog

## Active
_(nothing in progress)_

## Phase 3 — Backtest robustness (next up)
- [ ] Equity curve + cumulative R chart per grade
- [ ] Max drawdown (peak-to-trough on equity curve)
- [ ] Monte Carlo simulation (shuffle trade order 1000×, P5/P50/P95 bands)
- [ ] Trailing stop variant — compare fixed TP vs ATR-trailing on same signals
- [ ] quantstats tearsheet integration (Sharpe, Sortino, Calmar from realized_r series)

## Phase 4 — Live feed integration
- [ ] Paper trading mode: consume live signals, track open positions
- [ ] Compare live signal grades to backtest grade distribution
- [ ] Alerting when live win rate deviates >5% from OOS baseline

## Backlog / Ideas
- [ ] Regime filter in dashboard (BTC trend: bull/bear/chop)
- [ ] Side breakdown (BUY vs SELL win rates)
- [ ] Consecutive loss streaks (max drawdown in trades)
- [ ] Volume-confirmed entries filter
- [ ] SQN by symbol (not just grade) — find best symbols

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
- [x] CLAUDE.md workflow instructions + framework recommendations
