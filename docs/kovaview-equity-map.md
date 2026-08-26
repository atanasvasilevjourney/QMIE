# KovaView equity swing → QMIE (overlay map)

KovaView / ORBIS Equity is an **EOD US-stock/ETF** long-biased swing
cockpit (`quality_rank` GREEN/GREY/RED). QMIE is an **alert-only
USDT-perp scanner** (TEMA 9/90/199, closed 1h/4h + 1D radar). This note
maps *operator policy*, not a clone.

**Verdict: do not upgrade the live scoring engine from the KovaView
brief or the two notebooks.** Highest leverage in that stack is regime
+ timing vetoes + risk *sizing* — overlays and knobs — not new votes.
Do **not** retune `W_*` or EMA lengths from this mapping. Do **not**
apply `SCAN_TIMEFRAMES=4h` or `sig_min_adx=20` from this note.

Source: operator review brief (KovaView Trend Radar) plus
`KAMA-DF-stability-scoring.ipynb` and `TEMA-TEMPLATE_adjusted5`.
`SWING_STRATEGY.md` is a KovaView doc, not in this repo.

## What KovaView is (brief)

Composite `quality_rank` 0–100 → GREEN / GREY / RED. Convergence out of
7. GREEN needs rank ≳55, ≥2 positive momentum components, non-bearish
KAMA, ADX≥20 with DI+>DI−, and not `too_late`. Ops floor: rank ≥ 60,
convergence ≥ 4. Human takes GREEN_FLIP from an EOD list.

Hard gates: **SPY** price ≥ SMA200 and realized-vol percentile ≤ 75 →
`buys_allowed`. Sizing: stop = ATR(14)×2.5, risk 1.25% of equity.
Preferred exit: wide SMA20 trail (ATR stop → BE at +3% → max(peak×0.93,
SMA20); after +10% SMA20 only). Cooldown after two consecutive losses.
Fallback: hold through GREY, exit on RED (better than exit-on-leave-GREEN
in their gated sample).

Illustrative journal (SPY/AAPL/MSFT/JPM/XOM, 2023→2026, rank≥60, conv≥4)
is **% return on equities**, not QMIE R-multiples on perps:

| Setup | N | Win | Avg ret | Hold |
|---|---:|---:|---:|---:|
| Leave GREEN (raw) | 90 | 33% | +0.15% | 12d |
| Until RED + regime + ATR | 37 | 49% | +1.63% | 41d |
| SMA20 trail + regime + too_late + cooldown | 56 | 57% | +1.44% | 22d |

KAMA regime is a **risk filter**, not a standalone alpha engine (OOS
often trails buy&hold in strong bulls). Universe RS rank is a **planned
gap**, not live. Explicitly out of scope there: crypto, scalping, futures
prop APIs, auto-execution, per-ticker Optuna, oscillator soup.

## Notebooks (why they do not retune QMIE)

### KAMA-DF neighborhood stability

Universe: AAPL, AMZN, MSFT, NFLX, QQQ, SPY, **BTC-USD** daily (yfinance).
Naive per-ticker Optuna on IS Sharpe of a KAMA-cross book **collapses
OOS** on several names (AAPL IS Sharpe 1.71 → OOS 0.19; MSFT 1.82 →
0.21). BTC-USD naive best: IS 1.05 → OOS 0.56.

Neighborhood rule: among params with IS Sharpe > 1.0, pick the lowest
OOS Sharpe std of a 10-neighbor set. SPY neighborhood pick: OOS Sharpe
**1.46**, OOS std **0.12**. AMZN had no IS Sharpe > 1.0 on one pass.

**Keep the governance. Do not keep the indicator.** That rule is already
how QMIE promotes globals (`strategy/goals.yaml` min Sharpe 1.0; one
variable; frozen OOS). Copying Optuna winners into `W_*`, EMA lengths,
or KAMA periods is the failure mode the notebook exists to stop.

BTC-USD in that notebook is **spot daily**, not USDT-M 1h/4h. It does
not freeze a QMIE KAMA overlay.

### TQQQ triple-EMA grid

Ticker **TQQQ** daily, 2018-01-02 → 2026-03-30. Grid-search EMA periods
to max Sharpe. Best OOS: EMA(4, 119, 139), OOS Sharpe **0.642**, OOS DD
**−44.6%**, **9** OOS trades. IS Sharpe ~1.00. That **fails** QMIE
`min_sharpe: 1.0` and the KAMA-DF promote rule (IS>1 **and** stable OOS
neighborhood). 199 is in the slow grid; **9/90/199 is QMIE’s frozen live
stack**, not something this notebook proved. `docs/backtest-baseline.md`
already says: do not import TQQQ notebook periods.

