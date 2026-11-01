"""Binance Vision OHLCV source (default backtest path)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from backtest.data_loader import load_klines, resample_ohlcv

from .protocol import DataSource, OhlcvFrame


class VisionDataSource(DataSource):
    def __init__(self, cache_dir: Path | str | None = None) -> None:
        self._cache = Path(cache_dir) if cache_dir else None

    def load(
        self,
        symbol: str,
        timeframe: str,
        start: date,
        end: date,
    ) -> OhlcvFrame:
        kw = {}
        if self._cache is not None:
            kw["cache_dir"] = self._cache
        tf = timeframe.lower()
        df = load_klines(symbol, tf, start, end, **kw)
        return OhlcvFrame(symbol=symbol, timeframe=tf, df=df, source="vision")


def load_15m_with_1h(
    symbol: str,
    start: date,
    end: date,
    *,
    cache_dir: Path | str | None = None,
) -> tuple[OhlcvFrame, pd.DataFrame]:
    """Load native 15m and build 1h via resample (single source of truth)."""
    src = VisionDataSource(cache_dir=cache_dir)
    m15 = src.load(symbol, "15m", start, end)
    h1 = resample_ohlcv(m15.df, "1h")
    return m15, h1
