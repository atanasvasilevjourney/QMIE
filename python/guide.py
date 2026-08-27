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
        "version": "1.4",
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
                    "Take A / A+ only, both BUY and SELL. Frozen OOS was strongest on 4h "
                    "(SELL actually outnumbered BUY on that slice). Confirm side and "
                    "grade on quant_visualizer.pine. A higher-low (e.g. BTC 67–68k) is "
                    "an entry only if that closed bar actually graded A/A+ — the table "
                    "does not reconstruct chart patterns."
                ),
                "rules": [
                    "Grade A or A+ on a closed bar",
                    "Prefer 4h when sizing live",
                    "Use the printed SL / TP; do not invent levels",
                    "If price already ran far from signal_price, skip the chase",
                    "OPS TEMA BUY module is A/A+ BUY only — the measured swing add",
                ],
            },
            {
                "id": "expansion",
                "title": "Daily expansion (coil-UP)",
                "body": (
                    "New unranked 1D strategy: a close outside an armed GREY Donchian "
                    "coil (coil-UP long / coil-DOWN short). Strategy id "
                    "QMIE-DailyExpansion. Stop is the prior box, not today's wick. "
                    "Not an A/A+ grade and not the frozen 4h OOS. Clip 1 of the "
                    "manual two-step book — wait for a 4h TEMA BUY to add."
                ),
                "rules": [
                    "Radar bucket Expansions = today's coil-UP",
                    "OPS Daily expansion table = dispatched QMIE-DailyExpansion",
                    "Long SL = prior coil_low; short SL = prior coil_high",
                    "No TEMA TP on this ticket",
                    "Follow-through days of the same expansion do not re-fire",
                ],
            },
            {
                "id": "tema_buy",
                "title": "TEMA BUY module (graded add)",
                "body": (
                    "Separate OPS table for A/A+ BUY only. Prefer 4h — that is the "
                    "frozen swing edge (1.5×ATR stop / 2.5×ATR take). A badge "
                    "'after expansion' means the same symbol already has a 1D "
                    "coil-UP. That is clip 2. SELL A/A+ stays on the TEMA scanner table."
                ),
                "rules": [
                    "A or A+ BUY on a closed bar",
                    "Prefer 4h printed SL / TP",
                    "Do not hold for daily GREEN→GREY if TP already printed",
                    "Not a broker; quantity stays 0",
                ],
            },
            {
                "id": "breakout",
                "title": "Daily color-flip (unranked)",
                "body": (
                    "Day-1 GREY→GREEN/RED stays QMIE-DailyBreakout. It is not a coil "
                    "expansion and not an A/A+ grade. Color-flips have no stop — no R "
                    "until you journal a stop. Confirm on the Daily visualizer."
                ),
                "rules": [
                    "Not the 4h A/A+ OOS path",
                    "Color-flip only — coil-UP is Daily expansion",
                    "Color-flip rows show no R until a stop exists",
                    "Late-stage GREEN or RED is not a fresh start",
                ],
            },
            {
                "id": "screens",
                "title": "Daily screens (combo views)",
                "body": (
                    "SCREENS tab is the combo list: unique symbols from 4h A/A+, "
                    "daily expansion (coil-UP), color-flip, radar coils, and the ranked book. Space next, "
                    "Shift+Space flags a focus list (not a fill). Do not add "
                    "earnings/IPO filters."
                ),
                "rules": [
                    "Leaders: 4h TEMA A/A+ (frozen OOS edge)",
                    "Themes: 1D radar G/Y/R, fresh flips, tight coils",
                    "Liquid book: ranked slots (quantity still 0)",
                    "Specialist: 1D coil-UP expansion + GREY→GREEN/RED color-flip",
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
                "id": "kovaview",
                "title": "KovaView overlays (not a new engine)",
                "body": (
                    "KovaView is an EOD equity swing stack (GREEN/GREY/RED, SPY regime, "
                    "ATR×2.5, SMA20 trail). Do not port it into TEMA 9/90/199. too_late, "
                    "BTC buys_allowed, and two-loss cooldown were measured on 4h A/A+ and "
                    "taken off: they skip winners, not an expectancy engine. "
                    "SCAN_TIMEFRAMES=4h is still the outstanding live knob. "
                    "Map: docs/kovaview-equity-map.md."
                ),
                "rules": [
                    "too_late / BTC-RED / cooldown are not checklist skips — they cut winners",
                    "Do not add KAMA / EWMAC / z_52 as score votes",
                    "Printed stop stays 1.5×ATR; 1.25% equity is operator sizing",
                    "One outstanding knob: 4h-only, then ADX≥20 — not both",
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
