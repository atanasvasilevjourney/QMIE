"""
QMIE Backtest — Historical Kline Loader
========================================
Downloads monthly OHLCV ZIP files from Binance's public archive:
  https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/{TF}/{SYMBOL}-{TF}-{YYYY-MM}.zip

Caches each month as a local parquet file. Re-runs skip already-cached months.
Returns a DataFrame matching exchange_clients.py schema:
  columns: open, high, low, close, volume  (float64)
  index:   pd.DatetimeIndex (UTC)
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"
_DEFAULT_CACHE = Path(__file__).parent / "data" / "cache"

_COLS = {0: "open_time", 1: "open", 2: "high", 3: "low", 4: "close", 5: "volume"}


def _months_in_range(start: date, end: date) -> list[tuple[int, int]]:
    """Return (year, month) tuples covering start..end inclusive."""
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


def _cache_path(cache_dir: Path, symbol: str, tf: str, year: int, month: int) -> Path:
    return cache_dir / symbol / tf / f"{year:04d}-{month:02d}.parquet"


def _download_month(symbol: str, tf: str, year: int, month: int) -> pd.DataFrame | None:
    """Download and parse one monthly ZIP. Returns None on 404."""
    fname = f"{symbol}-{tf}-{year:04d}-{month:02d}.zip"
    url = f"{_BASE_URL}/{symbol}/{tf}/{fname}"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 404:
            logger.debug("No data for %s %s %04d-%02d", symbol, tf, year, month)
            return None
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Download failed %s: %s", url, e)
        return None

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        if not zf.namelist():
            return None
        csv_name = zf.namelist()[0]
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, header=None, usecols=list(_COLS.keys()))

    df.columns = list(_COLS.values())
    # Newer Binance files include a header row — drop it if present
    if isinstance(df.iloc[0, 0], str):
        df = df.iloc[1:].reset_index(drop=True)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    df.index.name = None
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype("float64")
    return df[["open", "high", "low", "close", "volume"]]


def load_klines(
    symbol: str,
    tf: str,
    start: date,
    end: date,
    cache_dir: Path = _DEFAULT_CACHE,
) -> pd.DataFrame:
    """
    Load OHLCV klines for symbol/tf over start..end using local cache.
    Returns DataFrame with open/high/low/close/volume columns, UTC DatetimeIndex.
    """
    today = date.today()
    frames: list[pd.DataFrame] = []

    for year, month in _months_in_range(start, end):
        is_current = (year == today.year and month == today.month)
        path = _cache_path(cache_dir, symbol, tf, year, month)

        if not is_current and path.exists():
            frames.append(pd.read_parquet(path))
            continue

        df = _download_month(symbol, tf, year, month)
        if df is None:
            continue

        if not is_current:
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path)
            logger.info("Cached %s", path)

        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    result = pd.concat(frames)
    result = result[~result.index.duplicated(keep="first")].sort_index()
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    return result.loc[start_ts:end_ts]


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Resample OHLCV DataFrame to a lower frequency.
    rule: pandas offset alias e.g. '4h', '1D'
    """
    return df.resample(rule, label="left", closed="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
