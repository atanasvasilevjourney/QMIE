# AI-ruled setup overlay

Fixed gates for `/qmie-setup` / `python -m improve.setup_review`.
These do **not** change QMIE weights. News/Reddit never gate.

| id | Pass | Fail |
|---|---|---|
| `qmie_alert` | BUY/SELL and grade A or A+ | B/C/REJECT/NEUTRAL |
| `mcp_recommendation` | MCP BUY/STRONG BUY vs QMIE BUY (same for SELL) | HOLD or opposite side |
| `mcp_htf` | MCP HTF same side | mixed/neutral/opposite |
| `mcp_rsi` | RSI not ≥75 on BUY, not ≤25 on SELL | extreme against the trade |
| `mcp_sentiment` | always recorded | never a gate |

Missing MCP fields → `INCOMPLETE`. Disagreement → `CONFLICT` (skip).
All required pass → `CONFIRM` then still open `quant_visualizer.pine`.
