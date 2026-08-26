# Paper cash sim — 4h A/A+ (2025 → 2026-07)

Not an order. `W_*` unchanged. Overlay skip list empty.
`$100` is **position notional at 1x**, not a $100 stop.

```bash
cd python
python -m backtest.cash_sim --start 2025-01-01 --cash 1000 --stake 100
```

Book: frozen `latest.parquet`, 10 USDT-M names, 4h A/A+, ADX≥20, ATR% 0.4–4.0,
OOS 2025-01-02 → 2026-07-29 (2152 closed alerts, win 49.1%, E[R] +0.309).

Start **$1000**. Each fill uses **$100**. Hard cap **10** concurrent (cash/stake).
No fees, no funding, no leverage. SL is ~3.7% of entry, so $100 notional
risks about **$3.70**, not $100.

| Policy | Taken | Skip | Final | PnL | Max DD |
|---|---:|---:|---:|---:|---:|
| FIFO every 4h A/A+ that fits | 1021 | 1131 | **$1,597** | **+$597** | −$183 |
| One open per symbol | 530 | 1622 | **$1,298** | **+$298** | −$113 |
| First / symbol / UTC day, then FIFO | 718 | 164 | **$1,500** | **+$500** | −$120 |
| First / symbol / day + one per symbol | 503 | 379 | **$1,332** | **+$332** | −$92 |
| Unlimited slots (not this $1000) | 2152 | 0 | $3,371 | +$2,371 | — |

One-open-per-symbol is the book that actually fits $1000 (10 names × $100).
Calendar on that book: **2025 +$88** (314 fills), **2026 through 29 Jul +$210** (216 fills).

BTC/ETH/SOL only (606 clustered alerts): FIFO **$1,239** (+$239); one-per-symbol **$1,066** (+$66).

A $100 *stop* would need ~$2,700 notional per trade. QMIE does not size that
leverage. Do not treat this as live edge until 30 closed manual fills.
