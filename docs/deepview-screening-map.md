# Deep View screening → QMIE desk

Richard Moglen’s Deep View (DFW / DVU) webinar is an **equities**
CAN SLIM cockpit: 11k names, earnings/sales, IPO age, NYSE open, AI
catalysts. QMIE is an **alert-only USDT-perp scanner** (~30 names,
closed 1h/4h + 1D radar). This note maps *workflow*, not a clone.

Do **not** port CAN SLIM fundamentals, custom score DSLs, or brokers.
Do **not** retune `W_*` from this mapping.

## What Deep View is (webinar)

Three-pane **screener**: data columns (left) + chart (center) + data /
AI / news (right). Top bar: current screen, **favorited presets**,
column-set picker.

Two reasons they screen:

1. **Trade ideas** (cup-handle, VCP, post-gap range).
2. **Market / theme analysis** (where money is rotating).

Ross (O’Neil): 3 go-to screens, 70–90% name overlap, hard part is
sizing and mental capital — not finding tickers. Short consistent
routine beats a monthly marathon.

## Module map

| Deep View | QMIE already | Fit |
|---|---|---|
| Screener module | OPS tables (TEMA / daily breakout / EXIT) | Partial — list exists, not a keyboard “spacebar through 300” cockpit |
| Chart pane while screening | CHARTS tab + Pine visualizer + VIEW CHART | Yes — keep SVG + Pine; do not add JS chart libraries |
| Data panel / stats table | Signal DETAILS + AGENTS ANALYZE overlay | Yes — ATR SL/TP stay scanner geometry |
| AI terminal / “ask why this gap” | `GET /agents/analysis/{id}` (template or OpenAI Take) | Overlay only — never a grade or order |
| News pane | Out of scope | Reject as a score input |
| Dashboard theme tracker | Trend Radar G/Y/R + fresh flips + clusters | **Use this** as the theme module |
| Watch list / Shift+Space flag | JOURNAL + paper book | Missing: a **focus list** (flag interesting rows without a fill) |
| Combo watch list (OR / dedupe) | AGENTS checklist (A/A+ ∪ daily breakout) + BOOK | **Highest-value UX** — one master symbol list |
| AND/OR filter groups | Checklist required vs optional gates; allocator `cluster_max` | Adapt as **views**, not a new engine |
| Column sets | OPS cards (symbol, TF, grade, score, price) | Add sort: score, TF, cluster, ATR%, coil width |
| Favorite screens | Implicit (OPS splits + BOOK + RADAR) | Add 4–5 **named views**, not new scoring math |
| Share screen / column-set links | Out of scope | Skip |

## Five Deep View presets → QMIE views

These are **operator views over existing data**. They are not five new
`compute_signal` engines.

| DV preset | What it hunts | QMIE analog | Use? |
|---|---|---|---|
| **Leaders** (wide net, 250–350, RS + liquidity + growth) | Position leaders setting up | **TEMA 4h A/A+** (frozen OOS PF 1.61) + radar GREEN | **Primary.** One general screen. |
| **Momentum leaders** (top 5% 1m/3m RS) | Fast swing RS | `ALLOC_MODE=rotation` lookback ROC; 1h A/A+ as a *secondary* list | **Secondary.** 1h dilutes OOS — do not make it the live book. |
| **Liquid leaders** ($100M+ ADV, ~100 names) | Cleaner tape, part-time universe | `SymbolUniverse` auto top-N by quote volume + static list | **Yes as universe**, already built. Do not rescan 11k perps. |
| **IPO 2y wide** | Young names, first stage-2 | No IPO in USDT perps | **Reject** (or later: “listed < N days” — out of scope now) |
| **Gaps and strong moves** (gap ≥5% or day ≥10%) | Theme ignition | **Daily breakout** GREY→GREEN/RED + coil-UP/DOWN + radar breakouts | **Yes as the specialist view.** Not an A/A+ grade. Long and short. |

## Workflow to steal (without changing the engine)

1. **One wide net + one specialist.** Leaders = 4h A/A+. Specialist =
   daily breakout / coils. Combo-dedupe into one review list.
2. **Sort for themes, then setups.** DV sorts % from open / % today,
   then industry. Crypto has no NYSE open — sort **radar % since flip**,
   **cluster**, then **score**. After the close, same sort on the 1D bar.
3. **Tight right side first.** DV RMV 0 = contraction, 100 = expansion.
   QMIE already has **tight GREY coils** (`coil_width_pct`) and ATR%
   gates. Sort coils tight→wide. Do **not** add RMV as an 8th score vote.
4. **Flag ≠ fill.** Shift+Space → watch list. QMIE should flag OPS /
   checklist rows onto a **focus list**, then JOURNAL only if you click
   live. Paper auto-fill is measurement, not a watch list.
5. **Keyboard through the chart.** Space / arrows next row, CHARTS
   follows the selected symbol (already started via VIEW CHART).
6. **Ross’s three screens, translated:** 4h A/A+ · radar 1D · ranked
   book. If time-boxed, skip 1h entirely (`SCAN_TIMEFRAMES=4h` still
   unapplied — one knob, do not apply from this note).

## AND/OR groups — what to copy

Deep View **ALL** group = every filter must pass (QMIE: grade A + closed
bar + optional ADX/ATR/HTF). **ANY** group = earnings *or* sales *or*
pattern (QMIE: TEMA A/A+ *or* daily breakout; checklist optional gates).

Combo list = **OR of result sets, then unique(symbol)**. That is the
module to add on OPS/AGENTS — not a SQL query builder over 200
fundamentals.

## Explicit rejects

- Earnings / sales / CAN SLIM / FCF / IPO date as score inputs
- Generic “create screener from scratch” that mutates `W_*`
- News / catalyst scrape into grades
- Color-coded candlestick pattern engine as a new vote
- Short-stock inverse screens as a second product
- Intraday 5-minute execution from the screener (QMIE stops stay the
  printed 1h/4h ATR; you click size)
- Deep View AI as a replacement for `python -m backtest.run`

## Landed (combo SCREENS)

`GET /screens` + desk **SCREENS** tab: unique(symbol) OR of 4h A/A+, daily
breakout, radar coils, ranked book. Named views, sortable columns, local
focus list (Shift+Space), chart follows the cursor. Not a new engine.
Do not add earnings/IPO next. Measure 30 **manual** 4h fills before any
new screen math.

`places_orders` stays false. Quantity on the desk DAG stays 0.
