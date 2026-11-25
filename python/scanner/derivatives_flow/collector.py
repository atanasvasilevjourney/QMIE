"""Async multi-venue fetch for derivatives flow snapshots."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import aiohttp

from .core import (
    ASTER,
    BG,
    BV,
    DERIBIT,
    GATE,
    HL,
    HTX,
    OKX,
    asset_symbols,
    build_narrative,
    chart_payload,
    cvd_window,
    hourly_bucket,
    key_levels,
    liq_aggregate_rows,
    modelled_liq_clusters,
    observed_liq_clusters,
    oi_changes,
    parse_binance_klines,
    utc_now,
)

logger = logging.getLogger(__name__)
UA = {"User-Agent": "qmie-derivatives-flow/1.0"}


class _FetchLog:
    def __init__(self) -> None:
        self.ok: list[str] = []
        self.fail: dict[str, str] = {}

    def record_ok(self, name: str) -> None:
        if name not in self.ok:
            self.ok.append(name)

    def record_fail(self, name: str, err: str) -> None:
        self.fail[name] = err[:200]


async def _get_json(
    session: aiohttp.ClientSession,
    log: _FetchLog,
    name: str,
    url: str,
    *,
    params: dict | None = None,
    method: str = "GET",
    body: dict | None = None,
    timeout: float = 12.0,
) -> Any:
    try:
        if method == "POST":
            async with session.post(url, json=body, headers=UA, timeout=timeout) as resp:
                status = resp.status
                text = await resp.text()
        else:
            async with session.get(url, params=params, headers=UA, timeout=timeout) as resp:
                status = resp.status
                text = await resp.text()
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {text[:120]}")
        log.record_ok(name)
        return json.loads(text)
    except Exception as e:
        log.record_fail(name, f"{type(e).__name__}: {e}")
        raise


def _src(label: str, url: str) -> dict[str, str]:
    return {"source": label, "url": url, "fetched_at_utc": utc_now()}


async def binance_24h(session: aiohttp.ClientSession, log: _FetchLog, sym: str) -> dict[str, Any]:
    u = f"{BV}/api/v3/ticker/24hr"
    j = await _get_json(session, log, "binance_24h", u, params={"symbol": sym})
    return dict(
        last=float(j["lastPrice"]),
        high=float(j["highPrice"]),
        low=float(j["lowPrice"]),
        change_pct=float(j["priceChangePercent"]),
        quote_volume_usd=float(j["quoteVolume"]),
        **_src("Binance spot 24hr (data-api.binance.vision)", u),
    )


async def binance_klines(
    session: aiohttp.ClientSession, log: _FetchLog, sym: str, interval: str, limit: int
) -> list[dict]:
    u = f"{BV}/api/v3/klines"
    k = await _get_json(
        session, log, f"binance_klines_{interval}", u, params={"symbol": sym, "interval": interval, "limit": limit}
    )
    return parse_binance_klines(k)


async def okx_perp(session: aiohttp.ClientSession, log: _FetchLog, s: dict) -> dict[str, Any]:
    inst = s["okx_swap"]
    inst_j = await _get_json(session, log, "okx_instrument", f"{OKX}/api/v5/public/instruments", params={"instType": "SWAP", "instId": inst})
    ctval = float(inst_j["data"][0]["ctVal"])
    oi = await _get_json(session, log, "okx_oi", f"{OKX}/api/v5/public/open-interest", params={"instType": "SWAP", "instId": inst})
    fr = await _get_json(session, log, "okx_funding", f"{OKX}/api/v5/public/funding-rate", params={"instId": inst})
    mk = await _get_json(session, log, "okx_mark", f"{OKX}/api/v5/public/mark-price", params={"instType": "SWAP", "instId": inst})
    tk = await _get_json(session, log, "okx_ticker", f"{OKX}/api/v5/market/ticker", params={"instId": inst})
    row = oi["data"][0]
    tkr = tk["data"][0]
    fr0 = fr["data"][0]
    mk0 = mk["data"][0]
    return dict(
        exchange="OKX",
        mark=float(mk0["markPx"]),
        oi_usd=float(row["oiUsd"]),
        funding=float(fr0["fundingRate"]),
        funding_interval_h=8,
        vol24h_usd=float(tkr["volCcy24h"]) * float(tkr["last"]),
        ctval=ctval,
        **_src("OKX public REST", f"{OKX}/api/v5/public"),
    )


async def bitget_perp(session: aiohttp.ClientSession, log: _FetchLog, s: dict) -> dict[str, Any]:
    sym = s["bitget"]
    t = await _get_json(session, log, "bitget_ticker", f"{BG}/api/v2/mix/market/ticker", params={"symbol": sym, "productType": "usdt-futures"})
    oi = await _get_json(session, log, "bitget_oi", f"{BG}/api/v2/mix/market/open-interest", params={"symbol": sym, "productType": "usdt-futures"})
    fr = await _get_json(session, log, "bitget_funding", f"{BG}/api/v2/mix/market/current-fund-rate", params={"symbol": sym, "productType": "usdt-futures"})
    t0 = t["data"][0]
    o0 = oi["data"]["openInterestList"][0]
    f0 = fr["data"][0]
    mark = float(t0.get("markPrice") or t0["lastPr"])
    return dict(
        exchange="Bitget",
        mark=mark,
        oi_usd=float(o0["size"]) * mark,
        funding=float(f0["fundingRate"]),
        funding_interval_h=float(f0.get("fundingRateInterval") or 8),
        vol24h_usd=float(t0.get("usdtVolume") or 0),
        **_src("Bitget v2 mix", f"{BG}/api/v2/mix/market"),
    )


async def gate_perp(session: aiohttp.ClientSession, log: _FetchLog, s: dict) -> dict[str, Any]:
    c = await _get_json(session, log, "gate_contract", f"{GATE}/futures/usdt/contracts/{s['gate']}")
    t = await _get_json(session, log, "gate_ticker", f"{GATE}/futures/usdt/tickers", params={"contract": s["gate"]})
    mult = float(c["quanto_multiplier"])
    mark = float(c["mark_price"])
    t0 = t[0]
    return dict(
        exchange="Gate",
        mark=mark,
        oi_usd=float(t0["total_size"]) * mult * mark,
        funding=float(c["funding_rate"]),
        funding_interval_h=float(c.get("funding_interval", 28800)) / 3600,
        vol24h_usd=float(t0.get("volume_24h_quote") or 0),
        mult=mult,
        **_src("Gate futures usdt", f"{GATE}/futures/usdt"),
    )


async def htx_perp(session: aiohttp.ClientSession, log: _FetchLog, s: dict) -> dict[str, Any]:
    oi = await _get_json(session, log, "htx_oi", f"{HTX}/linear-swap-api/v1/swap_open_interest", params={"contract_code": s["htx"]})
    fr = await _get_json(session, log, "htx_funding", f"{HTX}/linear-swap-api/v1/swap_funding_rate", params={"contract_code": s["htx"]})
    row = oi["data"][0]
    fr0 = fr["data"]
    return dict(
        exchange="HTX",
        mark=None,
        oi_usd=float(row["value"]),
        funding=float(fr0["funding_rate"]),
        funding_interval_h=8,
        vol24h_usd=float(row.get("trade_turnover") or 0),
        **_src("HTX linear-swap", f"{HTX}/linear-swap-api/v1"),
    )


async def hl_perp(session: aiohttp.ClientSession, log: _FetchLog, s: dict) -> dict[str, Any]:
    r = await _get_json(session, log, "hyperliquid", HL, method="POST", body={"type": "metaAndAssetCtxs"})
    idx = [u["name"] for u in r[0]["universe"]].index(s["hl"])
    c = r[1][idx]
    mark = float(c["markPx"])
    return dict(
        exchange="Hyperliquid",
        mark=mark,
        oi_usd=float(c["openInterest"]) * mark,
        funding=float(c["funding"]),
        funding_interval_h=1,
        vol24h_usd=float(c["dayNtlVlm"]),
        **_src("Hyperliquid metaAndAssetCtxs", HL),
    )


async def aster_perp(session: aiohttp.ClientSession, log: _FetchLog, s: dict) -> dict[str, Any]:
    p = await _get_json(session, log, "aster_premium", f"{ASTER}/fapi/v1/premiumIndex", params={"symbol": s["aster"]})
    oi = await _get_json(session, log, "aster_oi", f"{ASTER}/fapi/v1/openInterest", params={"symbol": s["aster"]})
    t = await _get_json(session, log, "aster_24h", f"{ASTER}/fapi/v1/ticker/24hr", params={"symbol": s["aster"]})
    mark = float(p["markPrice"])
    return dict(
        exchange="Aster",
        mark=mark,
        oi_usd=float(oi["openInterest"]) * mark,
        funding=float(p["lastFundingRate"]),
        funding_interval_h=8,
        vol24h_usd=float(t["quoteVolume"]),
        **_src("Aster fapi", f"{ASTER}/fapi/v1"),
    )


async def deribit_perp(session: aiohttp.ClientSession, log: _FetchLog, s: dict) -> dict[str, Any] | dict[str, str]:
    if not s["deribit"]:
        return {"error": "no Deribit perpetual for asset"}
    r = await _get_json(
        session, log, "deribit", f"{DERIBIT}/get_book_summary_by_instrument", params={"instrument_name": s["deribit"]}
    )
    row = r["result"][0]
    return dict(
        exchange="Deribit",
        mark=float(row["mark_price"]),
        oi_usd=float(row["open_interest"]),
        funding=float(row.get("funding_8h") or 0),
        funding_interval_h=8,
        vol24h_usd=float(row.get("volume_usd") or 0),
        **_src("Deribit book summary", DERIBIT),
    )


async def bybit_ws_sample(sym: str, seconds: int, log: _FetchLog) -> dict[str, Any]:
    tick: dict[str, Any] = {}
    liqs: list[dict] = []
    url = "wss://stream.bybit.com/v5/public/linear"
    t0 = time.time()
    try:
        import websockets

        async with websockets.connect(url, open_timeout=10, ping_interval=15) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": [f"tickers.{sym}", f"allLiquidation.{sym}"]}))
            while time.time() - t0 < seconds:
                try:
                    raw = await asyncio.wait_for(ws.recv(), max(0.5, seconds - (time.time() - t0)))
                except asyncio.TimeoutError:
                    break
                m = json.loads(raw)
                tp = m.get("topic", "")
                if tp.startswith("tickers."):
                    tick.update({k: v for k, v in m["data"].items() if v not in (None, "")})
                elif tp.startswith("allLiquidation."):
                    for d in m["data"]:
                        liqs.append(
                            dict(
                                side="long" if d["S"] == "Buy" else "short",
                                qty=float(d["v"]),
                                price=float(d["p"]),
                                ts=int(d["T"]),
                            )
                        )
        log.record_ok("bybit_ws")
    except Exception as e:
        log.record_fail("bybit_ws", str(e))
    dur = round(time.time() - t0, 1)
    out: dict[str, Any] = {
        "sample_seconds": dur,
        "liquidations_sampled": liqs,
        **_src("Bybit public WebSocket", url),
    }
    if tick.get("markPrice"):
        out["perp"] = dict(
            exchange="Bybit",
            mark=float(tick["markPrice"]),
            oi_usd=float(tick["openInterestValue"]),
            funding=float(tick["fundingRate"]),
            funding_interval_h=float(tick.get("fundingIntervalHour") or 8),
            vol24h_usd=float(tick.get("turnover24h") or 0),
            **_src("Bybit WS tickers", url),
        )
    else:
        out["perp"] = {"error": "Bybit WS ticker not received"}
    return out


async def oi_history(session: aiohttp.ClientSession, log: _FetchLog, s: dict) -> tuple[dict[str, list[tuple[int, float]]], dict[str, str]]:
    h: dict[str, list[tuple[int, float]]] = {}
    sources: dict[str, str] = {}
    j = await _get_json(
        session,
        log,
        "okx_oi_hist",
        f"{OKX}/api/v5/rubik/stat/contracts/open-interest-history",
        params={"instId": s["okx_swap"], "period": "1H", "limit": 100},
    )
    h["OKX"] = sorted((int(x[0]), float(x[3])) for x in j["data"])
    sources["OKX"] = "OKX rubik OI history 1H"
    j = await _get_json(
        session,
        log,
        "gate_stats_1h",
        f"{GATE}/futures/usdt/contract_stats",
        params={"contract": s["gate"], "interval": "1h", "limit": 100},
    )
    h["Gate"] = sorted((int(x["time"]) * 1000, float(x["open_interest_usd"])) for x in j)
    sources["Gate"] = "Gate contract_stats 1h"
    j = await _get_json(
        session,
        log,
        "htx_oi_hist",
        f"{HTX}/linear-swap-api/v1/swap_his_open_interest",
        params={"contract_code": s["htx"], "period": "60min", "amount_type": 1, "size": 100},
    )
    h["HTX"] = sorted((int(x["ts"]), float(x["value"])) for x in j["data"]["tick"])
    sources["HTX"] = "HTX swap_his_open_interest 60min"
    return h, sources


async def long_short(session: aiohttp.ClientSession, log: _FetchLog, s: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        j = await _get_json(
            session,
            log,
            "okx_lsr",
            f"{OKX}/api/v5/rubik/stat/contracts/long-short-account-ratio-contract",
            params={"instId": s["okx_swap"], "period": "1H", "limit": 25},
        )
        rows = j["data"]
        out["OKX_accounts"] = {
            "ratio": float(rows[0][1]),
            "24h_ago": float(rows[24][1]) if len(rows) > 24 else None,
            "bar_utc": utc_now(int(rows[0][0]) / 1000),
            "source": "OKX long-short-account-ratio",
        }
    except Exception as e:
        out["OKX_accounts"] = {"error": str(e)[:150]}
    try:
        j = await _get_json(
            session,
            log,
            "okx_top_lsr",
            f"{OKX}/api/v5/rubik/stat/contracts/long-short-position-ratio-contract-top-trader",
            params={"instId": s["okx_swap"], "period": "1H", "limit": 25},
        )
        rows = j["data"]
        out["OKX_top_traders_positions"] = {
            "ratio": float(rows[0][1]),
            "24h_ago": float(rows[24][1]) if len(rows) > 24 else None,
            "bar_utc": utc_now(int(rows[0][0]) / 1000),
            "source": "OKX top-trader position ratio",
        }
    except Exception as e:
        out["OKX_top_traders_positions"] = {"error": str(e)[:150]}
    try:
        j = await _get_json(
            session,
            log,
            "bitget_lsr",
            f"{BG}/api/v2/mix/market/account-long-short",
            params={"symbol": s["bitget"], "period": "1h"},
        )
        rows = j["data"]
        out["Bitget_accounts"] = {
            "ratio": float(rows[-1]["longShortAccountRatio"]),
            "24h_ago": float(rows[-25]["longShortAccountRatio"]) if len(rows) >= 25 else None,
            "bar_utc": utc_now(int(rows[-1]["ts"]) / 1000),
            "source": "Bitget account-long-short 1h",
        }
    except Exception as e:
        out["Bitget_accounts"] = {"error": str(e)[:150]}
    try:
        j = await _get_json(
            session,
            log,
            "gate_lsr",
            f"{GATE}/futures/usdt/contract_stats",
            params={"contract": s["gate"], "interval": "1h", "limit": 25},
        )
        out["Gate_accounts"] = {
            "ratio": j[-1]["lsr_account"],
            "24h_ago": j[0]["lsr_account"],
            "bar_utc": utc_now(j[-1]["time"]),
            "source": "Gate lsr_account",
        }
        out["Gate_top_traders_size"] = {
            "ratio": j[-1]["top_lsr_size"],
            "24h_ago": j[0]["top_lsr_size"],
            "bar_utc": utc_now(j[-1]["time"]),
            "source": "Gate top_lsr_size",
        }
    except Exception as e:
        out["Gate_accounts"] = {"error": str(e)[:150]}
    return out


async def cvd_series(session: aiohttp.ClientSession, log: _FetchLog, s: dict, spot_1h: list[dict]) -> tuple[dict, dict, dict]:
    spot: dict[str, dict[int, float]] = {}
    perp: dict[str, dict[int, float]] = {}
    srcs: dict[str, str] = {}
    spot["Binance"] = hourly_bucket([(k["t"], 2 * k["tbq"] - k["qv"]) for k in spot_1h])
    srcs["spot:Binance"] = "Binance spot 1h klines taker"
    px = {k["t"]: k["c"] for k in spot_1h}
    try:
        j = await _get_json(
            session,
            log,
            "okx_spot_taker",
            f"{OKX}/api/v5/rubik/stat/taker-volume",
            params={"ccy": s["okx_spot"].split("-")[0], "instType": "SPOT", "period": "1H"},
        )
        spot["OKX"] = hourly_bucket(
            [(int(x[0]), (float(x[2]) - float(x[1])) * px[int(x[0])]) for x in j["data"] if int(x[0]) in px]
        )
        srcs["spot:OKX"] = "OKX rubik taker-volume SPOT"
    except Exception as e:
        srcs["spot:OKX"] = f"FAILED {e}"
    try:
        j = await _get_json(
            session,
            log,
            "okx_perp_taker",
            f"{OKX}/api/v5/rubik/stat/taker-volume-contract",
            params={"instId": s["okx_swap"], "period": "1H", "unit": 2, "limit": 100},
        )
        perp["OKX"] = hourly_bucket(
            [(int(x[0]), float(x[2]) - float(x[1])) for x in j["data"] if float(x[1]) > 0 and float(x[2]) > 0]
        )
        srcs["perp:OKX"] = "OKX rubik taker-volume-contract USD"
    except Exception as e:
        srcs["perp:OKX"] = f"FAILED {e}"
    try:
        j = await _get_json(
            session,
            log,
            "bitget_taker",
            f"{BG}/api/v2/mix/market/taker-buy-sell",
            params={"symbol": s["bitget"], "period": "1h", "limit": 100},
        )
        perp["Bitget"] = hourly_bucket(
            [
                (int(x["ts"]), (float(x["buyVolume"]) - float(x["sellVolume"])) * px.get(int(x["ts"]), 0))
                for x in j["data"]
                if int(x["ts"]) in px
            ]
        )
        srcs["perp:Bitget"] = "Bitget taker-buy-sell 1h"
    except Exception as e:
        srcs["perp:Bitget"] = f"FAILED {e}"
    try:
        j = await _get_json(
            session,
            log,
            "gate_taker",
            f"{GATE}/futures/usdt/contract_stats",
            params={"contract": s["gate"], "interval": "1h", "limit": 100},
        )
        mult = float(
            (await _get_json(session, log, "gate_contract2", f"{GATE}/futures/usdt/contracts/{s['gate']}"))[
                "quanto_multiplier"
            ]
        )
        perp["Gate"] = hourly_bucket(
            [
                (x["time"] * 1000, (x["long_taker_size"] - x["short_taker_size"]) * mult * x["mark_price"])
                for x in j
            ]
        )
        srcs["perp:Gate"] = "Gate contract_stats taker"
    except Exception as e:
        srcs["perp:Gate"] = f"FAILED {e}"
    try:
        j = await _get_json(
            session,
            log,
            "aster_klines",
            f"{ASTER}/fapi/v1/klines",
            params={"symbol": s["aster"], "interval": "1h", "limit": 100},
        )
        perp["Aster"] = hourly_bucket([(int(x[0]), 2 * float(x[10]) - float(x[7])) for x in j])
        srcs["perp:Aster"] = "Aster fapi klines 1h"
    except Exception as e:
        srcs["perp:Aster"] = f"FAILED {e}"
    return spot, perp, srcs


async def liq_okx(session: aiohttp.ClientSession, log: _FetchLog, s: dict, start_ms: int, ctval: float) -> dict[str, Any]:
    url = f"{OKX}/api/v5/public/liquidation-orders"
    rows: list[dict] = []
    after = None
    for _ in range(60):
        params: dict[str, Any] = {
            "instType": "SWAP",
            "uly": s["okx_swap"].rsplit("-", 1)[0],
            "state": "filled",
            "limit": 100,
        }
        if after:
            params["after"] = after
        d = await _get_json(session, log, "okx_liq", url, params=params)
        det = d["data"][0]["details"] if d.get("data") else []
        if not det:
            break
        for x in det:
            side = (
                x["posSide"]
                if x["posSide"] in ("long", "short")
                else ("long" if x["side"] == "sell" else "short")
            )
            rows.append(
                dict(
                    side=side,
                    usd=float(x["sz"]) * ctval * float(x["bkPx"]),
                    price=float(x["bkPx"]),
                    ts=int(x["ts"]),
                )
            )
        after = det[-1]["ts"]
        if int(after) < start_ms:
            break
    rows = [r for r in rows if r["ts"] >= start_ms]
    total, long_u, short_u = liq_aggregate_rows(rows)
    oldest = min((r["ts"] for r in rows), default=None)
    cov = (time.time() * 1000 - oldest) / 3.6e6 if oldest else 0
    return {
        "exchange": "OKX",
        "total_usd": total,
        "long_usd": long_u,
        "short_usd": short_u,
        "n_orders": len(rows),
        "coverage_hours": round(min(cov, 24), 2),
        "complete": cov >= 23.0,
        "method": "OKX liquidation-orders pagination",
        "_rows": rows,
        **_src("OKX liquidation-orders", url),
    }


async def liq_gate(session: aiohttp.ClientSession, log: _FetchLog, s: dict, start_ms: int) -> dict[str, Any]:
    url = f"{GATE}/futures/usdt/contract_stats"
    j = await _get_json(session, log, "gate_liq_stats", url, params={"contract": s["gate"], "interval": "1h", "limit": 30})
    j = sorted(j, key=lambda x: x["time"])[-24:]
    long_u = sum(x["long_liq_usd"] for x in j)
    short_u = sum(x["short_liq_usd"] for x in j)
    rows: list[dict] = []
    try:
        mult = float(
            (await _get_json(session, log, "gate_contract_liq", f"{GATE}/futures/usdt/contracts/{s['gate']}"))[
                "quanto_multiplier"
            ]
        )
        orders = await _get_json(
            session,
            log,
            "gate_liq_orders",
            f"{GATE}/futures/usdt/liq_orders",
            params={"contract": s["gate"], "limit": 1000, "from": start_ms // 1000},
        )
        for x in orders:
            sz = float(x["size"])
            rows.append(
                dict(
                    side="long" if sz < 0 or float(x.get("order_size", 0)) < 0 else "short",
                    usd=abs(sz) * mult * float(x["fill_price"]),
                    price=float(x["fill_price"]),
                    ts=int(x["time"]) * 1000,
                )
            )
    except Exception:
        pass
    return {
        "exchange": "Gate",
        "total_usd": long_u + short_u,
        "long_usd": long_u,
        "short_usd": short_u,
        "coverage_hours": len(j),
        "complete": len(j) >= 24,
        "method": "Gate hourly long_liq_usd/short_liq_usd",
        "_rows": rows,
        **_src("Gate contract_stats liq", url),
    }


async def liq_htx(session: aiohttp.ClientSession, log: _FetchLog, s: dict, start_ms: int, end_ms: int) -> dict[str, Any]:
    url = f"{HTX}/linear-swap-api/v3/swap_liquidation_orders"
    rows: list[dict] = []
    seen: set[str] = set()
    w = start_ms
    while w < end_ms:
        we = min(w + 3_600_000, end_ms)
        cur = w
        for _ in range(20):
            d = await _get_json(
                session,
                log,
                "htx_liq",
                url,
                params={"contract": s["htx"], "trade_type": 0, "start_time": cur, "end_time": we, "direct": "next"},
            )
            chunk = d.get("data") or []
            for x in chunk:
                if x["query_id"] in seen:
                    continue
                seen.add(x["query_id"])
                rows.append(
                    dict(
                        side="long" if x["direction"] == "sell" else "short",
                        usd=float(x["trade_turnover"]),
                        price=float(x["price"]),
                        ts=int(x["created_at"]),
                    )
                )
            if len(chunk) < 50:
                break
            cur = max(x["created_at"] for x in chunk) + 1
        w = we
    total, long_u, short_u = liq_aggregate_rows(rows)
    return {
        "exchange": "HTX",
        "total_usd": total,
        "long_usd": long_u,
        "short_usd": short_u,
        "n_orders": len(rows),
        "coverage_hours": 24.0 if rows else 0,
        "complete": bool(rows),
        "_rows": rows,
        **_src("HTX swap_liquidation_orders", url),
    }


async def liq_coinalyze(
    session: aiohttp.ClientSession, log: _FetchLog, asset: str, start_ms: int, end_ms: int, api_key: str
) -> dict[str, Any]:
    if not api_key:
        return {"error": "COINALYZE_API_KEY not set"}
    url = "https://api.coinalyze.net/v1/liquidation-history"
    m = {"Binance": f"{asset}USDT_PERP.A", "Bybit": f"{asset}USDT.6"}
    async with session.get(
        url,
        params={
            "symbols": ",".join(m.values()),
            "interval": "1hour",
            "from": start_ms // 1000,
            "to": end_ms // 1000,
            "convert_to_usd": "true",
        },
        headers={"api_key": api_key, **UA},
        timeout=15,
    ) as resp:
        if resp.status != 200:
            text = await resp.text()
            log.record_fail("coinalyze", f"HTTP {resp.status}")
            return {"error": text[:120]}
        payload = await resp.json()
        log.record_ok("coinalyze")
    out: dict[str, Any] = {}
    for item in payload:
        ex = next(k for k, v in m.items() if v == item["symbol"])
        long_u = sum(x["l"] for x in item["history"])
        short_u = sum(x["s"] for x in item["history"])
        out[ex] = {
            "exchange": ex,
            "total_usd": long_u + short_u,
            "long_usd": long_u,
            "short_usd": short_u,
            "complete": True,
            **_src("Coinalyze liquidation-history", url),
        }
    return out


def _append_snapshot(asset: str, snap: dict[str, Any], data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "flow_snapshots.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snap) + "\n")


def snapshot_oi_change(asset: str, cur: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    path = data_dir / "flow_snapshots.jsonl"
    if not path.exists():
        return {}
    snaps: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                snaps.append(json.loads(line))
    except Exception:
        return {}
    snaps = [x for x in snaps if x.get("asset") == asset and x.get("t", 0) < cur["t"] - 600_000]
    out: dict[str, Any] = {}
    for hrs in (1, 4, 24):
        tgt = cur["t"] - hrs * 3_600_000
        c = [x for x in snaps if abs(x["t"] - tgt) < 0.25 * hrs * 3_600_000 + 900_000]
        if not c:
            out[f"{hrs}h"] = None
            continue
        p = min(c, key=lambda x: abs(x["t"] - tgt))
        common = set(p.get("oi_by_ex") or {}) & set(cur.get("oi_by_ex") or {})
        a = sum(cur["oi_by_ex"][e] for e in common)
        b = sum(p["oi_by_ex"][e] for e in common)
        out[f"{hrs}h"] = {
            "chg_pct": (a / b - 1) * 100 if b else None,
            "vs_snapshot_utc": utc_now(p["t"] / 1000),
            "venues": sorted(common),
        }
    return out


async def safe_call(coro):
    try:
        return await coro
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}


async def build_derivatives_flow_snapshot(
    asset: str,
    *,
    liq_sample_sec: int = 20,
    coinalyze_key: str = "",
    data_dir: Path | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    asset = asset.upper()
    if asset not in ("BTC", "ETH", "SOL"):
        raise ValueError("symbol must be BTC, ETH, or SOL")
    t0 = time.time()
    log = _FetchLog()
    s = asset_symbols(asset)
    now_ms = int(time.time() * 1000)
    day0 = now_ms - now_ms % 86_400_000
    start24 = now_ms - 86_400_000
    data_dir = data_dir or Path(__file__).resolve().parents[2] / "data"

    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        t24, k1h, k4h, k1d, okx, bitget, gate, htx, hl, aster, deribit, bybit, oih, lsr, liq_gate_r, liq_htx_r, coinalyze_r, oi4h = await asyncio.gather(
            safe_call(binance_24h(session, log, s["binance"])),
            safe_call(binance_klines(session, log, s["binance"], "1h", 200)),
            safe_call(binance_klines(session, log, s["binance"], "4h", 500)),
            safe_call(binance_klines(session, log, s["binance"], "1d", 500)),
            safe_call(okx_perp(session, log, s)),
            safe_call(bitget_perp(session, log, s)),
            safe_call(gate_perp(session, log, s)),
            safe_call(htx_perp(session, log, s)),
            safe_call(hl_perp(session, log, s)),
            safe_call(aster_perp(session, log, s)),
            safe_call(deribit_perp(session, log, s)),
            safe_call(bybit_ws_sample(s["bybit"], liq_sample_sec, log)),
            safe_call(oi_history(session, log, s)),
            safe_call(long_short(session, log, s)),
            safe_call(liq_gate(session, log, s, start24)),
            safe_call(liq_htx(session, log, s, start24, now_ms)),
            safe_call(liq_coinalyze(session, log, asset, start24, now_ms, coinalyze_key)),
            safe_call(
                _get_json(
                    session,
                    log,
                    "okx_oi_hist_4h",
                    f"{OKX}/api/v5/rubik/stat/contracts/open-interest-history",
                    params={"instId": s["okx_swap"], "period": "4H", "limit": 100},
                )
            ),
        )

    if not isinstance(t24, dict) or "error" in t24 or not isinstance(k1h, list):
        raise RuntimeError(f"core price data failed: {t24}")

    okx_ctval = okx.get("ctval", 0.01) if isinstance(okx, dict) and "error" not in okx else 0.01
    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        liq_okx_r = await safe_call(liq_okx(session, log, s, start24, okx_ctval))

    price = float(t24["last"])
    perps: list[dict] = []
    for item in (okx, bitget, gate, htx, hl, aster, deribit):
        if isinstance(item, dict) and "error" not in item and item.get("exchange"):
            perps.append(item)
    if isinstance(bybit, dict) and "error" not in bybit:
        bp = bybit.get("perp")
        if isinstance(bp, dict) and "error" not in bp:
            perps.append(bp)

    tot_oi = sum(float(p.get("oi_usd") or 0) for p in perps)
    f8 = (
        sum(p["funding"] * 8 / p["funding_interval_h"] * p["oi_usd"] for p in perps) / tot_oi
        if tot_oi
        else None
    )

    if isinstance(oih, tuple) and len(oih) == 2:
        oi_hist, oi_src = oih
    else:
        oi_hist, oi_src = {}, {}
    oi_chg = (
        oi_changes(oi_hist)
        if oi_hist
        else {"error": (oih.get("error") if isinstance(oih, dict) else "unavailable")}
    )

    snap = {"t": now_ms, "asset": asset, "oi_by_ex": {p["exchange"]: p["oi_usd"] for p in perps}, "price": price}
    _append_snapshot(asset, snap, data_dir)
    snap_chg = snapshot_oi_change(asset, snap, data_dir)

    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        spot_s, perp_s, cvd_src = await cvd_series(session, log, s, k1h)

    hour_floor = start24 - start24 % 3_600_000 + 3_600_000
    cvd = {
        "spot_24h": cvd_window(spot_s, hour_floor),
        "perp_24h": cvd_window(perp_s, hour_floor),
        "spot_since_0000utc": cvd_window(spot_s, day0),
        "perp_since_0000utc": cvd_window(perp_s, day0),
        "window_note": "hourly taker bars; 24h includes current partial hour",
        "sources": cvd_src,
    }

    liq: dict[str, Any] = {}
    for key, val in (("OKX", liq_okx_r), ("Gate", liq_gate_r), ("HTX", liq_htx_r)):
        if isinstance(val, dict) and "error" not in val:
            liq[key] = val
    if isinstance(bybit, dict) and "error" not in bybit:
        bl = bybit.get("liquidations_sampled") or []
        long_u = sum(x["qty"] * x["price"] for x in bl if x["side"] == "long")
        short_u = sum(x["qty"] * x["price"] for x in bl if x["side"] == "short")
        liq["Bybit"] = {
            "exchange": "Bybit",
            "complete": False,
            "sample_seconds": bybit.get("sample_seconds"),
            "n_orders": len(bl),
            "long_usd": long_u,
            "short_usd": short_u,
            "total_usd": long_u + short_u,
            "note": "live WebSocket sample only",
            **_src("Bybit WS allLiquidation", "wss://stream.bybit.com/v5/public/linear"),
        }
    if isinstance(coinalyze_r, dict) and "error" not in coinalyze_r:
        for ex, row in coinalyze_r.items():
            if isinstance(row, dict) and "error" not in row:
                liq[ex] = row

    complete = {k: v for k, v in liq.items() if v.get("complete") and "error" not in v}
    liq_tot = {
        "total_usd": sum(v["total_usd"] for v in complete.values()),
        "long_usd": sum(v["long_usd"] for v in complete.values()),
        "short_usd": sum(v["short_usd"] for v in complete.values()),
        "venues_included": sorted(complete),
    }
    missing = {
        "Binance": "no free 24h liquidation history (optional COINALYZE_API_KEY)",
        "Bybit (24h)": "REST blocked in some regions; WS sample or Coinalyze",
        "Bitget": "no public liquidation history",
        "Hyperliquid": "no public liquidation history",
    }
    if "Binance" in complete:
        missing.pop("Binance", None)
        missing.pop("Bybit (24h)", None)

    rows = [r for v in liq.values() for r in v.get("_rows", [])]
    obs_top = observed_liq_clusters(rows, price)
    for v in liq.values():
        v.pop("_rows", None)

    prof = None
    levels: dict[str, Any]
    if isinstance(k1d, list) and isinstance(k4h, list):
        levels = key_levels(k1d, k4h, price)
        prof = levels.pop("_volume_profile", None)
    else:
        levels = {"error": "klines unavailable"}

    model: list[dict] = []
    if isinstance(oi4h, dict) and "data" in oi4h and isinstance(k4h, list):
        kmap = {k["t"]: k for k in k4h}
        ser = sorted((int(x[0]), float(x[3])) for x in oi4h["data"])
        rows4: list[tuple[int, float, float | None, float, float]] = []
        for t, oi in ser:
            later = [k for k in k4h if k["t"] > t]
            rows4.append(
                (
                    t,
                    oi,
                    kmap.get(t, {}).get("c"),
                    min((k["l"] for k in later), default=price),
                    max((k["h"] for k in later), default=price),
                )
            )
        model = modelled_liq_clusters(rows4, price)

    price_block = dict(spot_last=price, **{k: v for k, v in t24.items() if k != "error"})

    result: dict[str, Any] = {
        "asset": asset,
        "generated_at_utc": utc_now(),
        "price": price_block,
        "perp_mark_by_exchange": {p["exchange"]: p["mark"] for p in perps if p.get("mark")},
        "open_interest": {
            "total_usd_now": tot_oi,
            "by_exchange": {
                p["exchange"]: {
                    "oi_usd": p["oi_usd"],
                    "source": p.get("source"),
                    "fetched_at_utc": p.get("fetched_at_utc"),
                    "available": True,
                }
                for p in perps
            },
            "change_from_history": oi_chg,
            "history_sources": oi_src,
            "change_from_own_snapshots": snap_chg,
        },
        "funding": {
            "oi_weighted_8h_equiv": f8,
            "by_exchange": {
                p["exchange"]: {
                    "rate": p["funding"],
                    "interval_h": p["funding_interval_h"],
                    "8h_equiv": p["funding"] * 8 / p["funding_interval_h"],
                }
                for p in perps
            },
        },
        "long_short": lsr if isinstance(lsr, dict) else {"error": str(lsr)},
        "cvd": cvd,
        "liquidations_24h": {
            "aggregate_of_complete_venues": liq_tot,
            "by_exchange": liq,
            "missing": missing,
            "observed_price_clusters": obs_top,
            "observed_clusters_note": "0.25% bins from reported liquidation prints",
        },
        "levels": {k: v for k, v in levels.items() if not k.startswith("_")},
        "modelled_liq_clusters": {
            "clusters": model,
            "note": "MODEL ESTIMATE from OKX 4H OI increases; not observed data",
        },
        "sources_contributed": sorted(log.ok),
        "fetch_errors": log.fail,
        "cache_note": "server-side snapshot; refresh on TTL",
    }
    result["narrative"] = build_narrative(result)
    result["chart"] = chart_payload(
        k4h if isinstance(k4h, list) else [],
        spot_s,
        perp_s,
        oi_hist,
        result["levels"],
        model,
        prof,
        price,
    )
    result["runtime_sec"] = round(time.time() - t0, 1)
    return result