"""
QMIE — Altcoin Attention Selector (read-only)
=============================================
Ranks symbols by cross-detector attention for pump/breakout *watchlists*.
Combines microstructure hits with optional radar / TEMA context.

Signal-only. Never places orders. Never retunes W_*.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

import pandas as pd

from .exchange_clients import ExchangeClient
from .microstructure import MicrostructureConfig, run_detectors

logger = logging.getLogger(__name__)

PumpProb = Literal["LOW", "MED", "HIGH"]


@dataclass
class AttentionConfig:
    top_n: int = 40
    deep_scan_n: int = 25
    min_quote_volume: float = 5_000_000.0
    refresh_sec: int = 300
    micro: MicrostructureConfig = field(default_factory=MicrostructureConfig)

    def validate(self) -> None:
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if self.deep_scan_n < 1:
            raise ValueError("deep_scan_n must be >= 1")
        self.micro.validate()


@dataclass
class AttentionRow:
    symbol: str
    attention_score: float
    pump_probability: PumpProb
    tags: list[str]
    hits: list[dict[str, Any]]
    quote_volume_24h: float
    price_change_pct_24h: float
    funding_rate: float
    open_interest_usd: Optional[float]
    oi_change_pct: Optional[float]
    qmie_radar_color: Optional[str] = None
    qmie_tema: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AttentionSnapshot:
    as_of: Optional[str]
    status: str
    data_source: str
    count: int
    rows: list[dict[str, Any]] = field(default_factory=list)
    note: Optional[str] = None
    enabled: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def empty_attention_snapshot(
    *, enabled: bool = True, data_source: str = "okx", note: str = "no_attention_yet",
) -> AttentionSnapshot:
    return AttentionSnapshot(
        as_of=None,
        status="empty",
        data_source=data_source,
        count=0,
        note=note,
        enabled=enabled,
    )


def _pump_probability(score: float, n_hits: int) -> PumpProb:
    if score >= 65 and n_hits >= 3:
        return "HIGH"
    if score >= 40 and n_hits >= 2:
        return "MED"
    return "LOW"


def _attention_score(hits: list) -> float:
    """Weighted sum of detector sub-scores → 0–100."""
    if not hits:
        return 0.0
    weights = {
        "vol_velocity": 22,
        "oi_influx": 18,
        "funding_squeeze": 16,
        "range_breakout": 14,
        "vol_turnover": 12,
        "liquidations": 10,
        "whale_print": 8,
        "volatility": 8,
    }
    total_w = 0.0
    acc = 0.0
    for h in hits:
        w = weights.get(h.tag, 8)
        acc += w * float(h.score)
        total_w += w
    if total_w <= 0:
        return 0.0
    return round(min(100.0, acc / total_w * 100.0), 1)


def _rank_candidates(
    tickers: list[dict[str, Any]],
    *,
    min_quote_volume: float,
    top_n: int,
) -> list[dict[str, Any]]:
    rows = [
        t for t in tickers
        if float(t.get("quote_volume_24h") or 0) >= min_quote_volume
    ]
    rows.sort(
        key=lambda t: (
            float(t.get("quote_volume_24h") or 0)
            * (1.0 + abs(float(t.get("price_change_pct_24h") or 0)) / 100.0)
        ),
        reverse=True,
    )
    return rows[:top_n]


async def _deep_fetch(
    client: ExchangeClient,
    symbol: str,
    sem: asyncio.Semaphore,
) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], list, list]:
    async with sem:
        df_1m: Optional[pd.DataFrame] = None
        df_1h: Optional[pd.DataFrame] = None
        liqs: list = []
        trades: list = []
        try:
            df_1m = await client.fetch_klines(symbol, "1m", limit=40)
        except Exception as e:
            logger.debug("1m klines %s: %s", symbol, e)
        try:
            df_1h = await client.fetch_klines(symbol, "1h", limit=30)
        except Exception as e:
            logger.debug("1h klines %s: %s", symbol, e)
        try:
            liqs = await client.fetch_liquidation_orders(symbol, limit=20)
        except Exception as e:
            logger.debug("liq %s: %s", symbol, e)
        try:
            trades = await client.fetch_agg_trades(symbol, limit=100)
        except Exception as e:
            logger.debug("trades %s: %s", symbol, e)
        return df_1m, df_1h, liqs, trades


async def build_attention_snapshot(
    client: ExchangeClient,
    *,
    cfg: Optional[AttentionConfig] = None,
    prev_oi: Optional[dict[str, float]] = None,
    radar_rows: Optional[list[dict[str, Any]]] = None,
    tema_symbols: Optional[set[str]] = None,
    sem: Optional[asyncio.Semaphore] = None,
) -> tuple[AttentionSnapshot, dict[str, float]]:
    """Fetch tickers, deep-scan top movers, rank by attention score."""
    cfg = cfg or AttentionConfig()
    cfg.validate()
    sem = sem or asyncio.Semaphore(8)
    prev_oi = prev_oi or {}
    radar_map = {
        str(r.get("symbol") or "").upper(): r
        for r in (radar_rows or [])
    }
    tema_symbols = tema_symbols or set()

    try:
        tickers = await client.fetch_market_tickers()
    except Exception as e:
        logger.warning("Attention: ticker fetch failed: %s", e)
        return (
            AttentionSnapshot(
                as_of=None,
                status="error",
                data_source=client.name,
                count=0,
                note=str(e),
            ),
            dict(prev_oi),
        )

    candidates = _rank_candidates(
        tickers,
        min_quote_volume=cfg.min_quote_volume,
        top_n=cfg.top_n,
    )
    deep_syms = {str(t["symbol"]).upper() for t in candidates[: cfg.deep_scan_n]}
    deep = [t for t in candidates if str(t["symbol"]).upper() in deep_syms]

    tasks = [_deep_fetch(client, t["symbol"], sem) for t in deep]
    deep_data = await asyncio.gather(*tasks, return_exceptions=True)
    deep_map = {
        str(t["symbol"]).upper(): pack
        for t, pack in zip(deep, deep_data)
        if not isinstance(pack, BaseException)
    }

    new_oi: dict[str, float] = dict(prev_oi)
    out_rows: list[AttentionRow] = []

    for ticker in candidates:
        sym = str(ticker["symbol"]).upper()
        pack = deep_map.get(sym)
        if pack is None:
            df_1m, df_1h, liqs, trades = None, None, [], []
        else:
            df_1m, df_1h, liqs, trades = pack
        oi_usd = ticker.get("open_interest_usd")
        oi_chg: Optional[float] = None
        if oi_usd is not None:
            try:
                oi_f = float(oi_usd)
                if sym in prev_oi and prev_oi[sym] > 0:
                    oi_chg = (oi_f - prev_oi[sym]) / prev_oi[sym] * 100.0
                new_oi[sym] = oi_f
            except (TypeError, ValueError):
                pass

        hits = run_detectors(
            ticker=ticker,
            oi_change_pct=oi_chg,
            df_1m=df_1m,
            df_1h=df_1h,
            liquidations=liqs,
            agg_trades=trades,
            cfg=cfg.micro,
        )
        score = _attention_score(hits)
        if score < 15 and not hits:
            continue

        rr = radar_map.get(sym) or {}
        out_rows.append(AttentionRow(
            symbol=sym,
            attention_score=score,
            pump_probability=_pump_probability(score, len(hits)),
            tags=[h.tag for h in hits],
            hits=[h.as_dict() for h in hits],
            quote_volume_24h=float(ticker.get("quote_volume_24h") or 0),
            price_change_pct_24h=float(ticker.get("price_change_pct_24h") or 0),
            funding_rate=float(ticker.get("funding_rate") or 0),
            open_interest_usd=float(oi_usd) if oi_usd is not None else None,
            oi_change_pct=round(oi_chg, 2) if oi_chg is not None else None,
            qmie_radar_color=rr.get("color"),
            qmie_tema="yes" if sym in tema_symbols else None,
        ))

    out_rows.sort(key=lambda r: -r.attention_score)

    snap = AttentionSnapshot(
        as_of=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        status="ready" if out_rows else "empty",
        data_source=client.name,
        count=len(out_rows),
        rows=[r.as_dict() for r in out_rows],
        note=None if out_rows else "no_symbols_above_threshold",
    )
    return snap, new_oi
