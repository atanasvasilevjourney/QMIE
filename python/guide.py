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
        "version": "1.5",
        "headline": "Signal-only desk. Radar is the spot book. TEMA is the leveraged add. You click size yourself.",
        "sections": [
            {
                "id": "what",
                "title": "What this is",
                "body": (
                    "QMIE scans USDT-perp 1h/4h bars for TEMA (leverage book) and "
                    "a daily Trend Radar for the spot book. It never sends an order. "
                    "Radar klines are the same closed daily candles; you take expansions "
                    "on spot and TEMA on a leveraged perp."
                ),
            },
            {
                "id": "tema",
                "title": "TEMA scanner (graded)",
                "body": (
                    "Take A / A+ only, both BUY and SELL — this is the leveraged book "
                    "on USDT-perp. Frozen OOS was strongest on 4h. Confirm side and "
                    "grade on quant_visualizer.pine. QMIE does not send leverage to a "
                    "venue; you set size on your perp."
                ),
                "rules": [
                    "Grade A or A+ on a closed bar",
                    "Prefer 4h when sizing the leveraged add",
                    "Use the printed SL / TP; do not invent levels",
                    "If price already ran far from signal_price, skip the chase",
                    "OPS TEMA BUY is A/A+ BUY only — leverage, not spot",
                ],
            },
            {
                "id": "expansion",
                "title": "Daily expansion (spot coil-UP)",
                "body": (
                    "Spot book. Unranked 1D close outside an armed GREY Donchian "
                    "coil (coil-UP long / coil-DOWN short). Strategy id "
                    "QMIE-DailyExpansion. Stop is the prior box, not today's wick. "
                    "No leverage and no TEMA TP. Clip 1 — wait for a 4h TEMA BUY "
                    "if you add a leveraged clip."
                ),
                "rules": [
                    "Radar Expansions = spot 1D coil-UP",
                    "OPS Daily expansion table = dispatched QMIE-DailyExpansion",
                    "Long SL = prior coil_low; short SL = prior coil_high",
                    "Take it on spot — not a perp / not TEMA ATR",
                    "Follow-through days of the same expansion do not re-fire",
                ],
            },
            {
                "id": "tema_buy",
                "title": "TEMA BUY module (leveraged add)",
                "body": (
                    "Leverage book. Separate OPS table for A/A+ BUY only on USDT-perp. "
                    "Prefer 4h — frozen swing edge (1.5×ATR stop / 2.5×ATR take). A badge "
                    "'after expansion' means the same symbol already has a spot 1D "
                    "coil-UP. That is clip 2. SELL A/A+ stays on the TEMA scanner table. "
                    "QMIE never sets leverage on a venue."
                ),
                "rules": [
                    "A or A+ BUY on a closed bar",
                    "Prefer 4h printed SL / TP on the perp",
                    "Do not hold for daily GREEN→GREY if TP already printed",
                    "Not a broker; quantity stays 0",
                ],
            },
            {
                "id": "breakout",
                "title": "Daily color-flip (unranked)",
                "body": (
                    "Day-1 GREY→GREEN/RED stays QMIE-DailyBreakout on the spot radar. "
                    "It is not a coil expansion, not leverage, and not an A/A+ grade. "
                    "Color-flips have no stop — no R until you journal a stop."
                ),
                "rules": [
                    "Not the 4h A/A+ OOS path",
                    "Color-flip is spot context — coil-UP is Daily expansion",
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
                    "Leaders: 4h TEMA A/A+ (leverage book)",
                    "Themes: 1D radar G/Y/R, fresh flips, tight coils (spot)",
                    "Liquid book: ranked slots (quantity still 0)",
                    "Specialist: spot 1D coil-UP expansion + GREY→GREEN/RED color-flip",
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
                    "Click the trade yourself. Radar expansions = spot. TEMA = leverage "
                    "on your perp — you set the size. Log the real fill in JOURNAL "
                    "(not the paper row). Do not retune W_* from one winner."
                ),
            },
        ],
    }
