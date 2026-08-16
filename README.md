# QMIE — Quant Multi-Asset Intelligence Engine

**Scanner Edition · Crypto-Focused · Manual-Entry**

A server-side multi-symbol crypto scanner that detects A/A+ trade setups
in real time and pushes alerts to Discord and Telegram. You execute
manually — no automated brokers, no API keys for trading, no prop-firm
guardrails to break.

**Status (Aug 2026):** live scanner ~90% of a shippable alert product;
intended system (scanner + measured edge + live feedback) ~75%. See
[`docs/development-status.md`](docs/development-status.md) for the
breakdown, known bugs, and the recommended sprint order.

---

## What it does

Every time a 1H or 4H bar closes (configurable), the server:

1. Pulls the latest 300 candles for each symbol in your universe
   (default: 30 USDT-perpetuals on Binance Futures)
2. Computes a 7-component weighted score (Supertrend + EMA200 + RSI +
   ADX + HTF + S/R + Volatility) — math identical to the Pine
   visualizer. Weights currently total 100.
3. Grades each signal A+ / A / B / C / REJECT
4. Ranks A/A+ (and optionally B) setups with **Ranked Asset
   Allocation** — top N long + top N short per timeframe, cluster cap
   so correlated names do not stack — then dispatches those slots to
   Discord and/or Telegram with a TradingView chart deep-link and a
   suggested book weight (not an order)
5. Persists every signal in SQLite for audit and later analysis

The companion **Pine visualizer indicator** runs locally on whatever
chart you open in TradingView, showing the same Supertrend + EMA + S/R
plots and the same dashboard. When the server alerts `BUY BTCUSDT 4H A
87/100`, you click the chart link, the indicator confirms the same
setup visually, you make the entry decision yourself.

