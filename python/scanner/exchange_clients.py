"""
QMIE — Exchange Market Data Clients
===================================
Public REST clients for kline / ticker data. **Read-only.** No auth.

Supported:
  * Binance USDT-M Futures   (fapi.binance.com)
  * Bybit V5 Linear Perps    (api.bybit.com)
  * OKX USDT-margined swaps  (www.okx.com) — geo-block fallback, not Pine venue

All three expose the same async interface:
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
_OKX_TF     = {"1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m",
               "1h":"1H","2h":"2H","4h":"4H","6h":"6H","12h":"12H",
               "1d":"1D","1w":"1W"}

# Binance-era tickers → current OKX SWAP inst. Do not map 1000PEPE→PEPE
# (different contract scale). FET has no OKX SWAP in the live book.
_OKX_INST_ALIAS = {
    "MATICUSDT": "POL-USDT-SWAP",
    "RNDRUSDT": "RENDER-USDT-SWAP",
}


def _okx_inst(symbol: str) -> str:
    """BTCUSDT / BTCUSDT.P → BTC-USDT-SWAP (with rebrand aliases)."""
    raw = symbol.upper().replace(".P", "").replace("-", "")
    if raw in _OKX_INST_ALIAS:
        return _OKX_INST_ALIAS[raw]
    if raw.endswith("USDT"):
        return f"{raw[:-4]}-USDT-SWAP"
    return f"{raw}-USDT-SWAP"


def _okx_to_qmie(inst_id: str) -> str:
    """BTC-USDT-SWAP → BTCUSDT."""
    s = inst_id.upper()
    if s.endswith("-USDT-SWAP"):
        return s[: -len("-USDT-SWAP")] + "USDT"
    return s.replace("-", "")


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
    async def fetch_premium_index(self, symbol: str) -> dict:
        """Return at least ``lastFundingRate`` (float, e.g. 0.0001 = 0.01%/8h)."""

    @abstractmethod
    async def fetch_market_tickers(self) -> list[dict[str, Any]]:
        """All USDT linear perps: normalized ticker rows for microstructure scans.

        Each row should include when available:
          symbol, last, price_change_pct_24h, quote_volume_24h,
          funding_rate, open_interest, open_interest_usd
        """

    async def fetch_liquidation_orders(
        self, symbol: str, *, limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Recent liquidation prints for one symbol (empty if unsupported)."""
        del symbol, limit
        return []

    async def fetch_agg_trades(
        self, symbol: str, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Recent aggregated trades for whale-print detection."""
        del symbol, limit
        return []

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

    async def fetch_premium_index(self, symbol: str) -> dict:
        """Fetch current mark price + funding rate via /fapi/v1/premiumIndex."""
        url = f"{self.BASE}/fapi/v1/premiumIndex"
        params = {"symbol": symbol.upper().replace(".P", "")}
        sess = await self._s()
        last_err: Exception | None = None
        for attempt in (1, 2):
            try:
                async with sess.get(url, params=params) as r:
                    if r.status >= 500:
                        last_err = RuntimeError(
                            f"Binance premiumIndex HTTP {r.status}")
                        await asyncio.sleep(0.25 * attempt)
                        continue
                    if r.status >= 400:
                        text = await r.text()
                        raise RuntimeError(
                            f"Binance premiumIndex HTTP {r.status}: {text[:200]}")
                    data = await r.json()
                    return data if isinstance(data, dict) else {}
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                last_err = e
                await asyncio.sleep(0.25 * attempt)
                continue
        raise last_err if last_err else RuntimeError(
            "Binance premiumIndex: unknown failure")

    async def fetch_market_tickers(self) -> list[dict[str, Any]]:
        """Merge 24h ticker stats with all-symbol premiumIndex funding."""
        sess = await self._s()
        async with sess.get(f"{self.BASE}/fapi/v1/ticker/24hr") as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Binance ticker HTTP {resp.status}")
            tickers = await resp.json()
        funding_map: dict[str, float] = {}
        async with sess.get(f"{self.BASE}/fapi/v1/premiumIndex") as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Binance premiumIndex HTTP {resp.status}")
            prem = await resp.json()
        if isinstance(prem, list):
            for row in prem:
                sym = str(row.get("symbol") or "")
                if sym.endswith("USDT"):
                    try:
                        funding_map[sym] = float(row.get("lastFundingRate") or 0)
                    except (TypeError, ValueError):
                        funding_map[sym] = 0.0
        out: list[dict[str, Any]] = []
        if not isinstance(tickers, list):
            return out
        for d in tickers:
            sym = str(d.get("symbol") or "")
            if not sym.endswith("USDT"):
                continue
            try:
                last = float(d.get("lastPrice") or 0)
                qv = float(d.get("quoteVolume") or 0)
                chg = float(d.get("priceChangePercent") or 0)
            except (TypeError, ValueError):
                continue
            out.append({
                "symbol": sym,
                "last": last,
                "price_change_pct_24h": chg,
                "quote_volume_24h": qv,
                "funding_rate": funding_map.get(sym, 0.0),
                "open_interest": None,
                "open_interest_usd": None,
            })
        return out

    async def fetch_liquidation_orders(
        self, symbol: str, *, limit: int = 20,
    ) -> list[dict[str, Any]]:
        sym = symbol.upper().replace(".P", "")
        url = f"{self.BASE}/fapi/v1/allForceOrders"
        params = {"symbol": sym, "limit": min(limit, 100)}
        sess = await self._s()
        async with sess.get(url, params=params) as resp:
            if resp.status >= 400:
                return []
            data = await resp.json()
        if not isinstance(data, list):
            return []
        out: list[dict[str, Any]] = []
        for row in data:
            try:
                px = float(row.get("price") or 0)
                qty = float(row.get("origQty") or row.get("executedQty") or 0)
                side = str(row.get("side") or "")
            except (TypeError, ValueError):
                continue
            out.append({
                "symbol": sym,
                "side": side,
                "price": px,
                "qty": qty,
                "notional_usd": px * qty,
                "time_ms": int(row.get("time") or 0),
            })
        return out

    async def fetch_agg_trades(
        self, symbol: str, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        sym = symbol.upper().replace(".P", "")
        url = f"{self.BASE}/fapi/v1/aggTrades"
        params = {"symbol": sym, "limit": min(limit, 1000)}
        sess = await self._s()
        async with sess.get(url, params=params) as resp:
            if resp.status >= 400:
                return []
            data = await resp.json()
        if not isinstance(data, list):
            return []
        out: list[dict[str, Any]] = []
        for row in data:
            try:
                px = float(row.get("p") or 0)
                qty = float(row.get("q") or 0)
            except (TypeError, ValueError):
                continue
            out.append({
                "price": px,
                "qty": qty,
                "notional_usd": px * qty,
                "time_ms": int(row.get("T") or 0),
                "buyer_maker": bool(row.get("m")),
            })
        return out


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

    async def fetch_premium_index(self, symbol: str) -> dict:
        """Map Bybit linear ticker ``fundingRate`` onto Binance-shaped keys."""
        sym = symbol.upper().replace(".P", "")
        url = f"{self.BASE}/v5/market/tickers"
        params = {"category": "linear", "symbol": sym}
        s = await self._s()
        async with s.get(url, params=params) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(
                    f"Bybit premiumIndex {sym} HTTP {resp.status}: {text[:200]}")
            payload = await resp.json()
        if payload.get("retCode") != 0:
            raise RuntimeError(
                f"Bybit error {payload.get('retCode')}: {payload.get('retMsg')}")
        rows = payload.get("result", {}).get("list", []) or []
        if not rows:
            return {"lastFundingRate": 0.0}
        row = rows[0]
        try:
            rate = float(row.get("fundingRate") or 0)
        except (TypeError, ValueError):
            rate = 0.0
        return {"lastFundingRate": rate, "symbol": row.get("symbol", sym)}

    async def fetch_market_tickers(self) -> list[dict[str, Any]]:
        url = f"{self.BASE}/v5/market/tickers"
        params = {"category": "linear"}
        s = await self._s()
        async with s.get(url, params=params) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Bybit tickers HTTP {resp.status}")
            payload = await resp.json()
        if payload.get("retCode") != 0:
            return []
        out: list[dict[str, Any]] = []
        for d in payload.get("result", {}).get("list", []) or []:
            sym = str(d.get("symbol") or "")
            if not sym.endswith("USDT"):
                continue
            try:
                last = float(d.get("lastPrice") or 0)
                qv = float(d.get("turnover24h") or 0)
                chg = float(d.get("price24hPcnt") or 0) * 100.0
                fr = float(d.get("fundingRate") or 0)
                oi = float(d.get("openInterest") or 0)
                oi_usd = float(d.get("openInterestValue") or 0)
            except (TypeError, ValueError):
                continue
            out.append({
                "symbol": sym,
                "last": last,
                "price_change_pct_24h": chg,
                "quote_volume_24h": qv,
                "funding_rate": fr,
                "open_interest": oi,
                "open_interest_usd": oi_usd,
            })
        return out

    async def fetch_liquidation_orders(
        self, symbol: str, *, limit: int = 20,
    ) -> list[dict[str, Any]]:
        sym = symbol.upper().replace(".P", "")
        url = f"{self.BASE}/v5/market/recent-trade"
        params = {"category": "linear", "symbol": sym, "limit": min(limit, 1000)}
        s = await self._s()
        async with s.get(url, params=params) as resp:
            if resp.status >= 400:
                return []
            payload = await resp.json()
        if payload.get("retCode") != 0:
            return []
        out: list[dict[str, Any]] = []
        for row in payload.get("result", {}).get("list", []) or []:
            try:
                px = float(row.get("price") or 0)
                qty = float(row.get("size") or 0)
            except (TypeError, ValueError):
                continue
            if qty * px < 10_000:
                continue
            out.append({
                "symbol": sym,
                "side": str(row.get("side") or ""),
                "price": px,
                "qty": qty,
                "notional_usd": px * qty,
                "time_ms": int(row.get("time") or 0),
            })
        return out[:limit]

    async def fetch_agg_trades(
        self, symbol: str, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await self.fetch_liquidation_orders(symbol, limit=limit)


# ═══════════════════════════════════════════════════════════════════════
class OkxClient(ExchangeClient):
    """OKX USDT-margined perpetual swaps. Public REST, no auth.

    Use when Binance fapi (451) and Bybit (403) are geo-blocked.
    Candles are OKX SWAP, not Binance USDT-M — confirm on the visualizer;
    bar prints can differ from ``BINANCE:SYMBOL.P``.
    """

    name = "okx"
    BASE = "https://www.okx.com"

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
        tf = _OKX_TF.get(timeframe.lower())
        if tf is None:
            raise ValueError(f"OKX: unsupported timeframe {timeframe}")
        inst = _okx_inst(symbol)
        url = f"{self.BASE}/api/v5/market/candles"
        params = {"instId": inst, "bar": tf, "limit": str(min(limit, 300))}
        s = await self._s()
        async with s.get(url, params=params) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(
                    f"OKX klines {inst}/{tf} HTTP {resp.status}: {text[:200]}")
            payload = await resp.json()
        if str(payload.get("code")) != "0":
            raise RuntimeError(
                f"OKX error {payload.get('code')}: {payload.get('msg')}")
        rows = payload.get("data") or []
        if not rows:
            return pd.DataFrame()
        # Newest-first: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        closed = [r for r in rows if len(r) < 9 or str(r[8]) == "1"]
        if not closed:
            closed = rows[1:] if len(rows) > 1 else []
        closed = list(reversed(closed))
        if not closed:
            return pd.DataFrame()
        padded = [list(r) + [""] * (9 - len(r)) for r in closed]
        df = pd.DataFrame(padded, columns=[
            "ts", "open", "high", "low", "close", "volume",
            "volCcy", "volCcyQuote", "confirm",
        ])
        df["ts"] = pd.to_datetime(pd.to_numeric(df["ts"]), unit="ms", utc=True)
        df.set_index("ts", inplace=True)
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df[["open", "high", "low", "close", "volume"]].dropna()

    async def fetch_top_volume_symbols(self, *, top_n: int,
                                       min_quote_volume: float) -> list[str]:
        if top_n <= 0:
            return []
        url = f"{self.BASE}/api/v5/market/tickers"
        params = {"instType": "SWAP"}
        s = await self._s()
        async with s.get(url, params=params) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"OKX tickers HTTP {resp.status}")
            payload = await resp.json()
        if str(payload.get("code")) != "0":
            return []
        ranked: list[tuple[str, float]] = []
        for d in payload.get("data") or []:
            inst = str(d.get("instId") or "")
            if not inst.endswith("-USDT-SWAP"):
                continue
            try:
                last = float(d.get("last") or 0)
                vol_base = float(d.get("volCcy24h") or 0)
            except (TypeError, ValueError):
                continue
            qv = vol_base * last
            if qv < min_quote_volume:
                continue
            ranked.append((_okx_to_qmie(inst), qv))
        ranked.sort(key=lambda r: -r[1])
        return [sym for sym, _ in ranked[:top_n]]

    async def fetch_premium_index(self, symbol: str) -> dict:
        inst = _okx_inst(symbol)
        url = f"{self.BASE}/api/v5/public/funding-rate"
        params = {"instId": inst}
        s = await self._s()
        async with s.get(url, params=params) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(
                    f"OKX funding {inst} HTTP {resp.status}: {text[:200]}")
            payload = await resp.json()
        if str(payload.get("code")) != "0":
            raise RuntimeError(
                f"OKX error {payload.get('code')}: {payload.get('msg')}")
        rows = payload.get("data") or []
        if not rows:
            return {"lastFundingRate": 0.0}
        row = rows[0]
        try:
            rate = float(row.get("fundingRate") or 0)
        except (TypeError, ValueError):
            rate = 0.0
        return {"lastFundingRate": rate, "symbol": _okx_to_qmie(inst)}

    async def fetch_market_tickers(self) -> list[dict[str, Any]]:
        url = f"{self.BASE}/api/v5/market/tickers"
        params = {"instType": "SWAP"}
        s = await self._s()
        async with s.get(url, params=params) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"OKX tickers HTTP {resp.status}")
            payload = await resp.json()
        if str(payload.get("code")) != "0":
            return []
        out: list[dict[str, Any]] = []
        for d in payload.get("data") or []:
            inst = str(d.get("instId") or "")
            if not inst.endswith("-USDT-SWAP"):
                continue
            sym = _okx_to_qmie(inst)
            try:
                last = float(d.get("last") or 0)
                vol_base = float(d.get("volCcy24h") or 0)
                qv = vol_base * last
                open24 = float(d.get("open24h") or last)
                if open24 > 0:
                    chg_pct = (last - open24) / open24 * 100.0
                else:
                    chg_pct = 0.0
                fr = float(d.get("fundingRate") or 0)
                oi = float(d.get("oi") or d.get("openInterest") or 0)
                oi_usd = float(d.get("oiCcy") or 0) * last if d.get("oiCcy") else oi * last
            except (TypeError, ValueError):
                continue
            out.append({
                "symbol": sym,
                "last": last,
                "price_change_pct_24h": chg_pct,
                "quote_volume_24h": qv,
                "funding_rate": fr,
                "open_interest": oi,
                "open_interest_usd": oi_usd,
            })
        return out

    async def fetch_liquidation_orders(
        self, symbol: str, *, limit: int = 20,
    ) -> list[dict[str, Any]]:
        inst = _okx_inst(symbol)
        url = f"{self.BASE}/api/v5/public/liquidation-orders"
        params = {"instType": "SWAP", "instId": inst, "limit": str(min(limit, 100))}
        s = await self._s()
        async with s.get(url, params=params) as resp:
            if resp.status >= 400:
                return []
            payload = await resp.json()
        if str(payload.get("code")) != "0":
            return []
        out: list[dict[str, Any]] = []
        for block in payload.get("data") or []:
            for row in block.get("details") or []:
                try:
                    px = float(row.get("bkPx") or row.get("px") or 0)
                    qty = float(row.get("sz") or 0)
                except (TypeError, ValueError):
                    continue
                out.append({
                    "symbol": _okx_to_qmie(inst),
                    "side": str(row.get("side") or block.get("side") or ""),
                    "price": px,
                    "qty": qty,
                    "notional_usd": px * qty,
                    "time_ms": int(row.get("ts") or block.get("ts") or 0),
                })
        return out[:limit]

    async def fetch_agg_trades(
        self, symbol: str, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        inst = _okx_inst(symbol)
        url = f"{self.BASE}/api/v5/market/trades"
        params = {"instId": inst, "limit": str(min(limit, 500))}
        s = await self._s()
        async with s.get(url, params=params) as resp:
            if resp.status >= 400:
                return []
            payload = await resp.json()
        if str(payload.get("code")) != "0":
            return []
        out: list[dict[str, Any]] = []
        for row in payload.get("data") or []:
            try:
                px = float(row.get("px") or 0)
                qty = float(row.get("sz") or 0)
            except (TypeError, ValueError):
                continue
            out.append({
                "price": px,
                "qty": qty,
                "notional_usd": px * qty,
                "time_ms": int(row.get("ts") or 0),
                "buyer_maker": str(row.get("side") or "").lower() == "sell",
            })
        return out


# ═══════════════════════════════════════════════════════════════════════
def get_client(source: str, *, timeout: float = 10.0) -> ExchangeClient:
    s = source.lower().strip()
    if s == "binance":
        return BinanceClient(timeout=timeout)
    if s == "bybit":
        return BybitClient(timeout=timeout)
    if s == "okx":
        return OkxClient(timeout=timeout)
    raise ValueError(f"Unknown data source: {source}")
