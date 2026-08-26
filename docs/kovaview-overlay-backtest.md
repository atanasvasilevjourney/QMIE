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

Vision cache, not live `fapi`. Production overlay skip list is **empty**.

**Cooldown is not coded.** A book-wide two-loss skip treated every 4h A/A+ as
the next setup and locked the book (606 → 2). That does not match KovaView
“skip the next setup.”

**`too_late` and BTC-RED `buys_allowed` are not coded.** They skipped 5–9
trades on this slice and cut winners (BTC-RED days plus one late-stage
ETH short). Overlay book = raw book.

## Headline (OOS ≥ 2025-01-01, 4h A/A+, ADX≥20, ATR% 0.4–4.0)

Three names: BTC / ETH / SOL.

| Book | N | Win | E[R] | PF | Notes |
|---|---:|---:|---:|---:|---|
| Raw closed alerts | 606 | 44.7% | +0.193 | 1.35 | Clustered 4h A/A+ |
| + too_late + BTC regime (trial) | 597 | 44.6% | +0.188 | 1.34 | Skip 9: BTC 5, too_late 4 — **taken off** |
| First alert / symbol / UTC day | 277 | 43.3% | +0.155 | 1.27 | Swing-style de-dupe |
| + too_late + BTC regime (trial) | 272 | 43.0% | +0.147 | 1.26 | Skip 5: BTC 3, too_late 2 — **taken off** |

Live overlay skip list is empty, so overlay n = raw n.

## Sample skips (trial only — not live)

| When (UTC) | Symbol | Out | R | Why |
|---|---|---|---:|---|
| 2025-01-03 08:00 | BTCUSDT | WIN | +1.67 | `btc_regime` |
| 2025-01-04 08:00 | ETHUSDT | WIN | +1.67 | `btc_regime` |
| 2025-01-04 16:00 | SOLUSDT | LOSS | −1.00 | `btc_regime` |
| 2025-04-08 04:00 | ETHUSDT | WIN | +1.67 | `too_late` |
| 2025-08-13 04:00 | ETHUSDT | LOSS | −1.00 | `too_late` |

## Verdict

Do **not** put `too_late`, BTC-RED `buys_allowed`, or a loss-streak
cooldown on the 4h checklist. They take winners off the book. Re-run
after `SCAN_TIMEFRAMES=4h` is live before calling any overlay a frozen
baseline.

## Daily (1d) — same names, same engine

Not a live knob. `SCAN_TIMEFRAMES` stays `1h,4h`. Overlay skip list empty.
HTF for 1d is weekly. `compute_signal` only scores `W_HTF` when the weekly
frame has **220 bars** (~4.2y). Outcome model is still first-touch
1.5/2.5 ATR, **100 bars** (~100 calendar days on 1d vs ~17 days on 4h).

Command:

```bash
cd python
python -m backtest.overlay_run \
  --symbols BTCUSDT ETHUSDT SOLUSDT --tf 1d \
  --start 2020-01-01 --end 2026-07-31 --split 2025-01-01 \
  --min-adx 20 --min-atr-pct 0.4 --max-atr-pct 4.0
```

Native Vision 1d (BTC/ETH 2404 bars, SOL 2142, weekly 344/307).

### Short window (2024-01-01 start) — HTF never arms

Weekly bars ≪ 220. OOS ungated: B 73 / C 407, **zero A/A+**. A+ is
unreachable without HTF (max 80). Not an ATR-band artifact.

### Long window (2020-01-01 start, OOS ≥ 2025-01-01)

HTF can score. Daily ATR% on A/A+ is wider than 4h (p50 4.66, p90 5.89).

| Book | N | Win | E[R] | PF | Notes |
|---|---:|---:|---:|---:|---|
| All grades ungated | 625 | 31.0% | −0.172 | 0.75 | Loses |
| A/A+ IS (`<` 2025-01-01) | 33 | 15.2% | −0.596 | 0.30 | Loses |
| A/A+ OOS ungated | 55 | 27.3% | −0.273 | 0.63 | BUY 52 / SELL 3 |
| ADX ≥ 20 only | 42 | 33.3% | −0.111 | 0.83 | Still loses |
| ATR% 0.4–4.0 only | 21 | 23.8% | −0.365 | 0.52 | 4.0 cap is tight on 1d |
| Canonical ATR+ADX | 9 | 44.4% | +0.185 | 1.33 | **All BTCUSDT.** n too small |

The 9 gated rows are four BTC BUY wins in Apr–May 2025, then five losses.
That is not a frozen OOS. Ungated daily A/A+ **loses**. Widening ATR to 8
does not save it (same 42-trade ADX book, E[R] −0.111).

**Do not add `1d` to `SCAN_TIMEFRAMES`.** Radar already runs daily.
Outstanding knob remains `SCAN_TIMEFRAMES=4h`.
