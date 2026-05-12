# QMIE Architecture (Scanner Edition)

## Component map

```
                   ┌─────────────────────────────────────────────────┐
                   │                    QMIE Server                   │
                   │                  (single process)                │
                   │                                                  │
   Binance fapi    │  ┌────────────────┐    ┌────────────────────┐  │
   public REST  ───┼─▶│ ExchangeClient │───▶│  ScannerScheduler  │  │
   (no auth)       │  │  Binance/Bybit │    │  bar-close trigger │  │
                   │  └────────────────┘    │  per-TF dispatch   │  │
                   │                        └─────────┬──────────┘  │
                   │                                  ▼             │
                   │  ┌──────────────┐    ┌────────────────────┐   │
                   │  │ SymbolUniv.  │───▶│   SignalEngine     │   │
                   │  │ static+auto  │    │   7-comp weighted  │   │
                   │  └──────────────┘    │   A+/A/B/C/REJECT  │   │
                   │                       └─────────┬──────────┘  │
                   │                                  ▼             │
                   │   ┌─── persist ────┐   ┌────────────────────┐  │
                   │   │  SQLite        │◀──│  SignalDispatcher  │  │
                   │   │  (signals tbl) │   │  dedup + fan-out   │  │
                   │   └────────────────┘   └─────────┬──────────┘  │
                   │                                  │             │
                   │       ┌──────────────────────────┼──────┐      │
                   │       ▼                          ▼      ▼      │
                   │  ┌──────────┐              ┌──────────┐ ┌─────┐│
                   │  │ Discord  │              │ Telegram │ │ ... ││
                   │  │ embed    │              │ MarkdownV2│ │     ││
                   │  └────┬─────┘              └──────┬───┘ └─────┘│
                   └───────┼───────────────────────────┼────────────┘
                           ▼                           ▼
                   Discord channel              Telegram chat
                   (rich embed +                (markdown +
                    TV deep link)                TV deep link)
                                            │
                                            │ (user clicks link)
                                            ▼
                                   TradingView chart opens
                                   with QMIE Visualizer
                                   indicator showing the
                                   same signal locally
```

## Why this shape

### 1. Server is the source of truth, Pine is the visualizer.

The naïve approach is to put the scoring logic in Pine and let
TradingView fire alerts. That fails at three points:

- Pine `request.security` cannot scan more than ~40 symbols per
  script, and even at 40 the chart starts to lag.
- Pine alerts only fire when *that script* is loaded on a chart.
  Run scanner on 30 symbols × 2 TFs = 60 chart instances on the
  user's account. Doesn't scale.
- The user has no audit trail. Pine doesn't persist state.

The server-side scanner with a Pine *visualizer* solves all three:
the server scans 30+ symbols on a single process, persists every
signal, and the Pine indicator on the user's chart simply mirrors
the math so manual entry is informed.

### 2. Closed-bar discipline.

`ScannerScheduler` only triggers on the second AFTER a bar closes.
This matches Pine's `barstate.isconfirmed` semantics. The two cardinal
sins this prevents:

- **Mid-bar repaint.** A scan at 03:47 on a 4H chart computes
  Supertrend on a still-forming bar. By 04:00 that bar may close
  very differently and the score changes. Acting on the 03:47 score
  is acting on noise.
- **Bar-close double-fire.** If you scan every 30 seconds, a 4H bar
  close gets scanned 8 times in the next 4 hours. Dispatcher dedup
  handles it, but the scheduler cuts waste at the source.

### 3. Notifiers are fire-and-forget.

`asyncio.gather(..., return_exceptions=True)` so a Discord 503 never
breaks a Telegram send. Notifier failures are logged, never raised
to the dispatcher. The cost: a failed Discord message is lost (no
retry queue). Acceptable for a notification system; would be
unacceptable for an execution system, which is why we're not building
that.

### 4. Idempotency is keyed on `symbol|tf|side|bar_close_ts`.

