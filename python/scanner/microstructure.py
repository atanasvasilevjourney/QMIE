"""
QMIE — Microstructure detectors (read-only overlay)
=================================================
StrikeChart-style derivatives + volume anomaly math for altcoin attention.
Does **not** place orders. Does **not** retune W_* or TEMA scoring.

Detectors (each returns 0–1 sub-score + optional tag):
  * volume_velocity — robust z of 1m volume rate vs trailing window
  * vol_turnover    — 24h quote vol / OI USD (liquidity churn proxy)
  * oi_influx       — OI up while price up (leverage fuel)
  * funding_squeeze — negative funding + rising price (short squeeze setup)
  * liquidation_burst — recent liq notional vs rolling baseline
  * whale_prints    — large aggTrade notional in scan window
  * volatility      — ATR% expansion on 1h
  * range_breakout  — Donchian break on 1h (coil-style)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional

import numpy as np
import pandas as pd

from .indicators import atr

Tag = Literal[
    "vol_velocity",
    "vol_turnover",
    "oi_influx",
    "funding_squeeze",
    "liquidations",
    "whale_print",
    "volatility",
    "range_breakout",
]


@dataclass
class MicrostructureConfig:
    vol_velocity_z: float = 4.0
    vol_velocity_window: int = 30          # 1m bars ≈ 30 minutes
    vol_turnover_threshold: float = 2.0    # 24h vol / OI USD
    oi_influx_min_pct: float = 5.0
    price_up_min_pct: float = 1.0
    funding_squeeze_max: float = -0.00005  # negative predicted/last funding
    liq_burst_min_usd: float = 250_000.0
    whale_min_usd: float = 100_000.0
    atr_expand_min_pct: float = 3.0
    range_lookback: int = 20
    range_max_width_pct: float = 15.0

    def validate(self) -> None:
        if self.vol_velocity_z <= 0:
            raise ValueError("vol_velocity_z must be > 0")
        if self.vol_velocity_window < 10:
            raise ValueError("vol_velocity_window must be >= 10")


@dataclass
class DetectorHit:
    tag: Tag
    score: float
    detail: str
    value: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _robust_z(series: pd.Series) -> Optional[float]:
    """Median/MAD z-score of the last point vs the rest."""
    if series is None or len(series) < 5:
        return None
    hist = series.iloc[:-1].dropna()
    last = float(series.iloc[-1])
    if hist.empty or not np.isfinite(last):
        return None
    med = float(hist.median())
    mad = float((hist - med).abs().median())
    if mad <= 1e-12:
        return 0.0 if last == med else 10.0
    return (last - med) / (1.4826 * mad)


def volume_velocity_score(
    df_1m: pd.DataFrame,
    *,
    window: int = 30,
    z_threshold: float = 4.0,
) -> Optional[DetectorHit]:
    """Rate-of-change of volume: z-score of last bar vs trailing window."""
    if df_1m is None or len(df_1m) < window + 2:
        return None
    vol = pd.to_numeric(df_1m["volume"], errors="coerce").dropna()
    if len(vol) < window + 2:
        return None
    tail = vol.iloc[-(window + 1):]
    z = _robust_z(tail)
    if z is None:
        return None
    score = min(1.0, max(0.0, z / z_threshold))
    if z < z_threshold * 0.5:
        return None
    return DetectorHit(
        "vol_velocity",
        round(score, 3),
        f"1m vol z={z:.1f} (>{z_threshold} = pump-like)",
        round(z, 2),
    )


def vol_turnover_score(
    quote_volume_24h: float,
    open_interest_usd: Optional[float],
    *,
    threshold: float = 2.0,
) -> Optional[DetectorHit]:
    """24h quote volume / OI USD — churn proxy when mcap is unavailable."""
    if open_interest_usd is None or open_interest_usd <= 0:
        return None
    if quote_volume_24h <= 0:
        return None
    ratio = quote_volume_24h / open_interest_usd
    if ratio < threshold:
        return None
    score = min(1.0, ratio / (threshold * 2))
    return DetectorHit(
        "vol_turnover",
        round(score, 3),
        f"vol/OI={ratio:.2f} (≥{threshold})",
        round(ratio, 3),
    )


def oi_influx_score(
    price_change_pct_24h: float,
    oi_change_pct: Optional[float],
    *,
    min_oi_pct: float = 5.0,
    min_price_pct: float = 1.0,
) -> Optional[DetectorHit]:
    """Price up + OI up → aggressive long positioning."""
    if oi_change_pct is None:
        return None
    if price_change_pct_24h < min_price_pct or oi_change_pct < min_oi_pct:
        return None
    score = min(1.0, (oi_change_pct / min_oi_pct) * 0.5 + 0.5)
    return DetectorHit(
        "oi_influx",
        round(score, 3),
        f"price +{price_change_pct_24h:.1f}% OI +{oi_change_pct:.1f}%",
        round(oi_change_pct, 2),
    )


def funding_squeeze_score(
    funding_rate: float,
    price_change_pct_24h: float,
    *,
    max_funding: float = -0.00005,
    min_price_pct: float = 1.0,
) -> Optional[DetectorHit]:
    """Negative funding while spot/perp price rises → short squeeze fuel."""
    if funding_rate > max_funding or price_change_pct_24h < min_price_pct:
        return None
    score = min(1.0, abs(funding_rate) / 0.001 + price_change_pct_24h / 10.0)
    score = min(1.0, score * 0.5)
    return DetectorHit(
        "funding_squeeze",
        round(score, 3),
        f"funding {funding_rate:.5f} price +{price_change_pct_24h:.1f}%",
        round(funding_rate, 6),
    )


def liquidation_burst_score(
    orders: list[dict[str, Any]],
    *,
    min_notional: float = 250_000.0,
) -> Optional[DetectorHit]:
    """Sum recent liquidation notional."""
    if not orders:
        return None
    total = sum(float(o.get("notional_usd") or 0) for o in orders)
    if total < min_notional:
        return None
    score = min(1.0, total / (min_notional * 4))
    return DetectorHit(
        "liquidations",
        round(score, 3),
        f"liq ${total:,.0f} (≥${min_notional:,.0f})",
        round(total, 0),
    )


def whale_print_score(
    trades: list[dict[str, Any]],
    *,
    min_usd: float = 100_000.0,
) -> Optional[DetectorHit]:
    """Largest single print in recent aggTrades."""
    if not trades:
        return None
    best = max(float(t.get("notional_usd") or 0) for t in trades)
    if best < min_usd:
        return None
    score = min(1.0, best / (min_usd * 3))
    return DetectorHit(
        "whale_print",
        round(score, 3),
        f"max print ${best:,.0f}",
        round(best, 0),
    )


def volatility_expand_score(
    df_1h: pd.DataFrame,
    *,
    min_atr_pct: float = 3.0,
) -> Optional[DetectorHit]:
    """ATR% on last closed 1h bar vs recent median."""
    if df_1h is None or len(df_1h) < 20:
        return None
    a = atr(df_1h, 14)
    close = df_1h["close"]
    pct = (a / close.replace(0, np.nan)) * 100.0
    pct = pct.dropna()
    if len(pct) < 10:
        return None
    last = float(pct.iloc[-1])
    med = float(pct.iloc[-20:-1].median())
    if last < min_atr_pct or last < med * 1.3:
        return None
    score = min(1.0, last / (min_atr_pct * 2))
    return DetectorHit(
        "volatility",
        round(score, 3),
        f"ATR% {last:.2f} (med {med:.2f})",
        round(last, 2),
    )


def range_breakout_score(
    df_1h: pd.DataFrame,
    *,
    lookback: int = 20,
    max_width_pct: float = 15.0,
) -> Optional[DetectorHit]:
    """Prior N-bar Donchian break (1h), coil-style."""
    if df_1h is None or len(df_1h) < lookback + 2:
        return None
    prior = df_1h.iloc[-(lookback + 1):-1]
    hi = float(prior["high"].max())
    lo = float(prior["low"].min())
    if lo <= 0:
        return None
    width = (hi - lo) / lo * 100.0
    close = float(df_1h["close"].iloc[-1])
    if width > max_width_pct:
        return None
    if close > hi:
        excess = (close - hi) / hi * 100.0
        score = min(1.0, 0.5 + excess / 10.0)
        return DetectorHit(
            "range_breakout",
            round(score, 3),
            f"1h UP break @{hi:.4g} width {width:.1f}%",
            round(excess, 2),
        )
    if close < lo:
        excess = (lo - close) / lo * 100.0
        score = min(1.0, 0.5 + excess / 10.0)
        return DetectorHit(
            "range_breakout",
            round(score, 3),
            f"1h DOWN break @{lo:.4g} width {width:.1f}%",
            round(excess, 2),
        )
    return None


def run_detectors(
    *,
    ticker: dict[str, Any],
    oi_change_pct: Optional[float],
    df_1m: Optional[pd.DataFrame],
    df_1h: Optional[pd.DataFrame],
    liquidations: list[dict[str, Any]],
    agg_trades: list[dict[str, Any]],
    cfg: Optional[MicrostructureConfig] = None,
) -> list[DetectorHit]:
    """Run all detectors for one symbol. Pure function — no I/O."""
    cfg = cfg or MicrostructureConfig()
    hits: list[DetectorHit] = []

    if df_1m is not None:
        h = volume_velocity_score(
            df_1m,
            window=cfg.vol_velocity_window,
            z_threshold=cfg.vol_velocity_z,
        )
        if h:
            hits.append(h)

    h = vol_turnover_score(
        float(ticker.get("quote_volume_24h") or 0),
        ticker.get("open_interest_usd"),
        threshold=cfg.vol_turnover_threshold,
    )
    if h:
        hits.append(h)

    h = oi_influx_score(
        float(ticker.get("price_change_pct_24h") or 0),
        oi_change_pct,
        min_oi_pct=cfg.oi_influx_min_pct,
        min_price_pct=cfg.price_up_min_pct,
    )
    if h:
        hits.append(h)

    h = funding_squeeze_score(
        float(ticker.get("funding_rate") or 0),
        float(ticker.get("price_change_pct_24h") or 0),
        max_funding=cfg.funding_squeeze_max,
        min_price_pct=cfg.price_up_min_pct,
    )
    if h:
        hits.append(h)

    h = liquidation_burst_score(liquidations, min_notional=cfg.liq_burst_min_usd)
    if h:
        hits.append(h)

    h = whale_print_score(agg_trades, min_usd=cfg.whale_min_usd)
    if h:
        hits.append(h)

    if df_1h is not None:
        h = volatility_expand_score(df_1h, min_atr_pct=cfg.atr_expand_min_pct)
        if h:
            hits.append(h)
        h = range_breakout_score(
            df_1h,
            lookback=cfg.range_lookback,
            max_width_pct=cfg.range_max_width_pct,
        )
        if h:
            hits.append(h)

    return hits
