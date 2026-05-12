# HTF Daily Trend Filter — Design Spec
**Date:** 2026-05-12
**Project:** QMIE Scanner Edition
**Status:** Approved, pending implementation

---

## Summary

Add a daily-trend label to every QMIE alert. When the 1D EMA200 says the macro trend
is bullish or bearish, that context appears visibly in Discord and Telegram so the trader
can factor it into the manual entry decision. No signals are blocked — this is a soft
informational field, not a gate.

---

## Motivation

The video strategy ("trend radar") uses daily EMA200 direction as the primary trend
filter: be invested when the daily trend is up, stand aside when it is down. QMIE's
existing HTF alignment component is a *soft score* (up to 20 points). A symbol with a
bearish daily trend can still reach A-grade if the other six components are strong.

Adding a visible `Daily Trend` label in alerts lets the trader apply the same
"trend radar" discipline themselves without removing QMIE's flexibility to alert
across all market conditions.

---

## Decisions

| Question | Decision |
|---|---|
| Hard block or soft warning? | Soft warning — signal always fires, label is informational |
| What defines daily trend? | EMA200 on 1D — price above = bullish, below = bearish |
| Where is it shown? | Discord embed field + Telegram message line only |
| How are 1D klines sourced? | Reuse existing htf_df for 4H scans; extra fetch only for 1H scans |

---

## Data Flow

```
scheduler._scan_pass(tf)
    │
    ├── 4H scan: htf = "1d" already fetched → daily_df = htf_df (0 extra calls)
    ├── 1H scan: htf = "4h" → fetch "1d" separately (1 extra call per symbol)
    │
    └── compute_signal(df, htf_df=htf_df, daily_df=daily_df, ...)
            │
            └── ema(daily_df["close"], 200) → compare last close
                  above EMA200 → daily_trend = "bullish"
                  below EMA200 → daily_trend = "bearish"
                  no data/NaN  → daily_trend = "unknown"
                  stored in ScanResult.daily_trend

dispatcher.dispatch(result)
    └── sig_dict["daily_trend"] = result.daily_trend
        TVSignal.model_validate(sig_dict)   # extra="allow" handles it

notifiers/discord.py  → embed field  "Daily Trend: Bullish / Bearish / Unknown"
notifiers/telegram.py → message line "Daily Trend: Bullish / Bearish / Unknown"
```

---

## File Changes

### `scanner/signal_engine.py`
- Add `daily_trend: str = "unknown"` to `ScanResult` dataclass
- Add `daily_df: Optional[pd.DataFrame] = None` parameter to `compute_signal()`
- Before the `return ScanResult(...)`: compute EMA200 on `daily_df["close"]` using
  the existing `ema()` function, compare `last_close` of the daily df to `e200_daily`,
  set `daily_trend` accordingly
- Pass `daily_trend=daily_trend` into `ScanResult(...)`

### `scanner/scheduler.py`
- In `scan_one(sym)` inside `_scan_pass(tf)`:
  - Determine `daily_df`:
    - If the HTF for this `tf` maps to `"1d"` (i.e. `htf == "1d"`): `daily_df = htf_df`
    - Else: fetch `"1d"` klines with `limit=250` in a try/except; `daily_df = None` on error
  - Pass `daily_df=daily_df` to `compute_signal()`

### `scanner/dispatcher.py`
- After building `sig_dict = sig.model_dump()`:
  add `sig_dict["daily_trend"] = result.daily_trend`

### `notifiers/discord.py`
- Add one embed field to the signal embed:
  - Name: `"Daily Trend"`
  - Value: `"Bullish"` / `"Bearish"` / `"Unknown"`
  - Inline: True (sits alongside existing fields)

### `notifiers/telegram.py`
- Add one line to the message body:
  - `Daily Trend: Bullish` / `Bearish` / `Unknown`

### `python/tests/test_signal_engine.py`
- `test_daily_trend_bullish` — daily close above EMA200 → `daily_trend == "bullish"`
- `test_daily_trend_bearish` — daily close below EMA200 → `daily_trend == "bearish"`
- `test_daily_trend_no_daily_df` — `daily_df=None` → `daily_trend == "unknown"`
- `test_daily_trend_insufficient_data` — daily df < 200 rows → `daily_trend == "unknown"`

---

## What Does NOT Change

- `config.py` — no new env vars
- `models.py` — no schema changes (TVSignal uses `extra="allow"`)
- `db.py` — no new columns
- `security.py` — unchanged
- `indicators.py` — `ema()` already exists, no changes needed
- Signal scoring weights — daily trend is display-only, does not affect score

---

## Out of Scope

- Hard-blocking signals based on daily trend (can be added later as a config flag)
- Persisting `daily_trend` in SQLite
- Showing daily trend in the `/signals` API endpoint
- Using Supertrend on 1D (EMA200 only per decision)
