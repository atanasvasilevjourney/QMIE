# TradingView MCP (Cursor)

Project MCP for [atilaahmettaner/tradingview-mcp](https://github.com/atilaahmettaner/tradingview-mcp)
(PyPI: `tradingview-mcp-server`). Config: `.cursor/mcp.json`.

## Governance warning — this is a shadow MCP

There is **no Runlayer-managed TradingView server** in this environment.
This entry is a **shadow MCP** (local stdio via `uvx`, not `runlayer.com`
and not `runlayer run <uuid>`). Shadow MCPs bypass org PBAC, audit
logging, and access controls.

If a Runlayer TradingView connector becomes available, migrate to that
URL and delete this stdio block.

Do **not** switch this to the paid hosted URL at pro.cryptosieve.com
unless you explicitly want a remote shadow MCP.

## Enable in Cursor

1. Install [`uv`](https://docs.astral.sh/uv/) so `uvx` is on your PATH.
2. Reload the window (or toggle the server in **Settings → MCP**).
3. First start can take a minute while `uvx` fetches the package.
4. Ask: `Show the available TradingView MCP tools.`

Optional news/sentiment: set `MARKETAUX_API_TOKEN` in the environment
(free tier at marketaux.com). Without it, those two tools no-op; the
rest still work. No TradingView account or API key is required.

## What it is for

Live screeners, third-party TA snapshots, news/sentiment, and the
package's own backtests — a second opinion next to QMIE alerts.

## What it is not

- **Not Pine-parity.** MCP indicators come from `tradingview-ta` /
  `tradingview-screener`, not `scanner/indicators.py`. Do not retune
  QMIE weights from MCP output.
- **Not the scanner.** QMIE remains the source of truth for A/A+
  alerts (`compute_signal` on closed 1H/4H bars).
- **Not a Pine alert bridge.** This MCP does not log into TradingView,
  does not fire Pine `alert()`, and cannot inject markers onto a
  retail chart. TradingView has no HTTP API for that. Do not use it
  to "send QMIE signals to Pine."
- **Not execution.** The MCP does not place orders. Neither does QMIE.

## How to visually verify a QMIE entry (already built)

Pine alerts flow **chart → server**, not server → chart.

```
QMIE scan (closed 1H/4H)
  → Discord/Telegram + TradingView deep-link
  → you open the chart with `pine/quant_visualizer.pine`
  → same 7-component math plots ▲/▼ on that bar
```

1. Add `pine/quant_visualizer.pine` to the chart once.
2. When Discord/Telegram fires, click the chart URL
   (`tv_chart_url()` → `symbol=BINANCE:BTCUSDT.P&interval=240`).
3. Confirm the visualizer label and dashboard match the alert
   (side, grade, score). That is the visual entry check.
4. Optional: Pine `alert()` on bar close can POST JSON to QMIE
   `/webhook` (HMAC) as a *redundant* copy of what the chart saw.
   That is the opposite direction of "server pushes to Pine."

Using this MCP as a "did the entry print?" check is the wrong
tool: its RSI/ADX will not match the visualizer, so a mismatch
would look like a bug when it is just a different library.

## AI-ruled overlay on a QMIE setup

MCP is a **confirm/skip** layer after QMIE already graded A/A+.
It does not become an 8th scoring component.

```
QMIE A/A+ alert
  → MCP yahoo_price + get_technical_analysis + get_multi_timeframe_analysis
  → python -m improve.setup_review --mcp-json mcp.json
  → CONFIRM | CONFLICT | INCOMPLETE
  → visualizer on the chart link (still manual)
```

Cursor command: `/qmie-setup`. Gates (fixed, not LLM vibe):

- QMIE directional A/A+
- MCP recommendation same side (HOLD fails)
- MCP HTF same side
- MCP RSI not extreme against the trade
- News/Reddit never gate

## Backtest

| What | Command / tool | Writes `docs/backtest-baseline.md`? |
|---|---|---|
| **QMIE signals** | `python -m backtest.run --split 2025-01-01 --min-adx 20 ...` | Yes, when you freeze OOS |
| **MCP generic strategies** | `backtest_strategy` / `walk_forward_backtest_strategy` | **No** — different math |
