# Quant review — Trend Radar, Daily breakout, paper R

2026-08-27. Multi-agent pass: weekly journal/OOS (`qmie-review`), radar math,
daily-breakout dispatch, paper/journal “execution.” **No `.env` write. No
orders. No `W_*` retune.** Outstanding one-variable knob stays
`SCAN_TIMEFRAMES` `1h,4h` → `4h` (`strategy/reviews/2026-08-27.md`).

QMIE is three products that share a desk. Mixing them is how a good coil
looks like a TEMA grade and a paper 1h book looks like edge.

| Product | Timeframe | What it is | Frozen edge? |
|---|---|---|---|
| TEMA scanner | closed 1h/4h | 7-component A/A+ | Yes — 4h A/A+ OOS 49.1% / E[R] +0.309 |
| Trend Radar | closed 1d | Unranked RGG breadth | No — context only |
| Daily breakout | closed 1d | Unranked GREY→GREEN/RED **or** coil close-break | **No harness** |

“Trade execution” here means **suggested levels + paper/journal R**. There
is no broker path. `quantity` stays 0. `weight_pct` is a 100-point risk
budget.

---

## 1. Trend Radar — calculation

### What is already correct (keep)

- **RGG hysteresis:** leave GREY only when `ADX >= 25` and `+DI ≠ −DI`;
  re-enter GREY when `ADX < 20`; hold the old color in `[20, 25)`.
  Locked by `TestClassifyRggSeries` (`test_holds_trend_in_band_20_25`,
  `test_leaves_grey_when_adx_crosses_enter`, …).
- **Closed daily bars:** clients drop the live candle; radar `as_of` is
  max closed `bar_time`, not wall clock; tick waits 5s after UTC day close.
- **Late-stage is signed:** GREEN needs `pct_since >= +50`; RED needs
  `pct_since <= -50`. Not `abs()`.
- **Coils vs breakouts** are mutually exclusive on a row.
- **Not in `compute_signal` / `W_*`.** Breadth bias lives in
  `radar_agent` (`GREEN > 1.2× RED` → LONG).

### Gaps vs a perfect radar (ranked)

**P1 — coil is not a coil.** `_detect_breakout` arms if the **last prior
bar** is GREY and the prior 20-bar Donchian width `≤ 15%`. The module
docstring says the **window** was a GREY tight coil. A 19-bar GREEN trend
plus one GREY pause inside a 15% box still arms. Tests only cover
all-GREY vs all-GREEN.

**P1 — two Donchian windows.** Tight-coil width uses the last 20 bars
**including today**. Breakout uses the prior 20 **excluding today**.
Displayed `coil_high` / `coil_low` on a breakout bar include today’s
wick; `breakout_level` does not.

**P1 — incomplete still looks like a full map.** Any failed symbol →
`status: incomplete`. RadarPanel subtitle is the same chrome as `ready`.
Orbit still tints the glass core from partial G/Y/R. Live `:8080` radar
was incomplete (8 radar errors) while Agents still printed LONG 88.5%
green.

**P1 — bias ignores GREY.** 10 GREEN / 80 GREY / 8 RED is LONG
(`10 > 9.6`). Grey share is the coil regime; treating it as a trend
session is the Signum-style miss.

**P2.** `(hi−lo)/lo` is not ATR compression. `+DI == −DI` in a strong
ADX trend keeps the old color (untested). GREEN can persist with
`−DI > +DI` inside `[20, 25)`. `as_of = max(bar_time)` is not “all names
on this UTC day.”

### Perfect radar calc (do not implement this cycle)

1. Wilder ADX/DMI on **closed** 1d (keep SMA-seeded RMA).
2. Same hysteresis 25 / 20.
3. Coil = Donchian width `≤ 15%` **and all N bars GREY**.
4. Breakout = first **closed close** outside **that same prior** GREY box
   (one-shot; excess stored, not a live gate until its own OOS exists).
5. Publish `as_of` = that UTC date; breadth / Orbit tint only if
   `status == ready` (or coverage ≥ `min_coverage_pct`).
6. Never into `W_*`.

---

## 2. Trend Radar — presentation

**Today:** G/Y/R counts, stacked bar, buckets (fresh G/R, breakouts,
coils, late). DETAILS has color, days, price, ADX, ±DI, coil %, breakout
level. Footer correctly says manual / not A/A+.

**Missing on the panel (data already exists elsewhere):** BTC color,
bias LONG/SHORT/MIXED, coverage %, `as_of` date, hysteresis 25/20.
Agents has bias + BTC. Orbit HUD has `as_of`. RadarPanel does not.

