# QMIE multi-agent briefing

Run when the user asks for a desk briefing, Smart Checklist, radar breadth,
analysis Take, hedge-fund DAG, or "what would the agents say" on current alerts.

1. Call `GET /agents/briefing` (or `cd python && python -m improve.agents`).
2. Report radar bias, A/A+ counts, checklist mix (GO/WATCH/SKIP), analysis
   armed/not, and the unapplied review knob. Do not write `.env`.
3. For the DAG analog of ai-hedge-fund-crypto: `GET /agents/desk`.
   Actions are suggest_long / suggest_short / watch / skip. quantity is 0.
4. For one symbol: `GET /agents/checklist/{id}`.
5. For a levels table + Take: `GET /agents/analysis/{id}` (on-demand).
6. Never treat GO, BULLISH, or suggest_long as an order. Never retune `W_*`.
   Do not import LangGraph, MACD ensembles, or a Binance trading gateway.

Specialists: scanner · radar · book · checklist · review · analysis
DAG: start → data → strategy → risk → portfolio (signal-only).
