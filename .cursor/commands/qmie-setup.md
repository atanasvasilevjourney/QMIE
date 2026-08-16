---
name: qmie-setup
description: >-
  AI-ruled overlay on a QMIE A/A+ setup using TradingView MCP live data
  and TA. Does not retune weights. Does not place orders.
---

# /qmie-setup

Confirm or skip a QMIE alert with **fixed rules** plus TradingView MCP
tools. Follow `.cursor/skills/tradingview-mcp/SKILL.md`.

## Inputs

Symbol + timeframe (from Discord, `GET /signals`, or the user). Example:
`BTCUSDT 4h BUY A 84`.

## Steps

1. **QMIE card** — side, grade, score, RSI, ADX, HTF, daily trend.
   Do not recompute a new grade from MCP.
2. **MCP live data** (if `tradingview` tools exist):
   - `yahoo_price` on `BTC-USD` (see `yahoo_symbol()`)
   - `get_technical_analysis` on the Binance perp
   - `get_multi_timeframe_analysis`
   - Optional info only: `combined_analysis`, `market_sentiment`
3. Map MCP output into:

```json
{
  "recommendation": "BUY",
  "rsi": 48.0,
  "htf_bias": "bullish",
  "yahoo_last": 67000,
  "sentiment": "bullish"
}
```

4. Run:

```bash
cd python && python -m improve.setup_review \
  --symbol BTCUSDT --timeframe 4h --side BUY --grade A --score 84 \
  --rsi 52 --adx 28 --htf-aligned --daily-trend bullish \
  --mcp-json mcp.json
```

5. Report verdict: `CONFIRM` / `CONFLICT` / `INCOMPLETE`.
6. Visual check: Discord chart link + `quant_visualizer.pine`.
7. **Backtest QMIE signals** (not MCP strategies):

```bash
cd python && python -m backtest.run --symbols BTCUSDT --tf 1h 4h \
  --start 2024-01-01 --split 2025-01-01 \
  --min-adx 20 --min-atr-pct 0.4 --max-atr-pct 4.0
```

MCP `backtest_strategy` / `walk_forward_backtest_strategy` may run as a
**generic** Supertrend/RSI sanity check. Label it MCP, never as
`docs/backtest-baseline.md`.

If MCP tools are missing: still run setup_review without `--mcp-json`
(verdict INCOMPLETE) and tell the operator to enable **tradingview**
in Settings → MCP (`uvx` on PATH).
