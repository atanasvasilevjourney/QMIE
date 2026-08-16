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
(a single knob). It is **not** Hermes, Signum, HyperLiquid, Railway,
or a TradingView MCP.

## When to use

- "review the strategy" / "what should we change next"
- "self-improving trading agent" / Hermes-style learning
- Ranked Asset Allocation / crypto swing book
- Journal stats look off vs goals

## Hard rules

1. **No execution.** No broker adapters, API wallets, private keys, or live orders.
2. **One variable per cycle.** If last week's change is not yet measured, do not propose another.
3. **Do not write `.env`.** Write `strategy/reviews/YYYY-MM-DD.md`. A human applies the knob and updates `strategy/baseline.yaml`.
4. **No shadow MCPs.** Do not `npx` TradingView/Signum/Hermes servers. This repo's TradingView surface is `pine/quant_visualizer.pine` plus `tv_chart_url()` deep links. If an MCP is required later, use a Runlayer-managed server.
5. **Do not retune scoring weights** on the sample used to report hit rate. Frozen OOS write-up (`docs/backtest-baseline.md`) first.

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