**Perfect RadarPanel copy**

- Title: **Trend Radar — unranked 1D context**
- Subtitle: `{status} · closed through {as_of} · {succeeded}/{requested}
  ({pct}%) · enter 25 / exit 20 · not a QMIE grade`
- Chip: `bias {LONG|SHORT|MIXED} (G > 1.2× R, grey ignored)` + `BTC {color}`
- If `incomplete`: warning, do not tint Orbit as if the map is full
- Fresh rows: include ADX (Late already does)

Rename radar **Breakouts** → **Donchian coil break (watch)** so it is
not the OPS Daily breakout table.

Orbit HUD: **Closed 1D breadth core (unranked)** — not “Live radar core.”

---

## 3. Daily breakout — calculation

Separate product: `QMIE-DailyBreakout`. **Not** in `python -m backtest.run`.
Frozen OOS is TEMA 1h/4h only. Daily **A/A+** overlay loses; that is why
**1d stays off `SCAN_TIMEFRAMES`.** Do not confuse the two.

### Exact live rule

Dispatch ORs two events onto one strategy name:

1. **Color flip:** `days_in_state == 1` GREY→GREEN (LONG) or GREY→RED
   (SHORT). No coil required. Tested
   (`test_green_flip_today_is_long` / `test_red_flip_today_is_short`).
2. **Coil close-break:** `_detect_breakout` UP/DOWN. Color can still be
   GREY.

Same bar, same side → one signal, reason
`trend_start_long+coil_breakout_up`. Opposite sides → two inbound
rows (untested).

**SL/TP** (`trend_start_to_tvsignal`):

- Coil UP → SL = displayed `coil_low` (today-inclusive box)
- Coil DOWN → SL = displayed `coil_high`
- Color-only flip → **SL = None, TP always None**

So color-only DailyBreakout paper fills **never mark** (`first_bar_exit`
needs a barrier). `realized_r` is null without a stop. You cannot
measure that book.

Pine daily label is long-only ATR 1.5/2.5, no coil, no shorts — **not**
the server product. Webhook vs radar can race on the same
`idempotency_key`.

ADX on the radar card is **display**, not a dispatch gate. A GREY coil
can fire at ADX 12. Do not copy TEMA’s `sig_min_adx` 20 onto this product
without its own OOS.

### Perfect breakout calc (own harness, later)

Freeze the rule **before** looking at OOS:

1. Walk **daily** closed bars only (`classify_symbol` / `iter_trend_starts`).
2. Split **2025-01-01**. Do **not** pool with 4h A/A+.
3. Report GREY→GREEN, GREY→RED, coil-UP, coil-DOWN **separately**.
4. Entry column A: signal close. Column B: **next open** (conservative).
5. Stop = **prior-window** opposite (not today’s wick). TP = 2R display
   for this product only — do not change TEMA 2.5×ATR.
6. Same-bar SL+TP → LOSS. Time-stop (10–20 daily bars) so OPEN does not
   vanish from expectancy.
7. One-shot: require all N prior bars GREY, not last-bar-only.

Do **not** stack volume + retest + excess floor + confirmation on the
decision sample. Measure the current OR-of-flip-and-coil book first; it
will look worse than the desk copy.

---

## 4. Daily breakout — presentation

Three lists, three meanings:

| Surface | Membership |
|---|---|
| Radar Breakouts | Coil close-outside-range only |
| OPS Daily breakout | Flips **and** coils (`QMIE-DailyBreakout`) |
| SCREENS Breakouts | Union of persisted DailyBreakout ∪ radar.breakouts |

GUIDE copy treats GREY→GREEN and coil-UP as one event. They are not.
Radar Fresh GREEN is **3 days**; OPS only dispatches **day 1**.

**Perfect OPS Daily breakout DETAILS**

- Tag: `trend_start` vs `coil_breakout` (never one “breakout” badge)
- Side BUY/SELL, ADX, prior coil high/low, `breakout_level`, excess %
- SL (prior opposite or `—`), suggested 2R **display only**
- Chart always **1d** visualizer (`interval=D`)
- Color-only: `R —` / “no R until stop defined” — do not invent ATR 1.5

SCREENS combo currently prefers 4h when TEMA also fired; a breakout
review must open **1d**.

---

## 5. Paper / journal R — calculation

There is no isolated perp account. Formulas that must **stay** (TEMA
Pine parity + frozen OOS):

