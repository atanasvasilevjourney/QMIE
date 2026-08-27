"""Load USDT-M Vision klines. Same archive as ``python -m backtest.run``."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from backtest.data_loader import load_klines, load_tf_ohlcv

from .protocol import SPLIT

CORE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT", "LINKUSDT"]
SATELLITES = ["SOLUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT"]  # later listings
DEFAULT_UNIVERSE = CORE + SATELLITES


def load_symbol(
    symbol: str,
    tf: str,
    *,
    start: date | None = None,
    end: date | None = None,
    cache_dir: Path | None = None,
) -> tuple[pd.DataFrame, str]:
    start = start or SPLIT.is_start
    end = end or SPLIT.oos_end
    kw: dict = {}
    if cache_dir is not None:
        kw["cache_dir"] = cache_dir
    df, src = load_tf_ohlcv(symbol, tf, start, end, **kw)
    return df, src


def load_panel(
    symbols: Iterable[str],
    tf: str = "1d",
    *,
    start: date | None = None,
    end: date | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Close panel, columns = symbols. Sources recorded per name."""
    closes: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    for sym in symbols:
        df, src = load_symbol(sym, tf, start=start, end=end)
        sources[sym] = src
        if df.empty:
            continue
        closes[sym] = df["close"].rename(sym)
    if not closes:
        return pd.DataFrame(), sources
    panel = pd.concat(closes.values(), axis=1).sort_index()
    return panel, sources


def coverage_table(symbols: Iterable[str], timeframes: Iterable[str] = ("1d", "4h")) -> pd.DataFrame:
    rows = []
    for sym in symbols:
        for tf in timeframes:
            df, src = load_symbol(sym, tf)
            rows.append({
                "symbol": sym,
                "tf": tf,
                "source": src,
                "bars": int(len(df)),
                "start": None if df.empty else str(df.index[0].date()),
                "end": None if df.empty else str(df.index[-1].date()),
            })
    return pd.DataFrame(rows)
