# QMIE — Claude Code Project Notes

This file is loaded automatically when Claude Code opens this project.
It tells Claude what this codebase is, where things live, and how to
run / test it without you having to re-explain.

## What this is

QMIE is a server-side crypto market scanner. It scans ~30 USDT-perp
symbols on 1H and 4H timeframes, computes a 7-component weighted
score (Supertrend + EMA200 + RSI + ADX + HTF alignment + S/R room +
Volatility regime), and dispatches A/A+ signals to Discord and/or
Telegram with a TradingView chart deep-link. It does **not** execute
trades. Manual entry only — by design.

A companion Pine v6 indicator (`pine/quant_visualizer.pine`) runs the
same scoring math locally on TradingView so chart plots match server
alerts.

## Repo layout

```
qmie/
├── pine/quant_visualizer.pine        ← TradingView indicator
├── python/
│   ├── main.py                       FastAPI app
│   ├── config.py                     Pydantic Settings (env)
│   ├── models.py                     TVSignal, Grade, etc.
│   ├── db.py                         aiosqlite persistence
│   ├── security.py                   HMAC + idempotency
│   ├── scanner/                      ← the core
│   │   ├── indicators.py             Pine-compatible math (RMA, EMA, RSI, ADX, ATR, Supertrend, pivots)
│   │   ├── signal_engine.py          7-component scoring → A+/A/B/C/REJECT
│   │   ├── exchange_clients.py       Binance + Bybit public REST
│   │   ├── scheduler.py              Bar-close-aware loop
│   │   ├── dispatcher.py             Dedup + notifier fan-out + TV deep-link
│   │   └── symbol_universe.py        Static list + auto-top-N by volume
│   ├── notifiers/
│   │   ├── discord.py                Rich embed + chart link
│   │   └── telegram.py               MarkdownV2 + chart link
│   ├── tests/                        109 pytest tests, 74% coverage
│   ├── requirements.txt
│   ├── pytest.ini
│   └── .env.example
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── docs/architecture.md              How things fit + scaling cliffs
├── README.md
└── REVIEW.md                         Audit findings + test summary
```

## Running

```bash
cp python/.env.example python/.env     # then set DISCORD_WEBHOOK_URL + WEBHOOK_SECRET
cd docker
docker compose --env-file ../python/.env up -d --build
docker logs -f qmie
```

Health: `curl localhost:8080/health | jq`

## Testing

```bash
cd python
pip install -r requirements.txt pytest pytest-asyncio pytest-cov
pytest -v                              # 109 tests, ~2s
pytest --cov=. --cov-report=term       # with coverage
```

To run a single suite:
```bash
pytest tests/test_indicators.py -v
pytest tests/test_signal_engine.py::TestComputeSignal::test_clear_uptrend_yields_buy -v
```

## Critical math invariants (do not break)

1. **Pine parity.** Server signals must match what the user sees in
   `pine/quant_visualizer.pine` on the same candles. If you touch
   `scanner/indicators.py` or `scanner/signal_engine.py`, change the
   corresponding Pine code in the same commit and add a regression test.

2. **RMA = SMA-seeded recurrence**, not pandas' default ewm. See
   `indicators.rma()`. This is required for bit-exact match with Pine's
   `ta.rma`. Changing this will silently desync the visualizer from
   the server.

3. **Triple-Supertrend agreement is in {±1, ±3}, never ±2.** The
   scoring threshold is `>= 1` so 2/3 majority signals are counted
   at 1/3 strength. A previous version had `>= 2` which silently
   dropped these — that is a regression we never want again. See
   `test_partial_supertrend_agreement_scored`.

4. **Closed-bar discipline.** The scheduler only fires 5s after a
   bar close, never mid-bar. Don't lower the grace window without
   re-running `test_no_scan_before_bar_close_grace`.

5. **Notifier failures must NOT raise into the dispatcher.**
   `asyncio.gather(..., return_exceptions=True)` is load-bearing —
   a failing Discord must not break Telegram, and vice versa. See
   `test_notifier_failure_isolated`.

## Conventions

- Python 3.12. Type hints throughout.
- No new runtime dependencies without strong justification — the
  current set is intentionally small (FastAPI, pydantic, aiohttp,
  aiosqlite, pandas, numpy, redis).
- `async` everywhere in the request path. `httpx` is not used —
  we standardized on `aiohttp` for the exchange clients and for the
  notifiers.
- Tests use synthetic OHLCV fixtures from `tests/conftest.py`. No
  network calls in tests — exchange responses are mocked with
  `_FakeSession` / `_FakeResp` patterns.

## What this project is NOT

- A backtest framework (use Jesse or a Python notebook with
  `scanner.signal_engine.compute_signal` on historical klines)
- An execution system (deliberately no broker adapters)
- A multi-asset platform (crypto USDT perps only by design)

If a request would take it in any of those directions, push back and
ask for confirmation that the scope is intentionally changing.