```
risk       = |fill − stop|
R_BUY      = (exit − fill) / risk
R_SELL     = (fill − exit) / risk
WIN        <=> R > 0          # R == 0 is LOSS (binary protocol)
SL         = close ∓ 1.5 × ATR(14)
TP         = close ± 2.5 × ATR(14)    # planned R ≈ 1.667, not 2R
same_bar   = SL and TP touched → SL (LOSS)
path       = first closed bar after the signal bar
weight_pct = share of a 100-pt book, not qty
quantity   = 0
```

Paper fill = alert **close**, then later bars, SL before TP. That
**matches** `backtest._evaluate_outcome`. It does **not** match a
next-open fill. Changing fill-to-next-open or TP-to-2R **invalidates**
`docs/backtest-baseline.md`.

Cash PnL = `size_coins × signed(exit − fill)`. No fees, funding, or
isolated cap. 4 bps/side is small vs 1.67R TP and **material vs 4h E[R]
+0.309** — do not freeze edge from fee-less paper cash.

**Three size models, not one:** paper `$PAPER_NOTIONAL_USDT` → coin qty;
allocator `weight_pct`; journal UI default size `0.01` coins. They are
not convertible without a typed **1R risk USDT**.

`JOURNAL_OOS_WIN_PCT` exists but is unset. If enabled on the current
mix it would compare pooled paper+1h win% to 49.1 and look like edge.
Keep it off until the filter is **manual + 4h + A/A+**.

---

## 6. Paper / journal R — presentation

**Today’s failure is inference, not the R formula.**

Journal 2026-08-27: closed A/A+ **68**, win **57.4%**, avg R **0.511**.
Split: **62 paper / 6 manual**, **60× 1h / 8× 4h**, **5** closed manual
4h (need 30). CLI verdict `success` is journal math vs goals
(win ≥ 48, E[R] ≥ 0.15). Frozen edge remains 4h A/A+ OOS.

`JournalFlow` subtitle is `A/A+ win {pct}% · closed {n}` with no
source/TF. That is how 57% gets mistaken for 49.1%.

**Perfect stats line (always, not a footnote)**

```
A/A+ closed: 68  ·  paper 62 / manual 6  ·  1h 60 / 4h 8
win 57.4% is pooled journal — not frozen OOS
edge table: 4h A/A+ OOS 49.1%  E[R] +0.309
need 30 closed manual 4h A/A+ before live vs OOS
```

**Perfect DETAILS (plan card, not a ticket)**

- Entry (alert close) · Stop · TP · **R to TP** (~1.67 on TEMA rows)
- Optional: typed **1R risk USDT** → implied qty for the human
- Caption: “Signal-only. QMIE does not place orders.”
- Ban on that card: Submit, Qty to send, Isolated, Leverage, Wallet

Journal **Size** label: **coin qty for cash math only**, not an order.
Exit table collapsed row: cash PnL · **R** · **barrier** (SL/TP/manual)
· paper/manual · TF. Charts equity: start 0, **“journal cash, not live
equity,”** filterable to paper vs manual and 4h A/A+.

---

## 7. What we will not do from this review

- Apply `SCAN_TIMEFRAMES=4h` (human `.env` + `baseline.yaml` together).
- Apply `sig_min_adx` 20 or `alloc_top_long` 3 → 2.
- Retune `W_*` or put radar/coil into the 7-component sum.
- Add `1d` to `SCAN_TIMEFRAMES`.
- Re-apply KovaView checklist SKIP (`too_late`, BTC-RED `buys_allowed`,
  cooldown).
- Brokers, Hyperliquid, Hermes, Railway.
- Change TEMA SL/TP multipliers or fill-at-close without a new frozen
  parquet.

---

## 8. If the operator asks to implement next

One variable still owns the **scanner** cycle (4h alerts). Presentation
fixes do not count as that knob:

1. **Desk honesty (safe):** RadarPanel `as_of` / coverage / incomplete
   warning; journal stats split; DETAILS R-to-TP; never-an-order copy;
   Daily breakout tagged `trend_start` vs `coil`.
2. **Breakout SL honesty:** stop = prior-window opposite, not today’s
   inclusive coil box. Color-only rows stay `R —` until a stop rule is
   frozen **and** measured.
3. **Daily-breakout OOS harness** (new, not `backtest.run`): split
   2025-01-01, four separate books, next-open column, time-stop.

Do not start (3) until (1) is on the desk so the operator can see which
book they are even journaling.
