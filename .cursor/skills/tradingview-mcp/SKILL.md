---
name: tradingview-mcp
description: >-
  Use the project TradingView MCP for live quotes, ruled TA overlay on
  QMIE A/A+ setups, and generic MCP backtests. Never mix MCP numbers
  into QMIE scoring weights. Trigger on setup review, entry confirm,
  screener, or "use the MCP".
---

# TradingView MCP — live data + ruled overlay

`.cursor/mcp.json` launches `tradingview-mcp-server` with `uvx`.
**Shadow MCP** (not Runlayer). Prefer Runlayer if a managed TV server
appears later.

This cloud agent often has **no** `tradingview` tools. On the operator's
Cursor desktop they appear after `uv` is installed and the server is
enabled. If tools are missing, still run `python -m improve.setup_review`
without `--mcp-json` (verdict `INCOMPLETE`).

## When to use

- `/qmie-setup` or "confirm this entry with MCP"
- Live quote / screener / third-party TA
- Generic MCP strategy backtest (label it MCP, not QMIE OOS)

## Setup overlay (AI-ruled, not vibe)

QMIE grade is already computed. You only **confirm or skip**.

Discover tools with the MCP catalog, then call (names as in
atilaahmettaner/tradingview-mcp):

| Job | Tool | Map into snapshot |
|---|---|---|
| Last price | `yahoo_price` (`BTC-USD`) | `yahoo_last` |
| TA rec + RSI | `get_technical_analysis` | `recommendation`, `rsi` |
| HTF bias | `get_multi_timeframe_analysis` | `htf_bias`: bullish/bearish/mixed |
| News/Reddit | `combined_analysis` / `market_sentiment` | `sentiment` **info only** |

Write `mcp.json` and run `python -m improve.setup_review ... --mcp-json mcp.json`.

Fixed gates (see `improve/setup_review.py`):

1. QMIE side BUY/SELL and grade A/A+.
2. MCP recommendation same side (HOLD = fail).
3. MCP HTF same side.
4. MCP RSI not ≥75 on BUY, not ≤25 on SELL.
5. Sentiment never gates.

Verdicts: `CONFIRM` (open visualizer, still manual) /
`CONFLICT` (skip, do not retune `W_*`) /
`INCOMPLETE` (MCP missing).

## Backtest

**QMIE signals** (the real one):

```bash
cd python && python -m backtest.run --symbols BTCUSDT ETHUSDT --tf 1h 4h \
  --start 2024-01-01 --split 2025-01-01 \
  --min-adx 20 --min-atr-pct 0.4 --max-atr-pct 4.0
```

Write the table to `docs/backtest-baseline.md` only when the operator
asks to freeze OOS.

**MCP generic strategies** (optional extra): `backtest_strategy` or
`walk_forward_backtest_strategy` on `supertrend` / `rsi` for the Yahoo
symbol. Say clearly: this is not Pine-parity and not QMIE expectancy.

## Hard rules

1. Do not change `W_*`, `signal_engine.py`, or Pine from MCP output.
2. Do not treat MCP backtests as `docs/backtest-baseline.md`.
3. No execution. No HyperLiquid. No extra `npx` MCP servers.
4. Cannot push QMIE → Pine. Visual verify = chart link + visualizer.
5. Do not install OpenClaw / Hermes to wrap this MCP.
