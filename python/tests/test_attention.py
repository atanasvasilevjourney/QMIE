"""Altcoin attention selector — mocked exchange client."""
from __future__ import annotations

import pandas as pd
import pytest

from scanner.alt_selector import AttentionConfig, build_attention_snapshot
from scanner.exchange_clients import ExchangeClient


class _FakeClient(ExchangeClient):
    name = "fake"

    async def fetch_klines(self, symbol, timeframe, limit=300):
        n = min(limit, 40)
        idx = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
        vol = [100.0] * (n - 1) + [8000.0]
        return pd.DataFrame({
            "open": [1.0] * n, "high": [1.01] * n, "low": [0.99] * n,
            "close": [1.0] * n, "volume": vol,
        }, index=idx)

    async def fetch_top_volume_symbols(self, *, top_n, min_quote_volume):
        return ["AAAUSDT"]

    async def fetch_premium_index(self, symbol):
        return {"lastFundingRate": -0.0002}

    async def fetch_market_tickers(self):
        return [
            {
                "symbol": "AAAUSDT",
                "last": 1.0,
                "price_change_pct_24h": 6.0,
                "quote_volume_24h": 50_000_000,
                "funding_rate": -0.0002,
                "open_interest": 1e6,
                "open_interest_usd": 10_000_000,
            },
            {
                "symbol": "BBBUSDT",
                "last": 2.0,
                "price_change_pct_24h": 1.0,
                "quote_volume_24h": 100_000,
                "funding_rate": 0.0001,
                "open_interest_usd": None,
            },
        ]

    async def fetch_liquidation_orders(self, symbol, *, limit=20):
        return [{"notional_usd": 300_000, "side": "SELL"}]

    async def fetch_agg_trades(self, symbol, *, limit=100):
        return [{"notional_usd": 150_000}]

    async def close(self):
        pass


class TestAttentionSnapshot:
    async def test_builds_ranked_rows(self):
        client = _FakeClient()
        cfg = AttentionConfig(top_n=5, deep_scan_n=2, min_quote_volume=1_000_000)
        snap, new_oi = await build_attention_snapshot(
            client,
            cfg=cfg,
            prev_oi={"AAAUSDT": 8_000_000},
        )
        assert snap.status == "ready"
        assert snap.count >= 1
        top = snap.rows[0]
        assert top["symbol"] == "AAAUSDT"
        assert top["attention_score"] > 0
        assert "AAAUSDT" in new_oi
