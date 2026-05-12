"""
QMIE — Exchange Market Data Clients
===================================
Public REST clients for kline / ticker data. **Read-only.** No auth.

Supported:
  * Binance USDT-M Futures   (fapi.binance.com)
  * Bybit V5 Linear Perps    (api.bybit.com)

Both expose the same async interface:
    async fetch_klines(symbol, timeframe, limit) -> pd.DataFrame
    async fetch_top_volume_symbols(top_n, min_quote_volume) -> list[str]
    async close()

DataFrame schema:
    columns: open, high, low, close, volume   (all float64)
    index:   pd.DatetimeIndex (UTC)
    rows:    only CLOSED candles (the live in-progress one is dropped)

The "drop in-progress candle" rule is what makes server signals
match Pine's `barstate.isconfirmed` semantics.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)


# Map our short timeframe codes to each exchange's wire format
_BINANCE_TF = {"1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m",
               "1h":"1h","2h":"2h","4h":"4h","6h":"6h","8h":"8h",
               "12h":"12h","1d":"1d","3d":"3d","1w":"1w"}
_BYBIT_TF   = {"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30",
               "1h":"60","2h":"120","4h":"240","6h":"360","12h":"720",
               "1d":"D","1w":"W"}


# ═══════════════════════════════════════════════════════════════════════
class ExchangeClient(ABC):
    name: str = "abstract"

    @abstractmethod
    async def fetch_klines(self, symbol: str, timeframe: str,
                           limit: int = 300) -> pd.DataFrame: ...

    @abstractmethod
    async def fetch_top_volume_symbols(self, *, top_n: int,
                                       min_quote_volume: float) -> list[str]: ...

    @abstractmethod
    async def close(self) -> None: ...


# ═══════════════════════════════════════════════════════════════════════
class BinanceClient(ExchangeClient):
    name = "binance"
    BASE = "https://fapi.binance.com"

    def __init__(self, *, timeout: float = 10.0):
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def _s(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout))
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_klines(self, symbol: str, timeframe: str,
                           limit: int = 300) -> pd.DataFrame:
        tf = _BINANCE_TF.get(timeframe.lower())
        if tf is None:
            raise ValueError(f"Binance: unsupported timeframe {timeframe}")
        # Strip a trailing .P (TradingView perpetual marker) if present.
        sym = symbol.upper().replace(".P", "")
        url = f"{self.BASE}/fapi/v1/klines"
        params = {"symbol": sym, "interval": tf, "limit": min(limit, 1500)}

        s = await self._s()
        last_err: Exception | None = None
        for attempt in (1, 2):
            try:
                async with s.get(url, params=params) as resp:
                    if resp.status >= 500:
                        # Transient → retry once
                        last_err = RuntimeError(
                            f"Binance klines {sym}/{tf} HTTP {resp.status}")
                        await asyncio.sleep(0.25 * attempt)
                        continue
                    if resp.status >= 400:
                        text = await resp.text()
                        raise RuntimeError(
                            f"Binance klines {sym}/{tf} HTTP {resp.status}: {text[:200]}")
                    data = await resp.json()
                    break
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                last_err = e
                await asyncio.sleep(0.25 * attempt)
                continue
        else:
            raise last_err if last_err else RuntimeError("Binance klines: unknown failure")

        # Schema: [openTime, open, high, low, close, volume, closeTime, ...]
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data, columns=[
            "openTime","open","high","low","close","volume","closeTime",
            "quoteVolume","trades","takerBuyBase","takerBuyQuote","_ignore",
        ])
        df["openTime"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
        df.set_index("openTime", inplace=True)
        for c in ("open","high","low","close","volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[["open","high","low","close","volume"]].dropna()

        # Drop the in-progress candle. Binance returns the live one as the
        # last row when its closeTime is in the future.
        if len(df) > 0:
            df = df.iloc[:-1]
        return df

    async def fetch_top_volume_symbols(self, *, top_n: int,
                                       min_quote_volume: float) -> list[str]:
        if top_n <= 0:
            return []
        url = f"{self.BASE}/fapi/v1/ticker/24hr"
        s = await self._s()
        async with s.get(url) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Binance ticker HTTP {resp.status}")
            data = await resp.json()

        # USDT-margined perps only
        rows = []
        for d in data:
            sym = d.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            qv = float(d.get("quoteVolume", 0))
            if qv < min_quote_volume:
                continue
            rows.append((sym, qv))
        rows.sort(key=lambda r: -r[1])
        return [r[0] for r in rows[:top_n]]


# ═══════════════════════════════════════════════════════════════════════
class BybitClient(ExchangeClient):
    name = "bybit"
    BASE = "https://api.bybit.com"

    def __init__(self, *, timeout: float = 10.0):
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def _s(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout))
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_klines(self, symbol: str, timeframe: str,
                           limit: int = 300) -> pd.DataFrame:
        tf = _BYBIT_TF.get(timeframe.lower())
        if tf is None:
            raise ValueError(f"Bybit: unsupported timeframe {timeframe}")
        sym = symbol.upper().replace(".P", "")
        url = f"{self.BASE}/v5/market/kline"
        params = {"category": "linear", "symbol": sym,
                  "interval": tf, "limit": min(limit, 1000)}

        s = await self._s()
        async with s.get(url, params=params) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(f"Bybit klines {sym}/{tf} HTTP {resp.status}: {text[:200]}")
            payload = await resp.json()

        if payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit error {payload.get('retCode')}: {payload.get('retMsg')}")

        # list comes back NEWEST-first; columns: [start, open, high, low, close, volume, turnover]
        rows = payload.get("result", {}).get("list", [])
        if not rows:
            return pd.DataFrame()
        rows = list(reversed(rows))
        df = pd.DataFrame(rows, columns=["start","open","high","low","close","volume","turnover"])
        df["start"] = pd.to_datetime(pd.to_numeric(df["start"]), unit="ms", utc=True)
        df.set_index("start", inplace=True)
        for c in ("open","high","low","close","volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[["open","high","low","close","volume"]].dropna()
        if len(df) > 0:
            df = df.iloc[:-1]
        return df

    async def fetch_top_volume_symbols(self, *, top_n: int,
                                       min_quote_volume: float) -> list[str]:
        if top_n <= 0:
            return []
        url = f"{self.BASE}/v5/market/tickers"
        params = {"category": "linear"}
        s = await self._s()
        async with s.get(url, params=params) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Bybit tickers HTTP {resp.status}")
            payload = await resp.json()
        if payload.get("retCode") != 0:
            return []
        rows = []
        for d in payload.get("result", {}).get("list", []):
            sym = d.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            qv = float(d.get("turnover24h", 0))
            if qv < min_quote_volume:
                continue
            rows.append((sym, qv))
        rows.sort(key=lambda r: -r[1])
        return [r[0] for r in rows[:top_n]]


# ═══════════════════════════════════════════════════════════════════════
def get_client(source: str, *, timeout: float = 10.0) -> ExchangeClient:
    s = source.lower().strip()
    if s == "binance":
        return BinanceClient(timeout=timeout)
    if s == "bybit":
        return BybitClient(timeout=timeout)
    raise ValueError(f"Unknown data source: {source}")