Oscillator soup in that notebook (MACD, RSI, StochRSI, STC) is listed as
out of scope in the KovaView brief. Do not add it here either.

## Module map

| KovaView | QMIE already | Transfer? |
|---|---|---|
| `quality_rank` 0–100 GREEN/GREY/RED | TEMA 7-component score + A+/A/B/C; 1D radar is ADX/DMI RGG only (`scanner/radar.py`) | No — radar is not a 7-factor equity quality_rank |
| Convergence / 7 votes | Seven weights summing to 100 (TMA, EMA199, RSI, ADX, HTF, S/R, vol) | No new votes. Ribbon / BOS / sweep stay cut |
| ADX≥20, DI+>DI− for GREEN | Radar enter_adx=25 / exit_adx=20; live `sig_min_adx` still **0.0**; measurement protocol ADX≥20 | **Next knob after 4h is live** (`strategy/reviews/2026-08-25.md`) |
| `too_late` hard block | Radar `is_late_stage` (GREEN ≥30d and ≥50% since flip) — chase-risk, not a hard A/A+ block | Overlay: checklist SKIP. Not an 8th score |
| Coil / ATR compression | Radar tight GREY coils + coil-UP (`QMIE-DailyBreakout`, unranked) | Already a screen, not A/A+ |
| SPY SMA200 + RV≤75 | `daily_trend` (close vs EMA199); `ALLOC_MODE=rotation` BTC-weak → CASH/PAXG. Live default is **ranked** | Crypto analog is **BTC 1D vs EMA200 + vol%**, not SPY |
| Universe RS | Ranked allocator by QMIE score, `cluster_max=1`; ARS `norm_score` is lookback ROC | Measure rotation vs ranked **after** 4h. Do not add z_mom / z_52 / EWMAC |
| ATR×2.5 stop, 1.25% equity | Info-only SL **1.5×ATR** / TP **2.5×ATR**. Desk `quantity` always 0 | Operator math only. Changing SL to 2.5 ATR needs a **new** frozen OOS |
| SMA20 trail, BE at +3%, 0.93×peak | Backtest ATR-trail **column**; frozen write-up: trail does not beat 1.5/2.5 on A/A+ | Research-only until a new outcome model is frozen |
| Hold GREY / exit RED | Radar is context; paper exits are SL/TP first-touch | Operator policy on discretionary holds, not the paper engine |
| 2-loss cooldown | None | Operator checklist. Do not code until 4h+ADX are measured |
| EOD email GREEN_FLIP | Discord/Telegram radar digest (optional) | Not Resend. Not an equity pipeline |
| Discretionary final click | Matches QMIE: alerts + SCREENS + GO/WATCH/SKIP | Keep. Never auto-execute |

## Review asks

### 1. Fit vs dashboard risk limits (max DD, per-trade risk, overnight hold)

QMIE goals (`strategy/goals.yaml`) are Sharpe ≥ 1.0, E[R] ≥ 0.15,
win% ≥ 48, max DD ≤ 20%. Frozen OOS DD is in **R units**, not account %
(`docs/backtest-baseline.md`). Combined 1h+4h A/A+ OOS: win 42.1% (below
48), E[R] +0.122 (below 0.15), Sharpe 1.30. **4h A/A+** already clears
the numeric goals: win 49.1%, E[R] +0.309, PF 1.61, Sharpe 2.09.

KovaView 1.25% equity / ATR×2.5 is a **prop sizing policy**. QMIE prints
info-only 1.5×ATR SL and never sizes shares (`quantity` 0). Map 1.25%
(or a tighter prop daily-loss cap) in the operator’s head:  
`shares = floor(risk$ / (ATR×k))` — do not grow a broker path.

Overnight hold of 2–7 weeks is an **equity EOD** horizon. QMIE paper
holds until first touch of 1.5/2.5 ATR or 100 bars (~4–17 calendar days
on 4h). Crypto “overnight” is 24/7 funding, not a NYSE gap. Do not
import a 7-week SMA20 trail as the live paper exit without a new frozen
table. Discretionary operators may trail winners **after** the printed
TP if their account DD cap allows it — that is off-engine.

**Acceptable fit:** use QMIE’s printed stop as the risk unit; cap
notional so one loser ≤ min(1.25% equity, prop max daily loss). Do not
widen the engine stop to 2.5 ATR to “match KovaView.”

### 2. Should SPY-centric regime generalize to BTC/ETH?

**Yes as an overlay, never as SPY inside a crypto book.** Analog:

- **BTC 1D close ≥ EMA199/200** already exists as `daily_trend` and a
  checklist item. Treat bearish daily vs a BUY as SKIP/WATCH, not a new
  vote.
