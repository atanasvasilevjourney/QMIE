# Spaceman module — improvement plan

Engineering plan for the **active perps / flow** desk path (`DeskPersona = spaceman`).
Complements **Space Observer** (swing digest). QMIE stays **signal-only** — no broker,
no tick streaming into `compute_signal`, no `W_*` changes without frozen-OOS proof.

**As of:** persona gate + `GET /flow/screener` v1 (OI, bar-Δ, CVD slope, funding table).

---

## 1. Product definition

### Who Spaceman is for

Operators who watch **positioning and aggression** (OI, CVD, funding, value area)
on **USDT perps**, often intraday-ish, but still **manual entry** on the exchange /
TradingView — not bot execution.

### Jobs to be done

| Job | Success looks like |
|-----|-------------------|
| See **who is crowded** | OI level + Δ vs recent baseline, per symbol |
| See **who is being bought/sold aggressively** | Bar-CVD (later: divergence vs price) |
| **Combine** with existing edge | TEMA grade + flow rank on one screener |
| **Act** with context | Alert / desk row shows flow chips + TV link |
| **Review** | Journal + optional flow snapshot at entry time |

### Non-goals

- Hyperliquid trading API, CCXT private keys, order placement
- Sub-minute WebSocket fused into the 7-component score
- Pine retune from MCP or flow panel
- Footprint / L2 unless explicitly phase-4 research

---

## 2. Architecture (target)

```
┌─────────────────────────────────────────────────────────────────┐
│                     ScannerScheduler (unchanged)                 │
│  closed 4h/1h → SignalEngine → Dispatcher → SQLite signals      │
└───────────────────────────────┬─────────────────────────────────┘
                                │ same signals
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              FlowScheduler (new, bar-close aligned)              │
│  after TEMA pass OR on 1h close: snapshot flow per symbol      │
│  → SQLite flow_snapshots (symbol, tf, bar_ts, oi, delta, …)     │
└───────────────────────────────┬─────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
 GET /flow/screener      GET /flow/{symbol}     attach on dispatch
 (ranked table)          (detail + series)       flow_context JSON
        │                       │
        └───────────┬───────────┘
                    ▼
            Spaceman desk (Flow tab + Ops overlays)
            Agents checklist (WATCH rules, not REJECT by default)
```

**Principle:** Flow is **parallel overlay**. TEMA remains source of grade; flow
**ranks, enriches, and optionally gates** via config (one knob at a time in review).

---

## 3. Data layer (phased)

### Phase A — Bar-close fundamentals (extend v1)

| Field | Source | Notes |
|-------|--------|-------|
| `open_interest` | REST per venue | Binance `/openInterest`, OKX `/open-interest`, Bybit OI history |
| `oi_change_pct` | OI hist 2× 4h (or 1h) | OKX: add hist if API allows; else skip Δ |
| `bar_delta` | `2*takerBuyBase - volume` (Binance klines) | Already partially implemented |
| `cvd_slope` | cumsum(delta) over N closed bars | Tunable lookback (default 6× tf) |
| `funding_rate` | existing `fetch_premium_index` | Already on live path |
| `price_change_pct` | same kline window | For OI+price quadrant labels |

**Venue parity:** Every payload includes `data_source`. Desk shows badge when
`SCAN_DATA_SOURCE=okx` ≠ Binance Pine chart.

**Implementation:**

- Move fan-out out of on-demand `/flow/screener` into **cached snapshots**
  (see Phase B).
- Extend `exchange_clients` only with small REST helpers (no new SDK deps).
- Persist `takerBuyBase` in an internal kline fetch used by flow only (do not
  widen public `fetch_klines` OHLCV schema unless tests require it).

### Phase B — Snapshot store + scheduler hook

**Table `flow_snapshots`** (aiosqlite):

- `symbol`, `timeframe`, `bar_close_ts` (ms), `oi`, `oi_change_pct`,
  `bar_delta`, `cvd`, `cvd_slope`, `funding_rate`, `delta_source`, `created_at`
- Unique `(symbol, timeframe, bar_close_ts)`

**FlowScheduler:**

- Runs on same closed-bar clock as scanner (4h primary; optional 1h for Spaceman
  refresh **desk-only**, not Telegram spam).
- Writes snapshot batch after universe scan (reuse symbol list from scheduler).
- `/flow/screener` reads **last snapshot per symbol** (fast, no N× REST per click).

**Retention:** 30–90 days rolling (match Binance OI hist limit); prune job daily.

### Phase C — Value / TPO-lite (swing-friendly active context)

| Field | Method |
|-------|--------|
| `poc`, `vah`, `val` | Session VP from **30m closed bars** (24–48h window) |
| `dist_to_poc_pct` | vs last 4h close |

Library option: vendored POC math or minimal copy from `py-market-profile` pattern
— **one dependency max**, evaluated in review if added.

No tick TPO in v1; label UI **“VA lite (30m bars)”** to set expectations.

### Phase D — Divergence + alerts (optional product)

- **CVD divergence:** price 4h high/low vs CVD high/low over lookback (same math
  as research bots; unit tests on synthetic series).
- **OI alerts:** Discord/Telegram optional template “OI +12% 4h, price +3%” —
  dedup key `symbol|flow|oi_spike|bar_ts`.
- **Never** auto-trade; max N alerts per day config.

### Phase E — Research (not live until measured)

