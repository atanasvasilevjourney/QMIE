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
- **Not execution.** The MCP does not place orders. Neither does QMIE.