Cursor can also talk to [atilaahmettaner/tradingview-mcp](https://github.com/atilaahmettaner/tradingview-mcp)
via `.cursor/mcp.json` (`uvx` → `tradingview-mcp-server`). That is a
**shadow MCP** (not Runlayer). It is a screener / second-opinion TA
layer, **not** Pine-parity and **not** a QMIE scoring input. Setup:
[`docs/tradingview-mcp.md`](docs/tradingview-mcp.md).

---

## What it does NOT do

* No order execution. No broker API keys. No fills, no SL/TP placement,
  no cancels. Manual entry only.
* No forex, no indices, no equities, no futures. Crypto only — by
  design. Each market has its own volatility regime, session structure,
  and microstructure. One scoring engine cannot serve all of them well.
* No "autonomous AI trader" — no Hermes, Signum, HyperLiquid, or
  LLM that places orders. The Cursor review agent proposes **one**
  parameter change from journal vs `strategy/goals.yaml`. The scanner
  math stays deterministic and Pine-parity.
* No order execution. The Python backtest harness (`python/backtest/`)
  measures historical hit rate of the same `compute_signal` engine;
  it does not place trades. Pine's strategy tester is still unreliable
  (repainting) — use the Python runner, not TradingView, for stats.

---

## Repository layout

```
qmie/
├── pine/
│   ├── quant_visualizer.pine          chart indicator (companion to scanner)
│   └── asset_rotation.pine            ARS-style rotation (ALLOC_MODE=rotation)
├── python/
│   ├── main.py                        FastAPI entry
│   ├── config.py                      pydantic settings
│   ├── models.py                      TVSignal, Grade, AssetClass
│   ├── db.py                          aiosqlite persistence
│   ├── security.py                    HMAC + idempotency
│   ├── scanner/
│   │   ├── exchange_clients.py        Binance + Bybit public REST
│   │   ├── indicators.py              Pine-compatible math
│   │   ├── signal_engine.py           7-component scoring
│   │   ├── symbol_universe.py         static + auto top-N volume
│   │   ├── scheduler.py               bar-close-aware loop
│   │   ├── allocator.py               ranked swing book + ARS rotation
│   │   ├── rotation.py               Lookback ROC, cash, dual, BTC-weak
│   │   ├── radar.py                  daily RGG + coil Trend Radar
│   │   └── dispatcher.py              dedup + notifier fan-out
│   ├── improve/
│   │   └── review.py                  one-variable weekly review (no .env writes)
│   ├── notifiers/
│   │   ├── discord.py                 themed embeds + TV deep link
│   │   └── telegram.py                MarkdownV2 + TV deep link
│   ├── requirements.txt
│   └── .env.example
├── strategy/
│   ├── goals.yaml                     success vs failure (Sharpe, DD, R)
│   ├── baseline.yaml                  frozen live knobs
│   └── reviews/                       dated one-variable proposals
├── .cursor/                           review agent / skill / /qmie-review
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
└── docs/
    ├── architecture.md                what runs where, why
    ├── development-status.md          completeness score + next sprints
    └── deployment.md                  ops runbook
```

---

## Quick start

```bash
git clone <repo> qmie && cd qmie
cp python/.env.example python/.env
$EDITOR python/.env                       # set DISCORD_WEBHOOK_URL at minimum

cd docker
docker compose --env-file ../python/.env up -d --build

# Sanity-check
curl -s localhost:8080/health | jq
curl -s localhost:8080/universe | jq
curl -s localhost:8080/allocation | jq    # last ranked swing book
```

The first 1H or 4H bar close after startup should trigger a scan pass —
watch the logs (`docker logs -f qmie`) and you'll see the scan
complete and any A/A+ grade alerts go out.

When you take a trade, journal it against the alert id from `GET /signals`:

```bash
curl -s localhost:8080/signals | jq '.[0].id'
curl -s -X POST localhost:8080/journal \
  -H 'content-type: application/json' \
  -d '{"signal_id":1,"fill_price":65000,"size":0.01,"notes":"took the A"}'
curl -s -X PATCH localhost:8080/journal/1 \
  -H 'content-type: application/json' \
  -d '{"exit_price":66200}'
curl -s localhost:8080/journal/stats
```

---

## Customising signal quality

Three knobs in `.env`:

| Setting | Effect |
|---|---|
| `SCAN_MIN_ALERT_GRADE` | `A+` only (very rare), `A` (default), `B` (noisier), `C` (firehose) |
| `SCAN_TIMEFRAMES` | More TFs = more signals. `4h` only is the cleanest. `1h,4h` is balanced. |
| `W_*` weights | Re-weight the seven components. Defaults sum to **100**. Rebalance all of them together. |

| `ALLOC_MODE` | `ranked` (default): top N long + top N short per TF. `all`: firehose. `rotation`: ARS lookback ROC into the strongest name (or CASH). |
| `ALLOC_TOP_LONG` / `ALLOC_TOP_SHORT` | Slots in the swing book (default 3 / 3). Ignored in rotation unless dual. |
| `ALLOC_CLUSTER_MAX` | Max names per correlated cluster (BTC / ETH / SOL / OTHER). `1` default; `0` = unlimited. |
| `ALLOC_WEIGHTING` | `rank` (n, n-1, …, 1) or `equal` inside each side. |
| `ALLOC_NORM_LENGTH` | Rotation lookback bars for ROC (default 20). |
| `ALLOC_NORM_THRESHOLD` | If every ROC is below this %, rotate to CASH (defensive 1). |
| `ALLOC_DUAL` | `true`: 50/50 the top two names that clear the threshold. |
| `ALLOC_DEFENSIVE2` | BTC-weak overlay: `off`, `cash`, `paxg`, `paxg_then_cash`. |
| `ALLOC_MA_FILTER` | If true, a name must also trade above its MA to be eligible. |

Suggested `weight_pct` is a 100-point risk budget for **you**. QMIE still does not place orders.

### Daily Trend Radar (RGG + coils)

Independent of the 1H/4H scoring scanner. Once per closed **daily** bar,
QMIE classifies every universe symbol:

| Bucket | Meaning |
|---|---|
| **GREEN / GREY / RED** | ADX(14)+DMI with hysteresis (enter 25 / exit 18) |
| **Fresh flips** | Color changed within `RADAR_FRESH_FLIP_DAYS` (default 3) |
| **Tight coils** | 20-day range width ≤ `RADAR_COIL_MAX_WIDTH_PCT` |
| **Breakouts** | Close outside prior tight-coil range |

```bash
curl -s localhost:8080/radar | jq '.green,.fresh_green,.breakouts,.tight_coils'
curl -s -X POST localhost:8080/radar/once   # force a pass (admin)
```

Digest goes to Discord/Telegram when `RADAR_NOTIFY=true`. Still **manual
entry only** — radar never places orders and never retunes `W_*`.

Weekly, score the journal against `strategy/goals.yaml` (one knob at a time):

```bash
cd python && python -m improve.review
# then open strategy/reviews/YYYY-MM-DD.md
```

Or ask the Cursor agent `/qmie-review`. It will not write `.env`.

On an A/A+ alert, `/qmie-setup` pulls TradingView MCP live TA (if the
server is enabled) through a **fixed** confirm/skip checklist
(`python -m improve.setup_review`). That does not change scores.
Backtest QMIE signals with `python -m backtest.run`, not MCP
`backtest_strategy`. Details: [`docs/tradingview-mcp.md`](docs/tradingview-mcp.md).

The volatility filter (`SIG_MIN_ATR_PCT` / `SIG_MAX_ATR_PCT`) suppresses
both dead-quiet and chaos regimes — leave defaults unless you have a
strong opinion.

---

## What you should still build

This is a complete signal-generation system. It is **not** a complete
trading system. Journaling fills is now built in (`POST /journal`).
What remains:

1. **Walk-forward write-up**: run `python -m backtest.run` with a frozen
   `--split` and paste the table into `docs/backtest-baseline.md`. Set
   `JOURNAL_OOS_WIN_PCT` from that A/A+ OOS win rate so live drift
   alerts have a baseline (needs ≥ 30 closed journal fills).

2. **Position sizing:** Ranked Asset Allocation is built in
   (`ALLOC_MODE=ranked`). Discord shows rank, suggested weight %, and
   cluster. You still size and click the order yourself.

3. **Do not refit weights** on the same sample you use to report hit
   rate. Measure first (Sprint 1).

---

## Honest limitations

* **Pine visualizer ↔ server parity is "very close" not "bit-exact".**
  Identical math, but tiny EMA/RMA seed differences exist between
  pandas and Pine on the very first valid bars. After ~5× the longest
  lookback (so ~1000 bars in this case) the values converge. Don't
  panic if a borderline B/A boundary signal disagrees on the very
  first scan after startup — let it warm up.

* **TradingView cannot receive arbitrary HTTP push from your server.**
  The Pine visualizer runs the same logic locally; that's how the
  chart "matches" the alert. Anyone selling you a "TradingView API"
  that injects custom marks onto retail charts is either selling the
  Charting Library license (~$$$) or lying.

* **Public REST has rate limits.** Binance fapi: ~2400 weight/min,
  each kline call is weight 1-10 depending on limit. With 30 symbols
  × 2 timeframes × HTF lookup = ~120 requests per pass, each weight
  ~5 → 600 weight per pass. Well under the limit but if you go
  >150 symbols, switch to WebSocket kline streams (separate work).

* **SQLite is fine for this scale.** Hundreds of signals/day max. If
  you scan 500+ symbols on 15m and want to retain a year of history
  for analysis, swap `DB_URL` for Postgres.