- Long/short ratio, liquidation streams (venue-specific, often noisy)
- Tape CVD from aggTrades (separate **research** script, not scheduler)
- Backtest: do flow gates improve **4h A/A+** PF on frozen split
  (`docs/backtest-baseline.md`)? Only then optional `sig_flow_*` gate.

---

## 4. API surface (target)

| Endpoint | Purpose |
|----------|---------|
| `GET /flow/screener` | Ranked rows + join latest TEMA grade (exists; refactor to snapshots) |
| `GET /flow/{symbol}` | Time series last K snapshots + VP levels |
| `GET /flow/leaderboard?view=` | Presets: `oi_up`, `cvd_up`, `divergence_bull`, `crowded_long` |
| Signal payload | `flow_context` on stored alert + Discord field |

Query params: `timeframe=4h|1h`, `limit`, `view`.

---

## 5. Desk UI — Spaceman module

### Information architecture

Consolidate Spaceman into **Flow** as home (already default tab), with sub-views:

1. **Leaderboard** (default) — sortable table: symbol, grade, OI Δ, CVD slope,
   funding, POC distance, quadrant tag (`long_build`, `short_cover`, …).
2. **Symbol drill-down** — sparkline CVD + OI (SVG, no new chart library); link
   to CHARTS + TradingView.
3. **Ops link** — “Open in Ops table” for same symbol (shared selection state).

### UX rules (from `web/DESIGN.md`)

- Orbis WebGL stays dark; Flow panels follow theme.
- IBM Plex Mono for numbers; no 10px table text.
- Empty state: one dashed line + data_source hint if geo-blocked.

### Spaceman-specific chrome

- Top bar: **Switch crew**, persona badge, **Sync** refreshes flow cache.
- Optional: compact **“Flow pulse”** strip on Ops when persona=spaceman (later).

---

## 6. Agents / checklist integration

Extend native checklist (`improve/checklist.py`) with **read-only flow rules**:

| Condition | Verdict bump |
|-----------|--------------|
| A/A+ long + negative CVD slope | WATCH (not SKIP) |
| A/A+ long + extreme positive funding + OI spike | WATCH |
| Flow data missing | no change |

Briefing poll **must not** call OpenAI; flow fields come from SQLite snapshot only.

---

## 7. Testing & quality

| Layer | Tests |
|-------|--------|
| `flow_metrics.py` | Synthetic delta/CVD/divergence; mocked aiohttp OI JSON |
| Scheduler hook | Snapshot written once per bar; no double-write |
| API | `/flow/screener` returns stable schema; 503 when scanner down |
| UI | Component tests optional; manual: Spaceman path smoke |
| Regression | `test_no_scan_before_bar_close_grace` unchanged |

**CI:** no network; use `_FakeSession` patterns from `test_exchange_clients.py`.

---

## 8. Rollout phases (recommended order)

### Sprint 1 — Cache & correctness

- [ ] `flow_snapshots` table + migration in `db.py`
- [ ] FlowScheduler hook on 4h bar close (batch write)
- [ ] Refactor `/flow/screener` to read DB; join `recent_signals` grade
- [ ] OKX OI Δ if endpoint supports; document gaps
- [ ] Flow tab: sort columns, data_source banner, refresh on Sync

### Sprint 2 — Leaderboard intelligence

- [ ] OI+price quadrant labels
- [ ] `GET /flow/leaderboard?view=…`
- [ ] Attach `flow_context` to new dispatches (dispatcher)
- [ ] Discord embed optional fields (config flag)

### Sprint 3 — Value lite + drill-down

- [ ] 30m VP POC/VAH/VAL per symbol (session UTC or exchange session — pick one, document)
- [ ] `GET /flow/{symbol}` series for SVG sparklines on Flow tab
- [ ] CHARTS tab: optional VA band overlay when persona=spaceman

### Sprint 4 — Divergence & alerts

- [ ] Divergence detector + unit tests
- [ ] Optional flow alerts (dedup + daily cap)
- [ ] Checklist WATCH rules

### Sprint 5 — Evidence

- [ ] Notebook or `backtest/` slice: flow gates vs 4h A/A+ OOS
- [ ] One-knob proposal in `strategy/reviews/` if justified; **do not** apply without sign-off

---

## 9. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| REST rate limits on live screener | Snapshot on bar close only |
| Binance 451 on Cloud VM | OKX source + clear UI labeling |
| Proxy CVD ≠ tape truth | Show `delta_source`; prefer taker when available |
| Scope creep into execution | PR checklist: no private API imports |
| Pine drift | Flow never in `compute_signal` until Pine parity spec exists |

---

## 10. Open decisions (need product call)

1. **Default Spaceman tf:** 4h only vs 4h table + 1h “pulse” sub-tab?
2. **Alerts:** flow-only Discord channel or same webhook with tag?
3. **VP session:** UTC day vs rolling 24h vs exchange maintenance window?
4. **Gate hardness:** WATCH-only forever vs optional suppress like funding?

---

## 11. References in repo

- Persona / nav: `web/src/deskNav.ts`, `web/src/hooks/usePersona.ts`
- Flow v1: `python/scanner/flow_metrics.py`, `GET /flow/screener` in `main.py`
- Data policy: `docs/streaming-data-sources.md`
- Scoring invariants: `CLAUDE.md` (Pine parity, closed-bar, no broker)
- Review discipline: `python/improve/review.py`, `docs/backtest-baseline.md`
