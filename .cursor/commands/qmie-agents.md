# QMIE multi-agent briefing

Run when the user asks for a desk briefing, Smart Checklist, radar breadth,
analysis Take, or "what would the agents say" on current alerts.

1. Call `GET /agents/briefing` (or `cd python && python -m improve.agents`).
2. Report radar bias, A/A+ counts, checklist mix (GO/WATCH/SKIP), analysis
   armed/not, and the unapplied review knob. Do not write `.env`.
3. For one symbol: `GET /agents/checklist/{id}`.
4. For a levels table + Take: `GET /agents/analysis/{id}` (on-demand).
   Prices are scanner ATR SL/TP. Empty `OPENAI_API_KEY` uses the template.
5. Never treat GO or BULLISH as an order. Never retune `W_*` from MCP,
   TrendSpider, or the LLM.

Specialists: scanner · radar · book · checklist · review · analysis
(isolated via `asyncio.gather(..., return_exceptions=True)`).