If the scheduler re-fires (operator clicks `/scan/once`, restart
mid-bar, etc.), the same bar-close generates the same key and the
dispatcher silently drops the duplicate. The seen-set has a 30-minute
TTL by default — long enough to cover any reasonable retry window,
short enough to allow the next bar's signal through.

In production with multi-restart, set `REDIS_URL` so the seen-set
survives container restarts. With in-memory fallback, a restart
seconds after dispatch can re-fire the same alert.

---

## Scaling cliffs

| Workload | Approach | Cliff |
|---|---|---|
| ≤ 50 symbols × 2 TFs | Single process, public REST | None — current setup |
| 50–200 symbols × 3 TFs | Add WebSocket kline streams (Binance/Bybit both expose them) | aiohttp REST hits ~2 RPS per host before exchange rate-limits |
| 200+ symbols, multi-region | Postgres + Redis Streams; one scanner per region; reconcile via DB | SQLite write contention; in-memory dedup loses cross-process visibility |
| Live order execution | Re-add the broker adapter layer (deleted in this edition); needs prop-firm risk gate (also deleted) | Whole different system; do not lightly reintroduce |

---

## Where the math lives

`scanner/indicators.py` — every indicator must match Pine v6 semantics.
Critical: `rma()` uses `alpha=1/length, adjust=False`. Plain pandas
`ewm(span=n)` uses `alpha=2/(n+1)` and is wrong for ATR/RSI/ADX/Wilders.

`scanner/signal_engine.py` — the 7-component scoring is the same
function shape on both server and Pine. If you change it on one side,
change it on the other in the same commit. Otherwise the chart will
disagree with the alerts and the user will lose trust.

The Pine ST `direction` value is `-1` for uptrend (counterintuitive).
Both sides explicitly invert it to a `+1=up` convention to keep the
arithmetic identical.

---

## Failure modes and what they look like

| Symptom | Likely cause |
|---|---|
| `/health` returns `db_ok: false` | Volume mount missing in docker-compose; SQLite path not writable |
| Scanner runs but no Discord alerts | `SCAN_MIN_ALERT_GRADE` too strict, or `SIG_MIN_ATR_PCT` filtering everything in low-vol regime |
| Same signal fires twice | Container restart inside dedup TTL window; configure Redis or extend TTL |
| Pine visualizer disagrees with server | Different timeframe, different lookback (defaults must match `.env`), or warm-up window (first ~5 lookback periods) |
| `Binance HTTP 451` | You're scanning from a region Binance fapi blocks (US, UK without VPN). Switch `SCAN_DATA_SOURCE=bybit` |
| `Binance HTTP 403 Host not allowed` | Network egress blocked (firewall, container DNS). Test from inside the container with `curl https://fapi.binance.com/fapi/v1/ping` |
| Scanner loop crashes silently | Check logs for `Scheduler tick crashed` — exception isolated, loop continues, but you should fix the underlying issue |

---

## What changed from the broker edition

If you came here from the original spec that included Binance/Bybit/
Tradovate/IBKR adapters and a broker router: that whole layer was
removed. Files deleted:

- `python/adapters/` (entire directory: 5 broker adapters)
- `python/broker_router.py`
- `python/risk_manager.py` (prop-firm guardrails — irrelevant without execution)
- `python/queue_manager.py` (was for retrying failed broker submissions)

Files kept and unchanged in shape:
- `python/db.py` (now writes signals only, never orders)
- `python/security.py` (HMAC + idempotency still apply for the optional `/webhook`)
- `python/models.py` (`TVSignal` still the canonical signal model;
  `OrderIntent`/`BrokerResponse` still defined but only `TVSignal` is used)

If you want to re-introduce execution later, start from the dispatcher:
add a broker step BEFORE the notifier fan-out, with the same
`asyncio.gather` non-blocking pattern for notifiers but synchronous
broker submission. The earlier broker code is in git history.
