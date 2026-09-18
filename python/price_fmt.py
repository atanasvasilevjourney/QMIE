"""Shared crypto price formatting (Discord, Telegram, chart PNG)."""
from __future__ import annotations

from typing import Optional

from models import AssetClass


def crypto_decimals(price: float) -> int:
    a = abs(price)
    if a >= 100:
        return 2
    if a >= 1:
        return 4
    if a >= 0.0001:
        return 6
    return 8


def price_precision(asset_class: AssetClass, price: float) -> int:
    if asset_class is AssetClass.FOREX:
        return 3 if price > 10 else 5
    if asset_class in (AssetClass.METAL, AssetClass.FUTURE, AssetClass.EQUITY):
        return 2
    return crypto_decimals(price)


def fmt_price(price: Optional[float], asset_class: AssetClass = AssetClass.CRYPTO) -> str:
    if price is None:
        return "—"
    p = price_precision(asset_class, float(price))
    return f"{float(price):,.{p}f}"
