"""Derivatives flow collector — mocked aiohttp payloads."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from scanner.derivatives_flow.collector import binance_24h, safe_call
from scanner.derivatives_flow.collector import _FetchLog


@pytest.mark.asyncio
async def test_binance_24h_parses_ticker():
    log = _FetchLog()
    session = AsyncMock()
    resp = AsyncMock()
    resp.status = 200
    payload = {
        "lastPrice": "60000",
        "highPrice": "61000",
        "lowPrice": "59000",
        "priceChangePercent": "1.5",
        "quoteVolume": "1000000",
    }
    resp.text = AsyncMock(return_value=__import__("json").dumps(payload))
    cm = AsyncMock()
    cm.__aenter__.return_value = resp
    cm.__aexit__.return_value = None
    session.get = MagicMock(return_value=cm)
    row = await binance_24h(session, log, "BTCUSDT")
    assert row["last"] == 60000.0
    assert row["change_pct"] == 1.5
    assert "binance_24h" in log.ok


@pytest.mark.asyncio
async def test_safe_call_returns_error_dict():
    async def boom():
        raise ValueError("nope")

    out = await safe_call(boom())
    assert "error" in out