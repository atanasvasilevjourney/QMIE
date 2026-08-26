"""
QMIE — Trading guide (operator module)
======================================
Static ruled copy for the desk GUIDE tab. Not a score. Not a broker.
"""
from __future__ import annotations

from typing import Any


def trading_guide() -> dict[str, Any]:
    return {
        "title": "QMIE Trading Guide",
        "places_orders": False,
        "version": "1.0",
        "headline": "Signal-only desk. Paper fills every alert. You click live size yourself.",
        "sections": [
            {
                "id": "what",
                "title": "What this is",
                "body": (
                    "QMIE scans USDT perps on closed 1h/4h bars (TEMA 9/90/199) and "
                    "a daily trend radar. It never sends an order. The desk logs paper "
                    "fills so you can measure the alert stream before (or instead of) "
                    "clicking a live trade."
                ),
            },
            {
                "id": "tema",
                "title": "TEMA scanner (graded)",
                "body": (
                    "Take A / A+ only. Frozen OOS was strongest on 4h. Confirm side and "
                    "grade on quant_visualizer.pine. A higher-low (e.g. BTC 67–68k) is "
                    "an entry only if that closed bar actually graded A/A+ — the table "
                    "does not reconstruct chart patterns."
                ),
                "rules": [
                    "Grade A or A+ on a closed bar",
                    "Prefer 4h when sizing live",
                    "Use the printed SL / TP; do not invent levels",
                    "If price already ran far from signal_price, skip the chase",
                ],
            },
            {
                "id": "breakout",
                "title": "Daily breakout (unranked)",
                "body": (
                    "1D GREY→GREEN or coil-UP is a long trend-start, not an A/A+ grade. "
                    "Checklist is usually WATCH. Confirm on the Daily visualizer. Paper "
                    "still fills it so you can see how those alerts behave."
                ),
                "rules": [
                    "Not the 4h A/A+ OOS path",
                    "SL is coil_low when present",
                    "Late-stage GREEN is not a fresh start",
                ],
            },
            {
                "id": "screens",
                "title": "Daily screens (four views)",
                "body": (
                    "SCREENS tab is the combo list: unique symbols from 4h A/A+, "
                    "daily breakout, radar coils, and the ranked book. Space next, "
                    "Shift+Space flags a focus list (not a fill). Do not add "
                    "earnings/IPO filters."
                ),
                "rules": [
                    "Leaders: 4h TEMA A/A+ (frozen OOS edge)",
                    "Themes: 1D radar G/Y/R, fresh flips, tight coils",
                    "Liquid book: ranked slots (quantity still 0)",
                    "Specialist: daily GREY→GREEN / coil-UP — not an A/A+ grade",
                    "SCREENS tab: combo unique(symbol) list",
                    "Space next · Shift+Space flag · Enter opens CHARTS",
                ],
            },
            {
                "id": "paper",
                "title": "Paper automation",
                "body": (
                    "Every stored ENTRY gets one paper fill at signal_price. Size is "
                    "PAPER_NOTIONAL_USDT / price (default $1000). Notes say "
                    "'paper auto-fill'. This is not a broker and quantity on the desk "
                    "DAG stays 0."
                ),
                "rules": [
                    "One paper fill per alert (independent, like the backtest)",
                    "Manual journal fills on the same signal block a second paper row",
                    "PAPER SYNC backfills old alerts and marks exits",
                ],
            },
            {
                "id": "exit",
                "title": "Exit signal + PnL",
                "body": (
                    "On later closed bars, paper closes at SL or TP (same-bar both → SL). "
                    "The desk writes a QMIE-Paper EXIT row: exit price, reason, cash PnL, "
                    "and R if a stop existed. OPEN rows stay open until SL/TP (or you "
                    "close them in JOURNAL)."
                ),
                "rules": [
                    "PnL = size × (exit − fill) for BUY, inverted for SELL",
                    "R uses the signal stop; missing SL still gets cash PnL",
                    "EXIT table is paper closes — not a live flatten",
                ],
            },
            {
                "id": "charts",
                "title": "Charts (desk)",
                "body": (
                    "The CHARTS tab draws an SVG equity curve from closed fills "
                    "(paper + manual) and a closed-bar price chart with entry/exit "
                    "marks and SL/TP lines. It is not TradingView and not an order "
                    "ticket. Klines load only while the tab is open."
                ),
                "rules": [
                    "SVG only — no extra chart library",
                    "Closed candles from the scanner data source",
                    "Paper PnL is not live edge until 30 closed manual fills",
                ],
            },
            {
                "id": "live",
                "title": "If you take it live",
                "body": (
                    "Click the trade yourself on your venue. Log the real fill in JOURNAL "
                    "(not the paper row) so live edge can be compared to OOS after 30 "
                    "closed fills. Do not retune W_* from one winner."
                ),
            },
        ],
    }
