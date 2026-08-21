# Streaming / live crypto data vs QMIE

Research note after the Cloud VM geo-block (Binance `fapi` HTTP 451,
Bybit CloudFront 403). QMIE stays **signal-only**. This is market
**data**, not a broker.

The scanner does **not** need tick streaming. It already waits for a
**closed** 1h/4h bar (+ 5s grace) and scores Pine-compatible OHLCV.
A WebSocket of last prices would invite mid-bar alerts — that is a
regression (`test_no_scan_before_bar_close_grace`).

## What we probed on this VM (2026-08-21)

| Source | Protocol | Result | Use for QMIE score? |
|---|---|---|---|
| Binance USDT-M `fapi.binance.com` | REST klines | **451** geo-restricted | Yes, when unblocked (Pine venue) |
| Binance `fstream.binance.com` | WebSocket kline | **timeout** (same geo edge) | Same candles as REST; still blocked here |
| Bybit / bytick | REST | **403** country block | Alternate USDT perp, also blocked here |
| **OKX** `BTC-USDT-SWAP` | REST candles + funding | **200** | **Yes as geo fallback** (`SCAN_DATA_SOURCE=okx`). Not bit-exact vs `BINANCE:BTCUSDT.P` |
| Binance Vision | monthly zip | **200** | Backtests only (`python -m backtest.run`) |
| Yahoo / Kraken / CoinGecko | last price | **200** | Desk overlay only. Spot/index, not USDT-M |
| **Hyperliquid** `POST /info` `candleSnapshot` + `allMids` | REST | **200** from this VM | **No** — different venue (see below) |

Hyperliquid live 1h BTC print on this probe closed **77040** (coin `BTC`,
USDC perp). OKX SWAP last was **~76994**. They are not interchangeable
with Binance USDT-M or with `pine/quant_visualizer.pine` on
`BINANCE:BTCUSDT.P`.

## Binance API (USDT-M)

- REST: `GET /fapi/v1/klines` — already `BinanceClient`.
- Stream: `wss://fstream.binance.com/ws/<symbol>@kline_<tf>` pushes the
  **in-progress** bar every ~250ms, plus `x.k.x == true` on close.
- Geo: HTTP 451 / WS timeout from US-like Cloud IPs. A SOCKS proxy would
  dodge the block; we will not add one.
- Matches the visualizer. Keep as default `SCAN_DATA_SOURCE=binance`
  for operators who are not geo-blocked.

## Hyperliquid API

Public, no wallet:

- REST `POST https://api.hyperliquid.xyz/info`
  - `{"type":"candleSnapshot","req":{"coin":"BTC","interval":"1h",...}}`
  - `{"type":"allMids"}` — mid for ~900 coins
- WS `wss://api.hyperliquid.xyz/ws`
  `{"method":"subscribe","subscription":{"type":"candle","coin":"BTC","interval":"1h"}}`

**Leave it out of the scanner.**

- Perps are **USDC-margined**, coin id `BTC` not `BTCUSDT`.
- Prints ≠ Binance USDT-M ≠ the Pine chart we tell the operator to open.
- The rest of the HL surface is **exchange/wallet** (`userEvents`,
  `clearinghouseState`, order placement). QMIE deleted broker adapters
  on purpose. Wiring HL “because the candles work here” is how an
  execution path grows.
- `CLAUDE.md` / qmie-improve: no Hyperliquid.

If we ever want HL, it would be a **read-only overlay** (last mid on the
desk), never `compute_signal`, never `W_*`, never an order.

## Other open-source stacks (do not add)

| Project | What it is | Why not in QMIE |
|---|---|---|
| [cryptofeed](https://github.com/bmoscon/cryptofeed) | Normalized WS trades/books/candles | New runtime dep; tick-oriented; Binance still geo-blocked |
| [CCXT](https://github.com/ccxt/ccxt) / CCXT Pro | Unified REST+WS **and private trading** | New dep; private APIs are the broker path we removed |
| Tardis.dev | Historical tick replay (mostly paid) | Not closed-bar scanner data; not OSS for live |

OKX already covers the “Cloud VM needs USDT-perp OHLCV” hole with
`aiohttp` and no new packages.

## Recommendation

1. **Do not stream ticks into the score.** Keep closed-bar REST.
2. **Pine path:** Binance USDT-M REST when the operator’s network allows it.
3. **This Cloud VM:** `SCAN_DATA_SOURCE=okx` (session env; do not write
   `.env` unless you confirm). Confirm still on `quant_visualizer.pine`.
4. **Hyperliquid:** reachable here, wrong product for QMIE scoring.
   Do not integrate the HL trading API.
5. Desk `Sync: desk API unreachable` is **Vite `/qmie` → :8080`**, not
   Binance/HL. Open `http://127.0.0.1:5173` or the same-origin desk on
   `:8080` after CORS/fallback.
