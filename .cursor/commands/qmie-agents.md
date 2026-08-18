# QMIE multi-agent briefing

Run when the user asks for a desk briefing, Smart Checklist, radar breadth,
or "what would the agents say" on current alerts.

1. Call `GET /agents/briefing` (or `cd python && python -m improve.agents`).
2. Report radar bias, A/A+ counts, checklist mix (GO/WATCH/SKIP), and the
   unapplied review knob. Do not write `.env`.
3. For one symbol: `GET /agents/checklist/{id}`.
4. Never treat GO as an order. Never retune `W_*` from MCP or TrendSpider.

Specialists: scanner · radar · book · checklist · review
(isolated via `asyncio.gather(..., return_exceptions=True)`).
