# 51bitquant/ai-hedge-fund-crypto vs QMIE

Review of [51bitquant/ai-hedge-fund-crypto](https://github.com/51bitquant/ai-hedge-fund-crypto)
(LangGraph DAG + MACD/RSI ensemble + LLM portfolio manager). QMIE stays
**signal-only**. This file is the take / leave list. The implemented analog
is `GET /agents/desk` (`python/improve/desk.py`).

## Their graph

```
start → data(tf…) → merge → strategy(MACD/RSI/BB) → risk (20% cash cap)
  → portfolio LLM (buy/sell/short/cover + quantity)
```

Their README: data nodes per interval (`5m`…`1d`), merge, then strategy
nodes, then risk, then an LLM portfolio manager. Live mode can take
Binance API keys. Portfolio prompt says it "generates orders". Gateway
is a vendored python-binance client. QMIE has no merge node — stored
closed-bar alerts + daily radar already are the unified state.

## Take (QMIE analog)

| Their node | QMIE node | Notes |
|---|---|---|
| Start | `start` | Init state. `places_orders: false`. |
| Data (multi-TF) | `data` | Closed-bar 1h/4h + daily radar. **No 5m/15m/30m.** |
| Strategy ensemble | `strategy` | **QMIE 7-component TMA only.** Not MACD/RSI/Bollinger extra votes. |
| Risk 20% cap | `risk` | Ranked book + cluster_max + checklist. Suggested `weight_pct`, not shares. |
| Portfolio LLM | `portfolio` | Template decisions: `suggest_long` / `suggest_short` / `watch` / `skip`. **quantity always 0.** LLM Take stays on-demand `GET /agents/analysis/{id}`. |

## Leave (explicit)

- LangGraph / langchain / new runtime deps
- MACD, RSI-as-strategy, Bollinger as extra score components
- Adaptive weights mixed into `W_*`
- Intraday mid-bar TFs
- Binance trading keys / gateway / buy-sell-short-cover quantities
- LLM as the grader or as a live order brain
- Their sample backtest charts as QMIE edge (different engine, not frozen OOS)

## How to use the QMIE desk analog

1. Scanner still fires A/A+ on closed bars.
2. `GET /agents/desk` walks the five nodes and returns `decisions` per symbol.
3. Click the trade yourself. Journal the fill.
4. Do not treat `suggest_long` as an order.
