---
name: qmie-improve
description: >-
  Weekly scientific-method review of the QMIE crypto swing scanner.
  Use when the user asks to improve the strategy, run a Hermes-style
  self-learning loop, ranked asset allocation review, journal post-mortem,
  or "learn from mistakes" on QMIE. Never places orders.
---

# QMIE self-improving review

QMIE is an **alert-only** USDT-perp scanner. The self-improve loop is:
prompt → ranked swing allocation → journaled outcome → one new prompt
(a single knob). It is **not** Hermes, Signum, HyperLiquid, or Railway.

The optional TradingView MCP (`.cursor/mcp.json`) is a **shadow stdio**
server. Live quote + ruled confirm/skip on A/A+ (`/qmie-setup`) is
allowed. It is not the scanner and must not retune weights. QMIE
backtests stay `python -m backtest.run`. See `docs/tradingview-mcp.md`.

## When to use

- "review the strategy" / "what should we change next"
- "self-improving trading agent" / Hermes-style learning
- Ranked Asset Allocation / crypto swing book
- Journal stats look off vs goals

## Hard rules

1. **No execution.** No broker adapters, API wallets, private keys, or live orders.
2. **One variable per cycle.** If last week's change is not yet measured, do not propose another.
3. **Do not write `.env`.** Write `strategy/reviews/YYYY-MM-DD.md`. A human applies the knob and updates `strategy/baseline.yaml`.
4. **No extra shadow MCPs.** Do not `npx` Signum/Hermes servers. The
   one allowed project MCP is `tradingview` in `.cursor/mcp.json`
   (atilaahmettaner/tradingview-mcp via `uvx`). Prefer Runlayer if a
   managed TradingView server appears. Never mix MCP TA into QMIE
   `W_*` or `compute_signal`.
5. **Do not retune scoring weights** on the sample used to report hit rate. Frozen OOS write-up (`docs/backtest-baseline.md`) first. KovaView / KAMA-DF / TQQQ notebooks are overlay maps (`docs/kovaview-equity-map.md`), not a live-engine upgrade and not a reason to skip the outstanding `SCAN_TIMEFRAMES=4h` knob. Do **not** re-apply `too_late` / BTC-RED `buys_allowed` / cooldown as checklist SKIP — they cut winners on the 4h A/A+ slice (`docs/kovaview-overlay-backtest.md`). Do **not** add `1d` to `SCAN_TIMEFRAMES` — daily A/A+ OOS loses.
6. **OpenAI Take is not a score.** `GET /agents/analysis/{id}` may color the alert; it must not change `W_*`, grades, or place orders. Inventing gamma / dark-pool / 0DTE tape is out of scope.

## Workflow

1. Read `strategy/README.md`, `strategy/goals.yaml`, `strategy/baseline.yaml`.
2. From `python/`: `python -m improve.review` (optional `--db path/to/qmie.db`).
3. Open the new file under `strategy/reviews/`.
4. If verdict is `insufficient_sample`, stop. Tell the operator to journal fills (`POST /journal`) until `review.min_closed_fills`.
5. If a `proposed_knob` is set, explain: current value, proposed value, why this variable, how we will know it worked (toward goal vs toward failure).
6. Do not apply the change unless the user explicitly asks to edit `.env` **and** `baseline.yaml` together.

## Accuracy (data)

Trust closed-bar scanner data (Binance/Bybit public REST, 5s grace) and the manual journal. Do not invent fills. Do not scrape news into the score. Conclusions in the review must cite journal numbers or a backtest table.

## Reliability (24/7)

The scanner already runs in Docker Compose (`docs/deployment.md`). Do not add Railway/Hermes hosting.

## Goal

Success and failure are numeric in `strategy/goals.yaml` (Sharpe, max DD, expectancy R, win%). Direction toward the goal is good; toward failure is a revert.
