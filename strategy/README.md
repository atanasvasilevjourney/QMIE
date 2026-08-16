# Strategy files for the self-improving *review* loop
# ====================================================
#
# QMIE is still an alert scanner. It does not place orders.
# This folder is how the Cursor agent (and `python -m improve.review`)
# scores outcomes against a declared goal — the scientific method,
# one variable at a time.
#
# What this is not
# ----------------
# * Not Hermes / OpenClaw / "oneshot prompt that trades your account"
# * Not Signum, HyperLiquid, Railway, or Claude Routines
# * Not a TradingView MCP. There is no retail TV HTTP API in this repo.
#   Charts = `pine/quant_visualizer.pine` + Discord/Telegram deep links.
# * If you later want a TradingView-shaped MCP, use a Runlayer-managed
#   server. Do not add a shadow `.mcp.json`.
#
# Files
# -----
# goals.yaml      success vs failure (Sharpe, DD, expectancy, win%)
# baseline.yaml   current live knobs (must match `.env` after you apply a change)
# reviews/        dated markdown from `cd python && python -m improve.review`
#
# Ranked asset allocation (crypto swing)
# --------------------------------------
# After each bar-close scan, `scanner/allocator.py` keeps top N longs and
# top N shorts (default 3+3), 50/50 books, cluster_max=1 so you do not
# double ETH-beta. Discord shows `#rank · weight% · cluster`. Suggested
# size is a 100-point risk budget, not an order.
#
# Loop
# ----
# 1. Scanner fires ranked A/A+ alerts 24/7 (Docker Compose, not Railway).
# 2. You take the trade (or skip) and `POST /journal`.
# 3. Weekly: run the review CLI or ask the Cursor agent to `/qmie-review`.
# 4. Apply at most one `.env` change. Update `baseline.yaml` to match.
# 5. That value is the new baseline only if the next cycle moves toward
#    the goal. Revert if it moves toward failure.
