"""Tests for backtest.data_loader."""
from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backtest.data_loader import (
    _months_in_range,
    load_klines,
    resample_ohlcv,
)


# ── _months_in_range ────────────────────────────────────────────────────

def test_months_in_range_single_month():
    result = _months_in_range(date(2024, 3, 1), date(2024, 3, 31))
    assert result == [(2024, 3)]


def test_months_in_range_crosses_year():
    result = _months_in_range(date(2024, 11, 1), date(2025, 2, 1))
    assert result == [(2024, 11), (2024, 12), (2025, 1), (2025, 2)]


def test_months_in_range_same_start_end():
    result = _months_in_range(date(2024, 6, 15), date(2024, 6, 20))
    assert result == [(2024, 6)]


# ── resample_ohlcv ──────────────────────────────────────────────────────

def _make_1h_df(n: int = 48) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({
        "open": 100.0, "high": 101.0, "low": 99.0,
        "close": 100.5, "volume": 1000.0,
    }, index=idx)


def test_resample_to_4h_reduces_rows():
    df = _make_1h_df(48)
    result = resample_ohlcv(df, "4h")
    assert len(result) == 12


def test_resample_ohlcv_high_is_max():
    df = _make_1h_df(4)
    df["high"] = [101.0, 102.0, 103.0, 100.0]
    result = resample_ohlcv(df, "4h")
    assert result["high"].iloc[0] == 103.0


def test_resample_ohlcv_low_is_min():
    df = _make_1h_df(4)
    df["low"] = [99.0, 98.0, 97.0, 100.0]
    result = resample_ohlcv(df, "4h")
    assert result["low"].iloc[0] == 97.0


def test_resample_ohlcv_volume_is_sum():
    df = _make_1h_df(4)
    df["volume"] = 1000.0
    result = resample_ohlcv(df, "4h")
    assert result["volume"].iloc[0] == 4000.0


def test_resample_ohlcv_open_is_first():
    df = _make_1h_df(4)
    df["open"] = [10.0, 20.0, 30.0, 40.0]
    result = resample_ohlcv(df, "4h")
    assert result["open"].iloc[0] == 10.0


def test_resample_ohlcv_close_is_last():
    df = _make_1h_df(4)
    df["close"] = [10.0, 20.0, 30.0, 40.0]
    result = resample_ohlcv(df, "4h")
    assert result["close"].iloc[0] == 40.0


# ── load_klines (with mocked HTTP) ─────────────────────────────────────

def _make_zip_bytes(symbol: str, tf: str, year: int, month: int) -> bytes:
    """Create a minimal valid Binance klines ZIP in memory."""
    ts = int(pd.Timestamp(f"{year}-{month:02d}-01", tz="UTC").timestamp() * 1000)
    csv_content = f"{ts},100.0,101.0,99.0,100.5,1000.0,{ts+3599999},200000.0,10,500.0,100000.0,0\n"
    buf = io.BytesIO()
    fname = f"{symbol}-{tf}-{year:04d}-{month:02d}.csv"
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(fname, csv_content)
    return buf.getvalue()


def test_load_klines_returns_correct_schema(tmp_path):
    zip_bytes = _make_zip_bytes("BTCUSDT", "1h", 2024, 1)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = zip_bytes
    mock_resp.raise_for_status = MagicMock()
    with patch("backtest.data_loader.requests.get", return_value=mock_resp):
        df = load_klines("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31),
                         cache_dir=tmp_path)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is not None
    assert df.dtypes["close"] == "float64"
    # Index must not bleed past the requested end date
    assert df.index.max() < pd.Timestamp("2024-02-01", tz="UTC")


def test_load_klines_caches_to_disk(tmp_path):
    zip_bytes = _make_zip_bytes("BTCUSDT", "1h", 2024, 1)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = zip_bytes
    mock_resp.raise_for_status = MagicMock()
    with patch("backtest.data_loader.requests.get", return_value=mock_resp) as mock_get:
        load_klines("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31), cache_dir=tmp_path)
        load_klines("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31), cache_dir=tmp_path)
    assert mock_get.call_count == 1


def test_load_klines_404_returns_empty(tmp_path):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch("backtest.data_loader.requests.get", return_value=mock_resp):
        df = load_klines("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31),
                         cache_dir=tmp_path)
    assert df.empty
