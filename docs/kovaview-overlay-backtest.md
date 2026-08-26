# KovaView overlay check — 4h A/A+ (few names)

Post-filter only. Engine is still TEMA 9/90/199. `W_*` unchanged.
`.env` knobs unchanged (`SCAN_TIMEFRAMES` still `1h,4h`). Not an order.

Command:

```bash
cd python
python -m backtest.overlay_run \
  --symbols BTCUSDT ETHUSDT SOLUSDT --tf 4h \
  --start 2024-04-01 --end 2026-07-31 --split 2025-01-01 \
  --min-adx 20 --min-atr-pct 0.4 --max-atr-pct 4.0
```

Vision cache, not live `fapi`. Production `evaluate_native` items:
`too_late`, `btc_regime`, `cooldown`.

**Cooldown after the first run:** a book-wide “skip while streak ≥ 2”
starved the book (606 → 2). That is **not** KovaView “skip next setup”.
Live cooldown is now **per-symbol** and only hard-SKIPs for **24h** after
the last loss on that name. Paper fills still do not count.

## Headline (OOS ≥ 2025-01-01, 4h A/A+, ADX≥20, ATR% 0.4–4.0)

Three names: BTC / ETH / SOL.

| Book | N | Win | E[R] | PF | Notes |
|---|---:|---:|---:|---:|---|
| Raw closed alerts | 606 | 44.7% | +0.193 | 1.35 | Clustered 4h A/A+ |
| + overlays | 431 | 60.3% | +0.609 | 2.53 | Skip 175: cooldown 166, BTC 5, too_late 4 |
| First alert / symbol / UTC day | 277 | 43.3% | +0.155 | 1.27 | Swing-style de-dupe |
| + overlays | 226 | **50.4%** | **+0.345** | **1.70** | Skip 51: cooldown 46, BTC 3, too_late 2 |

One-per-day is the fair “few trades” view. Overlays lift win rate through
the 48% goal and roughly double expectancy vs this slice’s raw book.
They do **not** replace the outstanding `SCAN_TIMEFRAMES=4h` live knob
(frozen 10-name 4h A/A+ is still the engine table).

Skipped-reason counts can sum over 175 because a row may fail more than
one gate.

## Sample (first A/A+ per symbol-day, overlays kept)

| When (UTC) | Symbol | Side | Out | R | Overlay |
|---|---|---|---|---:|---|
| 2025-01-05 20:00 | SOLUSDT | BUY | WIN | +1.67 | keep |
| 2025-01-06 04:00 | BTCUSDT | BUY | WIN | +1.67 | keep |
| 2025-01-07 00:00 | BTCUSDT | BUY | LOSS | −1.00 | keep |
| 2025-02-06 08:00 | ETHUSDT | SELL | WIN | +1.67 | keep |
| 2025-02-24 08:00 | SOLUSDT | SELL | WIN | +1.67 | keep |

## Sample skips (same de-dupe)

| When (UTC) | Symbol | Out | R | Why |
|---|---|---|---:|---|
| 2025-01-03 08:00 | BTCUSDT | WIN | +1.67 | `btc_regime` (BTC RED — costs a winner) |
| 2025-01-04 08:00 | ETHUSDT | WIN | +1.67 | `btc_regime` |
| 2025-01-04 16:00 | SOLUSDT | LOSS | −1.00 | `btc_regime` |
| 2025-01-06 04:00 | ETHUSDT | LOSS | −1.00 | `cooldown` |
| 2025-04-08 04:00 | ETHUSDT | WIN | +1.67 | `too_late` (costs a winner) |
| 2025-08-13 04:00 | ETHUSDT | LOSS | −1.00 | `too_late` |

`too_late` and `btc_regime` are rare here and **not** free — they each
cut at least one winner. **Cooldown** is the workhorse (mostly clustered
losers after two losses on that name).

## Verdict

Overlays are **okay to keep on the checklist** with the 24h per-symbol
pause. Do not promote them into `compute_signal`. Do not treat the
clustered 60% WR as the frozen OOS (alert clustering inflates it).
One-per-day +0.345R / 50.4% WR is the number to remember. Re-run after
`SCAN_TIMEFRAMES=4h` is live before calling this a new frozen baseline.
