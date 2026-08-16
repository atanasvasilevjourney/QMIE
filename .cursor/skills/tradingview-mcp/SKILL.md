---
name: tradingview-mcp
description: >-
  Use the project TradingView MCP (atilaahmettaner/tradingview-mcp via
  uvx) for live screeners, third-party TA, news, and MCP backtests.
  Never mix those numbers into QMIE scoring weights.
---

# TradingView MCP (shadow stdio)

`.cursor/mcp.json` launches `tradingview-mcp-server` with `uvx`.
This is a **shadow MCP** (not Runlayer). Prefer a Runlayer-managed
TradingView server if one appears later.

## When to use

- "screen crypto gainers", "TA on BTC", "multi-timeframe gold"
- News / Reddit-style sentiment tools on the MCP
- The MCP's own backtest tools (separate from `python -m backtest.run`)

## Hard rules

1. **QMIE scoring stays 7-component Pine-parity.** Do not change
   `W_*`, `signal_engine.py`, or `quant_visualizer.pine` because an
   MCP tool returned a different RSI/ADX/grade.
2. **Do not treat MCP backtests as `docs/backtest-baseline.md`.**
   Frozen OOS for QMIE is the Python harness on closed bars.
3. **No execution.** MCP output is informational. No broker, no
   HyperLiquid, no "place this trade".
4. **Do not `npx -y` other MCP servers.** Do not point this config
   at pro.cryptosieve.com unless the operator asks for that remote.
5. **Cannot push QMIE → Pine alerts.** Visual verify = Discord
   deep-link + `quant_visualizer.pine` labels on the same bar.
   Pine `alert()` can POST to `/webhook`; that is chart → server.

## If tools are missing

The cloud agent often cannot spawn this stdio server. Tell the
operator to install `uv`, reload Cursor, and enable **tradingview**
under Settings → MCP. Then retry.
