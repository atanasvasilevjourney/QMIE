"""
Bar-close flow context for the desk Flow module (OI + bar-CVD).

Read-only public REST. Does not feed ``compute_signal`` or ``W_*``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np
import pandas as pd

from .exchange_clients import BinanceClient, BybitClient, ExchangeClient, OkxClient, _okx_inst

logger = logging.getLogger(__name__)


def _ohlc_proxy_delta(df: pd.DataFrame) -> pd.Series:
    hl = (df["high"] - df["low"]).replace(0, np.nan)
    buy = df["volume"] * (df["close"] - df["low"]) / hl
    return buy - (df["volume"] - buy)


def _cvd_slope(delta: pd.Series, lookback: int = 6) -> float | None:
    if delta.empty:
        return None
    cvd = delta.cumsum()
    if len(cvd) < 2:
        return None
    n = min(lookback, len(cvd))
    return float(cvd.iloc[-1] - cvd.iloc[-n])


async def _binance_taker_delta(client: BinanceClient, symbol: str, timeframe: str, limit: int) -> pd.Series:
    from . import exchange_clients as ec

    tf = ec._BINANCE_TF.get(timeframe.lower())
    if tf is None:
        return pd.Series(dtype=float)
    sym = symbol.upper().replace(".P", "")
    url = f"{client.BASE}/fapi/v1/klines"
    params = {"symbol": sym, "interval": tf, "limit": min(limit, 1500)}
    s = await client._s()
    async with s.get(url, params=params) as resp:
        if resp.status >= 400:
            return pd.Series(dtype=float)
        data = await resp.json()
    if not data:
        return pd.Series(dtype=float)
    df = pd.DataFrame(data, columns=[
        "openTime", "open", "high", "low", "close", "volume", "closeTime",
        "quoteVolume", "trades", "takerBuyBase", "takerBuyQuote", "_ignore",
    ])
    df["openTime"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
    df.set_index("openTime", inplace=True)
    vol = pd.to_numeric(df["volume"], errors="coerce")
    taker_buy = pd.to_numeric(df["takerBuyBase"], errors="coerce")
    delta = 2.0 * taker_buy - vol
    if len(delta) > 0:
        delta = delta.iloc[:-1]
    return delta.dropna()


async def _binance_oi(client: BinanceClient, symbol: str) -> tuple[float | None, float | None]:
    sym = symbol.upper().replace(".P", "")
    s = await client._s()
    oi_now: float | None = None
    url = f"{client.BASE}/fapi/v1/openInterest"
    async with s.get(url, params={"symbol": sym}) as resp:
        if resp.status == 200:
            row = await resp.json()
            try:
                oi_now = float(row.get("openInterest") or 0)
            except (TypeError, ValueError):
                oi_now = None
    oi_chg: float | None = None
    hist_url = f"{client.BASE}/futures/data/openInterestHist"
    async with s.get(hist_url, params={"symbol": sym, "period": "4h", "limit": 2}) as resp:
        if resp.status == 200:
            rows = await resp.json()
            if isinstance(rows, list) and len(rows) >= 2:
                try:
                    a = float(rows[-2].get("sumOpenInterest") or 0)
                    b = float(rows[-1].get("sumOpenInterest") or 0)
                    if a > 0:
                        oi_chg = (b - a) / a * 100.0
                except (TypeError, ValueError, KeyError):
                    pass
    return oi_now, oi_chg


async def _okx_oi(client: OkxClient, symbol: str) -> tuple[float | None, float | None]:
    inst = _okx_inst(symbol)
    s = await client._s()
    url = f"{client.BASE}/api/v5/public/open-interest"
    params = {"instType": "SWAP", "instId": inst}
    async with s.get(url, params=params) as resp:
        if resp.status >= 400:
            return None, None
        payload = await resp.json()
    if str(payload.get("code")) != "0":
        return None, None
    rows = payload.get("data") or []
    if not rows:
        return None, None
    try:
        oi_now = float(rows[0].get("oi") or 0)
    except (TypeError, ValueError):
        return None, None
    return oi_now, None


async def _bybit_oi(client: BybitClient, symbol: str) -> tuple[float | None, float | None]:
    sym = symbol.upper().replace(".P", "")
    s = await client._s()
    url = f"{client.BASE}/v5/market/open-interest"
    params = {"category": "linear", "symbol": sym, "intervalTime": "4h", "limit": 2}
    async with s.get(url, params=params) as resp:
        if resp.status >= 400:
            return None, None
        payload = await resp.json()
    if payload.get("retCode") != 0:
        return None, None
    rows = list(reversed(payload.get("result", {}).get("list", []) or []))
    if not rows:
        return None, None
    try:
        oi_now = float(rows[-1].get("openInterest") or 0)
    except (TypeError, ValueError):
        return None, None
    oi_chg = None
    if len(rows) >= 2:
        try:
            a = float(rows[-2].get("openInterest") or 0)
            b = float(rows[-1].get("openInterest") or 0)
            if a > 0:
                oi_chg = (b - a) / a * 100.0
        except (TypeError, ValueError):
            pass
    return oi_now, oi_chg


async def flow_row_for_symbol(
    client: ExchangeClient,
    symbol: str,
    *,
    timeframe: str = "4h",
    limit: int = 24,
) -> dict[str, Any]:
    sym = symbol.upper().replace(".P", "")
    delta_src = "proxy"
    bar_delta: float | None = None
    cvd_slope: float | None = None

    try:
        if isinstance(client, BinanceClient):
            delta = await _binance_taker_delta(client, sym, timeframe, limit)
            delta_src = "taker"
        else:
            df = await client.fetch_klines(sym, timeframe, limit=limit)
            delta = _ohlc_proxy_delta(df) if not df.empty else pd.Series(dtype=float)
            delta_src = "proxy"
        if not delta.empty:
            bar_delta = float(delta.iloc[-1])
            cvd_slope = _cvd_slope(delta)
    except Exception as exc:
        logger.warning("flow delta %s: %s", sym, exc)

    oi_now: float | None = None
    oi_chg: float | None = None
    try:
        if isinstance(client, BinanceClient):
            oi_now, oi_chg = await _binance_oi(client, sym)
        elif isinstance(client, OkxClient):
            oi_now, oi_chg = await _okx_oi(client, sym)
        elif isinstance(client, BybitClient):
            oi_now, oi_chg = await _bybit_oi(client, sym)
    except Exception as exc:
        logger.warning("flow oi %s: %s", sym, exc)

    funding: float | None = None
    try:
        prem = await client.fetch_premium_index(sym)
        funding = float(prem.get("lastFundingRate") or 0)
    except Exception:
        funding = None

    return {
        "symbol": sym,
        "timeframe": timeframe,
        "open_interest": oi_now,
        "oi_change_pct": oi_chg,
        "bar_delta": bar_delta,
        "cvd_slope": cvd_slope,
        "delta_source": delta_src,
        "funding_rate": funding,
    }


async def build_flow_screener(
    client: ExchangeClient,
    symbols: list[str],
    *,
    timeframe: str = "4h",
    max_symbols: int = 18,
    concurrency: int = 4,
) -> dict[str, Any]:
    syms = [s.upper().replace(".P", "") for s in symbols[:max_symbols]]
    sem = asyncio.Semaphore(concurrency)
    rows: list[dict[str, Any]] = []

    async def one(sym: str) -> None:
        async with sem:
            rows.append(await flow_row_for_symbol(client, sym, timeframe=timeframe))

    await asyncio.gather(*(one(s) for s in syms))
    rows.sort(key=lambda r: abs(r.get("cvd_slope") or 0), reverse=True)
    return {
        "places_orders": False,
        "data_source": client.name,
        "timeframe": timeframe,
        "rows": rows,
        "note": "Bar-close OI + bar delta. Taker delta on Binance; proxy elsewhere.",
    }
