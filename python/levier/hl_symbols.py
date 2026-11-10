"""Hyperliquid perp symbols (display tag only — not a data feed)."""
from __future__ import annotations

# USDT-style names QMIE uses that also list on HL (curated subset; extend in config later).
HL_USDT_SYMBOLS: frozenset[str] = frozenset(
    {
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "XRPUSDT",
        "DOGEUSDT",
        "ADAUSDT",
        "AVAXUSDT",
        "LINKUSDT",
        "DOTUSDT",
        "LTCUSDT",
        "TRXUSDT",
        "ATOMUSDT",
        "NEARUSDT",
        "APTUSDT",
        "ARBUSDT",
        "OPUSDT",
        "SUIUSDT",
        "INJUSDT",
        "FILUSDT",
        "TIAUSDT",
        "SEIUSDT",
        "WLDUSDT",
        "UNIUSDT",
        "AAVEUSDT",
        "MKRUSDT",
        "CRVUSDT",
        "LDOUSDT",
        "RUNEUSDT",
        "IMXUSDT",
        "SANDUSDT",
        "MANAUSDT",
        "APEUSDT",
        "GALAUSDT",
        "RENDERUSDT",
        "FETUSDT",
        "PEPEUSDT",
        "BONKUSDT",
        "WIFUSDT",
        "ORDIUSDT",
        "KASUSDT",
    }
)


def venue_tag(symbol: str) -> str:
    s = symbol.upper().replace(".P", "")
    return "HL" if s in HL_USDT_SYMBOLS else ""
