# Time-series momentum (SIGN) — crypto review

Source: [maxlamberti/time-series-momentum](https://github.com/maxlamberti/time-series-momentum) (Lim, Zohren & Roberts DMN report). QMIE vendored notebooks under `python/research/third_party/time_series_momentum/`.

## What the upstream project does

1. **SIGN (baseline TSMOM)** — For each asset, go long if the past 12-month return is positive, else short. Scale exposure by `0.15 / σ` where σ is an EWM daily volatility (span 60). Rebalance on **month-end** in the baseline notebook.
2. **DMN (MLP)** — Neural net trained with a Sharpe-like loss on normalized return features (multi-horizon norm returns, MACD z-scores, vol regime). Requires CLC futures panels + TensorFlow. Not run in QMIE CI.
3. **Benchmarks** — Compared to AQR cross-sectional momentum in the PDF report (futures universe).

## QMIE crypto port (top 10)

| Parameter | Futures (Lamberti) | QMIE crypto |
|---|---|---|
| Universe | CLC continuous futures | Static top-10 USDT-M perps (BTC, ETH, BNB, SOL, XRP, DOGE, ADA, AVAX, LINK, DOT) |
| Calendar | 252 trading days | 365 calendar days |
| Data | Pinnacle CLC | Binance Vision daily (same cache as `backtest.run`) |
| Holdout | Report sample ending ~2020 | IS 2019-09→2022-12, OOS 2023→today (`protocol.SPLIT`) |
| Costs | Report discusses TC | 3.25 bps turnover (research default) |

Run:

```bash
cd python
/workspace/.venv/bin/python -m research.trend_lab.run_tsmom_crypto
```

Artifacts: `python/research/artifacts/tsmom_top10_crypto.json`, `/opt/cursor/artifacts/` when present.

## Integration stance

- **No broker path** — weights are research P&L only.
- **No `W_*` changes** — SIGN is not Pine-parity scoring.
- **Desk** — Could later show SIGN regime badges on OPS/SCREENS; not wired to alerts in this PR.
- **vs TEMA** — TEMA is faster (4h stack + gates); SIGN is slow trend + vol targeting. Treat as complementary research, not a replacement signal.

## Hypotheses (research)

| Id | Claim |
|---|---|
| H-TS1 | Monthly SIGN L/S book beats equal-weight buy-and-hold on **OOS Sharpe** |
| H-TS2 | Long-only SIGN reduces drawdown vs L/S but sacrifices bear-leg profit |
| H-TS3 | Daily rebalance does not reliably beat monthly (turnover drag) |

## Validated run (Vision daily, OOS 2023-01-01 → 2026-09-28)

Universe: BTC, ETH, BNB, SOL, XRP, DOGE, ADA, AVAX, LINK, DOT. Per-name \(|w|≤1\), portfolio gross ≤ 1 after equal 1/10 split, 3.25 bps turnover, 1-day lag.

| Book (OOS) | Sharpe | CAGR | Max DD |
|---|---:|---:|---:|
| Equal-weight buy-and-hold | **0.70** | **27%** | −72% |
| SIGN monthly long-only | 0.49 | 12% | −45% |
| SIGN daily long-only | **0.66** | **21%** | −46% |
| SIGN monthly L/S | −0.06 | −13% | −53% |
| SIGN daily L/S | 0.25 | ~0% | −51% |

Per-asset OOS Sharpe (monthly long-only): BTC **0.92**, SOL **0.79**, DOGE **0.55**; DOT **−0.09** (weakest).

### Hypothesis board

| Id | Verdict |
|---|---|
| H-TS1 | **REJECT** — no L/S book beats BH on OOS Sharpe |
| H-TS2 | **CONFIRM** — long-only SIGN cuts max DD vs BH (−45% vs −72%) with lower CAGR than BH |
| H-TS3 | **INCONCLUSIVE** — daily long beats monthly long on Sharpe (0.66 vs 0.49) but with similar DD |

**Do not promote** to live scanner: slow daily/monthly book ≠ 4h TEMA tickets; BH still wins raw CAGR on this bull-heavy OOS.

Re-run: `python -m research.trend_lab.run_tsmom_crypto`. Artifacts: `tsmom_top10_crypto.json`, `tsmom_top10_oos_kpis.csv`, `tsmom_top10_oos_equity.png`.
