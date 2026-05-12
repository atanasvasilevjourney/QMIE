# QMIE — Quant Multi-Asset Intelligence Engine

**Scanner Edition · Crypto-Focused · Manual-Entry**

A server-side multi-symbol crypto scanner that detects A/A+ trade setups
in real time and pushes alerts to Discord and Telegram. You execute
manually — no automated brokers, no API keys for trading, no prop-firm
guardrails to break.

---

## What it does

Every time a 1H or 4H bar closes (configurable), the server:

1. Pulls the latest 300 candles for each symbol in your universe
   (default: 30 USDT-perpetuals on Binance Futures)
2. Computes a 7-component weighted score (Supertrend + EMA200 + RSI
   + ADX + HTF alignment + S/R room + Volatility) — math identical
   to the Pine visualizer
3. Grades each signal A+ / A / B / C / REJECT
4. Dispatches the qualifying ones to Discord and/or Telegram with
   a one-click TradingView chart deep-link
5. Persists every signal in SQLite for audit and later analysis

The companion **Pine visualizer indicator** runs locally on whatever
chart you open in TradingView, showing the same Supertrend + EMA + S/R
plots and the same dashboard. When the server alerts `BUY BTCUSDT 4H A
87/100`, you click the chart link, the indicator confirms the same
setup visually, you make the entry decision yourself.

---

## What it does NOT do

* No order execution. No broker API keys. No fills, no SL/TP placement,
  no cancels. Manual entry only.
* No forex, no indices, no equities, no futures. Crypto only — by
  design. Each market has its own volatility regime, session structure,
  and microstructure. One scoring engine cannot serve all of them well.
* No "AI" — no neural nets, no LLM trading, no reinforcement learning.
  Just deterministic indicator math, which means it's auditable and
  every signal is reproducible from the candle data alone.
* No backtest engine bundled. Backtesting Pine on TradingView's strategy
  tester is unreliable (repainting). Use a proper Python backtester
  with the same `scanner/signal_engine.py` logic if you want stats.

---

## Repository layout

```
qmie/
├── pine/
│   └── quant_visualizer.pine          chart indicator (companion to scanner)
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
│   │   └── dispatcher.py              dedup + notifier fan-out
│   ├── notifiers/
│   │   ├── discord.py                 themed embeds + TV deep link
│   │   └── telegram.py                MarkdownV2 + TV deep link
│   ├── requirements.txt
│   └── .env.example
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
└── docs/
    ├── architecture.md                what runs where, why
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
```

The first 1H or 4H bar close after startup should trigger a scan pass —
watch the logs (`docker logs -f qmie`) and you'll see the scan
complete and any A/A+ grade alerts go out.

---

## Customising signal quality

Three knobs in `.env`:

| Setting | Effect |
|---|---|
| `SCAN_MIN_ALERT_GRADE` | `A+` only (very rare), `A` (default), `B` (noisier), `C` (firehose) |
| `SCAN_TIMEFRAMES` | More TFs = more signals. `4h` only is the cleanest. `1h,4h` is balanced. |
| `W_*` weights | Re-weight the seven components if you want stronger HTF bias, less RSI, etc. They sum to 100; rebalance whole-numbers. |

The volatility filter (`SIG_MIN_ATR_PCT` / `SIG_MAX_ATR_PCT`) suppresses
both dead-quiet and chaos regimes — leave defaults unless you have a
strong opinion.

---

## What you should still build

This is a complete signal-generation system. It is **not** a complete
trading system. Things you still need to do yourself or extend:

1. **Trade journaling**: log every manual entry (price, size, why) so
   you can compare actual P&L against the signal universe stats. The
   `/signals` endpoint gives you the audit trail of what was alerted;
   you need to track what you *acted on*.

2. **Performance attribution**: build a small notebook that joins
   `signals` table with your manual fills to compute hit rate per
   grade, per timeframe, per symbol. The whole point of the grading
   system is to verify it predicts edge — assume nothing, measure it.

3. **Position sizing discipline**: a server that fires 10 A-grade
   alerts per day cannot tell you which 3 to take. You need an
   external rule (e.g. max 2 concurrent, max 1 per asset cluster
   ETH/SOL/AVAX, no entries in last hour of session, etc.).

4. **Walk-forward validation of the scoring engine**: refit the
   weights against your own historical fill data once you have ≥ 100
   trades. The defaults are reasonable but not optimal for any
   particular market regime.

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
