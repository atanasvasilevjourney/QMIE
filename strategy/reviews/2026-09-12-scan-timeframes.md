# QMIE review — 2026-09-12 (applied)

verdict: applied
proposed_knob: scan_timeframes
proposed_from: 1h,4h
proposed_to: 4h
applied: true
catalog_next: sig_min_adx

Human approved **4h-only** TEMA scanning. This change updates repo defaults
and `strategy/baseline.yaml`. Production `.env` on Render must match
(`SCAN_TIMEFRAMES=4h`) and restart the scanner.

## What changed

- `strategy/baseline.yaml`: `scan_timeframes: 4h`
- `python/config.py` default: `4h`
- `python/.env.example`: `SCAN_TIMEFRAMES=4h`

## Why (frozen OOS)

From [`docs/backtest-baseline.md`](../../docs/backtest-baseline.md) (TMA 9/90/199,
ADX≥20, ATR% 0.4–4.0, split 2025-01-01):

| Slice | A/A+ closed | Win % | E[R] | PF |
|---|---:|---:|---:|---:|
| Combined 1h+4h | 12744 | 42.1% | +0.122 | 1.21 |
| **4h only** | **2152** | **49.1%** | **+0.309** | **1.61** |
| 1h only | 10592 | 40.6% | +0.084 | 1.14 |

1h alerts dilute pooled PF under 1.3. 4h A/A+ clears Sprint 1 gates.

## Unchanged

- Daily Trend Radar (1D RGG / coils) — independent of `SCAN_TIMEFRAMES`
- HTF for 4h remains 1D via `SCAN_HTF_MAP`
- TEMA stack 9/90/199 and all `W_*` weights
- `sig_min_adx` stays 0.0 until the next one-variable cycle

## Next cycle

After n ≥ 30 closed **4h** A/A+ journal fills, run `python -m improve.review`.
Catalog proposes **`sig_min_adx` 0 → 20** only — do not change both knobs.
Suggest `JOURNAL_OOS_WIN_PCT=49.1` as the live benchmark from frozen 4h OOS.

## Out of scope

- Do not add `1d` to `SCAN_TIMEFRAMES` (daily A/A+ OOS loses).
- Do not import KovaView skip gates onto the native checklist.
- No broker / execution paths.