- **Realized-vol percentile ≤ 75** is not live. Rotation’s cash gate is
  lookback ROC + `btc_weak` (`scanner/rotation.py`), and live
  `ALLOC_MODE` is ranked, not rotation.
- ETH as a *second* confirmation is optional later. Do not AND BTC and
  ETH in the same cycle as 4h or ADX.

Do **not** make KAMA the 8th score component. If a KAMA *gate* is ever
measured, it is `buys_allowed`-style (prior close vs long AMA), one
variable, after 4h and ADX, with Pine parity + tests. The notebook
itself says KAMA is a filter, not alpha.

### 3. Priority of universe RS vs more entry polish

**Agree with KovaView: RS / book construction outranks entry polish.**
Do not add EWMAC, z_52, up-day volume, or oscillator soup to `W_*`.

QMIE already ranks by score and caps clusters. The next RS-like
measurement is `ALLOC_MODE=ranked` vs `rotation` (lookback ROC, cash,
BTC-weak) **after** `SCAN_TIMEFRAMES=4h` is live and journaled. A full
universe RS rank across 30 perps is a later overlay, not a reason to
touch `compute_signal`.

### 4. Is ~50–60% WR / fat-tail trail OK for discretionary prop use?

**Win rate in that band is acceptable if expectancy stays ≥ 0.15R and
the operator caps account DD.** Frozen **4h A/A+** is already 49.1% WR
with **fixed** 1.5/2.5 ATR (not a % trail) and E[R] +0.309. Combined
1h+4h 42.1% WR is below the 48% goal because **1h dominates** — that is
why the outstanding knob is 4h-only, not KAMA.

Fat-tail SMA20 trails (22–41 day holds, +1.4–1.6% average on a five-name
equity sample) are a **different outcome model**. QMIE’s ATR-trail
column did not beat fixed TP/SL on A/A+ enough to change the engine.
Paper journal ~64% WR is mostly paper/qa 1h fills — not that evidence
(`strategy/reviews/2026-08-25.md`).

For prop: 50–60% WR with a wide trail is psychologically fine **if**
losers are ATR-capped and two-loss cooldown is operator-enforced. It is
not a reason to replace 1.5/2.5 or to treat leave-GREEN (33% WR, +0.15%)
as the live path.

## What to steal (order). What not to.

Still first, **unapplied:** `SCAN_TIMEFRAMES=4h`. Then catalog
`sig_min_adx` 0→20. Do not change both. Do not skip ahead to KAMA
because a notebook is interesting.

| After 4h is live and measured | Why |
|---|---|
| `sig_min_adx` 0→20 | Aligns with GREEN ADX≥20; already in the frozen protocol |
| `too_late` → checklist SKIP | Radar late-stage already exists; make it hard on GO |
| BTC 1D trend + optional vol% as `buys_allowed` | SPY analog. Overlay, not an 8th vote |
| Measure `ALLOC_MODE=rotation` vs ranked | Universe RS / regime leverage |
| 2-loss cooldown (operator only — do not code) | 4h stream is not one EOD setup |

**Never from this brief / notebooks**

- Port `quality_rank` or add KAMA / EWMAC / z_52 / volume-up-day to
  `compute_signal`
- Optuna per symbol in production (the KAMA notebook’s cautionary tale)
- Import TQQQ EMA(4,119,139) or re-search 9/90/199
- Silent SL 1.5→2.5 ATR or SMA20 trail as the paper engine
- Share sizing, Resend equity EOD, SPY SMA200 on perps
- Treat illustrative % returns as QMIE R-expectancy

## Landed

Native checklist overlays (not `compute_signal`, not `.env`):

- **`too_late`** — radar `is_late_stage` same-side chase → SKIP
- **`btc_regime`** — BTC 1D RED blocks new BUY (`buys_allowed` false). GREY is WATCH. SELL is not gated. Missing BTC row is WATCH, not SKIP
- **Cooldown is not coded.** Book-wide two-loss skip locked 4h A/A+ (606→2). Leave skip-next as an operator habit, not a checklist gate.

GUIDE section `kovaview` points here. Measurement:
`docs/kovaview-overlay-backtest.md` (BTC/ETH/SOL 4h A/A+ OOS).
`places_orders` stays false. Quantity on the desk DAG stays 0.

**Still not landed (on purpose)**

- KAMA / EWMAC / z_52 as score votes
- `SCAN_TIMEFRAMES=4h` and `sig_min_adx=20` (one outstanding knob, then catalog)
- Realized-vol percentile, SMA20 trail, ATR×2.5 paper stop, share sizing
- Switching live `ALLOC_MODE` to rotation
- Two-loss / 24h cooldown as a checklist SKIP
