"""
Exchange client parsing tests.

Uses a fake aiohttp.ClientSession to mock HTTP responses. Verifies:
  * Binance and Bybit kline JSON parses correctly
  * The in-progress (unclosed) candle is dropped on both
  * 5xx triggers exactly one retry on Binance
  * 4xx raises immediately
  * Top-volume filtering works
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from scanner.exchange_clients import (
    BinanceClient, BybitClient, OkxClient, _okx_inst, get_client,
)


# ────── Helpers to fake aiohttp responses ───────────────────────────────
class _FakeResp:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def text(self):
        return json.dumps(self._payload)

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _FakeSession:
    """Sequence of responses to return for each .get() call."""
    def __init__(self, responses):
        self._queue = list(responses)
        self.closed = False
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        if not self._queue:
            raise RuntimeError("no more fake responses queued")
        return self._queue.pop(0)

    async def close(self):
        self.closed = True


# ════════════════════════════════════════════════════════════════════════
class TestBinance:
    @pytest.fixture
    def kline_payload(self):
        # 3 candles. Schema = [openTime, o, h, l, c, vol, closeTime, ...]
        return [
            [1704067200000, "100", "105", "99", "104", "10",
             1704070800000, "1040", 5, "5", "520", "0"],
            [1704070800000, "104", "108", "103", "107", "12",
             1704074400000, "1284", 6, "6", "640", "0"],
            [1704074400000, "107", "110", "106", "109", "9",
             1704078000000, "981",  4, "4", "440", "0"],
        ]

    async def test_parse_klines_drops_in_progress(self, kline_payload):
        # 3 candles in payload; fetch_klines drops the last (in-progress)
        c = BinanceClient()
        fake = _FakeSession([_FakeResp(200, kline_payload)])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            df = await c.fetch_klines("BTCUSDT", "1h", limit=10)
        assert len(df) == 2                           # 3 - 1 (in-progress)
        assert df.iloc[-1]["close"] == 107.0          # the second candle
        assert df.index.tz is not None                # UTC tz

    async def test_4xx_raises_immediately(self):
        c = BinanceClient()
        fake = _FakeSession([_FakeResp(400, {"msg": "bad symbol"})])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            with pytest.raises(RuntimeError, match="HTTP 400"):
                await c.fetch_klines("BADSYM", "1h")

    async def test_5xx_retries_once_then_succeeds(self, kline_payload):
        c = BinanceClient()
        fake = _FakeSession([
            _FakeResp(503, {"err": "transient"}),
            _FakeResp(200, kline_payload),
        ])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            df = await c.fetch_klines("BTCUSDT", "1h")
        assert len(df) == 2
        assert len(fake.calls) == 2                   # retry happened

    async def test_5xx_twice_raises(self, kline_payload):
        c = BinanceClient()
        fake = _FakeSession([
            _FakeResp(503, {"err": "x"}),
            _FakeResp(502, {"err": "y"}),
        ])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            with pytest.raises(RuntimeError):
                await c.fetch_klines("BTCUSDT", "1h")

    async def test_unsupported_timeframe_raises(self):
        c = BinanceClient()
        with pytest.raises(ValueError, match="unsupported timeframe"):
            await c.fetch_klines("BTCUSDT", "37s")

    async def test_strips_perp_dot_p_suffix(self, kline_payload):
        c = BinanceClient()
        fake = _FakeSession([_FakeResp(200, kline_payload)])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            await c.fetch_klines("BTCUSDT.P", "1h")
        # Verify the actual URL params used the stripped symbol
        assert fake.calls[0][1]["symbol"] == "BTCUSDT"

    async def test_top_volume_filter(self):
        # Mix of pairs, only USDT survives + min volume filter
        ticker_payload = [
            {"symbol": "BTCUSDT", "quoteVolume": "1000000000"},
            {"symbol": "ETHUSDT", "quoteVolume": "500000000"},
            {"symbol": "DOGEBUSD", "quoteVolume": "999999999"},   # not USDT
            {"symbol": "TRXUSDT", "quoteVolume": "10000"},        # below min
        ]
        c = BinanceClient()
        fake = _FakeSession([_FakeResp(200, ticker_payload)])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            top = await c.fetch_top_volume_symbols(
                top_n=10, min_quote_volume=1_000_000)
        assert top == ["BTCUSDT", "ETHUSDT"]


# ════════════════════════════════════════════════════════════════════════
class TestBybit:
    @pytest.fixture
    def kline_payload(self):
        # Bybit returns NEWEST-first: [start, o, h, l, c, vol, turnover]
        return {
            "retCode": 0,
            "result": {
                "list": [
                    ["1704074400000", "107", "110", "106", "109", "9", "981"],
                    ["1704070800000", "104", "108", "103", "107", "12", "1284"],
                    ["1704067200000", "100", "105", "99",  "104", "10", "1040"],
                ]
            },
        }

    async def test_parse_klines_drops_in_progress(self, kline_payload):
        c = BybitClient()
        fake = _FakeSession([_FakeResp(200, kline_payload)])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            df = await c.fetch_klines("BTCUSDT", "1h", limit=10)
        # 3 in payload, reversed → ascending; drop last → 2 remain
        assert len(df) == 2
        # First (oldest) confirmed bar
        assert df.iloc[0]["close"] == 104.0
        # Second (in-progress dropped)
        assert df.iloc[-1]["close"] == 107.0

    async def test_retcode_nonzero_raises(self):
        c = BybitClient()
        fake = _FakeSession([_FakeResp(200, {"retCode": 10001, "retMsg": "bad"})])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            with pytest.raises(RuntimeError, match="Bybit error"):
                await c.fetch_klines("BTCUSDT", "1h")


# ════════════════════════════════════════════════════════════════════════
class TestGetClient:
    def test_binance_factory(self):
        c = get_client("binance")
        assert isinstance(c, BinanceClient)

    def test_bybit_factory(self):
        c = get_client("bybit")
        assert isinstance(c, BybitClient)

    def test_okx_factory(self):
        c = get_client("okx")
        assert isinstance(c, OkxClient)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown data source"):
            get_client("kraken")

    def test_case_insensitive(self):
        assert isinstance(get_client("BINANCE"), BinanceClient)
        assert isinstance(get_client("Bybit"), BybitClient)
        assert isinstance(get_client("OKX"), OkxClient)


class TestPremiumIndex:
    async def test_binance_returns_funding_rate(self):
        c = BinanceClient()
        payload = {"symbol": "BTCUSDT", "lastFundingRate": "0.0001",
                   "markPrice": "65000"}
        fake = _FakeSession([_FakeResp(200, payload)])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            data = await c.fetch_premium_index("btcusdt.P")
        assert data["lastFundingRate"] == "0.0001"
        assert fake.calls[0][1]["symbol"] == "BTCUSDT"

    async def test_binance_5xx_retries_once_then_succeeds(self):
        c = BinanceClient()
        payload = {"symbol": "ETHUSDT", "lastFundingRate": "-0.0002"}
        fake = _FakeSession([_FakeResp(503, {}), _FakeResp(200, payload)])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            data = await c.fetch_premium_index("ETHUSDT")
        assert data["lastFundingRate"] == "-0.0002"
        assert len(fake.calls) == 2

    async def test_binance_4xx_raises_immediately(self):
        c = BinanceClient()
        fake = _FakeSession([_FakeResp(400, {"msg": "bad symbol"})])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            with pytest.raises(RuntimeError, match="HTTP 400"):
                await c.fetch_premium_index("NOPE")
        assert len(fake.calls) == 1

    async def test_bybit_maps_funding_rate(self):
        c = BybitClient()
        payload = {
            "retCode": 0,
            "result": {"list": [{"symbol": "BTCUSDT", "fundingRate": "0.0003"}]},
        }
        fake = _FakeSession([_FakeResp(200, payload)])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            data = await c.fetch_premium_index("BTCUSDT")
        assert data["lastFundingRate"] == pytest.approx(0.0003)

    async def test_bybit_empty_list_returns_zero_rate(self):
        c = BybitClient()
        payload = {"retCode": 0, "result": {"list": []}}
        fake = _FakeSession([_FakeResp(200, payload)])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            data = await c.fetch_premium_index("BTCUSDT")
        assert data["lastFundingRate"] == 0.0


class TestOkx:
    @pytest.fixture
    def candle_payload(self):
        # Newest-first. confirm 0 = in-progress, 1 = closed.
        return {
            "code": "0",
            "data": [
                ["1704074400000", "107", "110", "106", "109", "9", "9", "981", "0"],
                ["1704070800000", "104", "108", "103", "107", "12", "12", "1284", "1"],
                ["1704067200000", "100", "105", "99", "104", "10", "10", "1040", "1"],
            ],
        }

    async def test_parse_klines_drops_unconfirmed(self, candle_payload):
        c = OkxClient()
        fake = _FakeSession([_FakeResp(200, candle_payload)])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            df = await c.fetch_klines("BTCUSDT.P", "1h", limit=10)
        assert len(df) == 2
        assert df.iloc[-1]["close"] == 107.0
        assert df.index.tz is not None
        assert fake.calls[0][1]["instId"] == "BTC-USDT-SWAP"
        assert fake.calls[0][1]["bar"] == "1H"

    async def test_rebrand_aliases_matic_and_rndr(self, candle_payload):
        c = OkxClient()
        fake = _FakeSession([
            _FakeResp(200, candle_payload),
            _FakeResp(200, candle_payload),
        ])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            await c.fetch_klines("MATICUSDT", "1h", limit=10)
            await c.fetch_klines("RNDRUSDT", "4h", limit=10)
        assert fake.calls[0][1]["instId"] == "POL-USDT-SWAP"
        assert fake.calls[1][1]["instId"] == "RENDER-USDT-SWAP"

    async def test_pol_and_render_native_ids(self, candle_payload):
        c = OkxClient()
        fake = _FakeSession([
            _FakeResp(200, candle_payload),
            _FakeResp(200, candle_payload),
        ])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            await c.fetch_klines("POLUSDT", "1h", limit=10)
            await c.fetch_klines("RENDERUSDT", "1h", limit=10)
        assert fake.calls[0][1]["instId"] == "POL-USDT-SWAP"
        assert fake.calls[1][1]["instId"] == "RENDER-USDT-SWAP"

    def test_1000pepe_not_aliased_to_pepe(self):
        # Different contract scale — never map onto OKX PEPE-USDT-SWAP.
        assert _okx_inst("1000PEPEUSDT") == "1000PEPE-USDT-SWAP"
        assert _okx_inst("PEPEUSDT") == "PEPE-USDT-SWAP"
        assert _okx_inst("FETUSDT") == "FET-USDT-SWAP"

    async def test_4xx_raises(self):
        c = OkxClient()
        fake = _FakeSession([_FakeResp(451, {"msg": "restricted"})])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            with pytest.raises(RuntimeError, match="HTTP 451"):
                await c.fetch_klines("BTCUSDT", "4h")

    async def test_api_code_raises(self):
        c = OkxClient()
        fake = _FakeSession([_FakeResp(200, {"code": "51001", "msg": "bad inst"})])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            with pytest.raises(RuntimeError, match="OKX error"):
                await c.fetch_klines("BTCUSDT", "1h")

    async def test_funding_maps_rate(self):
        c = OkxClient()
        payload = {
            "code": "0",
            "data": [{"instId": "ETH-USDT-SWAP", "fundingRate": "0.00012"}],
        }
        fake = _FakeSession([_FakeResp(200, payload)])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            data = await c.fetch_premium_index("ETHUSDT")
        assert data["lastFundingRate"] == pytest.approx(0.00012)
        assert data["symbol"] == "ETHUSDT"
        assert fake.calls[0][1]["instId"] == "ETH-USDT-SWAP"

    async def test_top_volume_filters_usdt_swap(self):
        c = OkxClient()
        payload = {
            "code": "0",
            "data": [
                {"instId": "BTC-USDT-SWAP", "last": "50000", "volCcy24h": "2000"},
                {"instId": "ETH-USDT-SWAP", "last": "2000", "volCcy24h": "10"},
                {"instId": "BTC-USD-SWAP", "last": "50000", "volCcy24h": "99999"},
            ],
        }
        fake = _FakeSession([_FakeResp(200, payload)])
        with patch.object(c, "_s", AsyncMock(return_value=fake)):
            # BTC quote vol = 2000*50000 = 100_000_000; ETH = 20_000
            syms = await c.fetch_top_volume_symbols(top_n=5, min_quote_volume=1_000_000)
        assert syms == ["BTCUSDT"]
