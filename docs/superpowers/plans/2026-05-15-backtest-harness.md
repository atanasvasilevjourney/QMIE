# Backtest Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI backtest runner + Streamlit dashboard that measures QMIE's signal hit rate (TP before SL) by grade on 2 years of historical USDT-M futures data from data.binance.vision.

**Architecture:** `data_loader.py` downloads/caches monthly ZIPs from Binance's public archive. `runner.py` walks bars through `compute_signal` and evaluates outcomes. `run.py` is the CLI entry point that saves results to parquet. `app.py` is a Streamlit dashboard that reads the parquet.

**Tech Stack:** Python 3.12, pandas, requests, streamlit, pyarrow (parquet), pytest

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `python/backtest/__init__.py` | Create | Package marker |
| `python/backtest/data_loader.py` | Create | Download + cache monthly ZIPs, resample OHLCV |
| `python/backtest/runner.py` | Create | Bar walk + compute_signal + WIN/LOSS/OPEN evaluation |
| `python/backtest/run.py` | Create | CLI entry point, saves parquet |
| `python/backtest/app.py` | Create | Streamlit dashboard |
| `python/backtest/requirements.txt` | Create | Backtest-only deps (streamlit, pyarrow) |
| `python/tests/backtest/__init__.py` | Create | Package marker |
| `python/tests/backtest/test_data_loader.py` | Create | Unit tests for data_loader |
| `python/tests/backtest/test_runner.py` | Create | Unit tests for runner outcome logic |

---

## Task 1: Package scaffold + `data_loader.py`

**Files:**
- Create: `python/backtest/__init__.py`
- Create: `python/backtest/data_loader.py`
- Create: `python/tests/backtest/__init__.py`
- Create: `python/tests/backtest/test_data_loader.py`
- Create: `python/backtest/requirements.txt`

- [ ] **Step 1: Create package markers and requirements**

Create `python/backtest/__init__.py` (empty file):
```python
```

Create `python/tests/backtest/__init__.py` (empty file):
```python
```

Create `python/backtest/requirements.txt`:
```
streamlit==1.35.0
pyarrow==16.1.0
requests==2.32.3
```

- [ ] **Step 2: Write failing tests for `data_loader.py`**

Create `python/tests/backtest/test_data_loader.py`:

```python
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
    df = _make_1h_df(48)   # 48 hours = 12 × 4H bars
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
    # Binance CSV: open_time_ms, open, high, low, close, volume, close_time_ms, ...
    ts = int(pd.Timestamp(f"{year}-{month:02d}-01", tz="UTC").timestamp() * 1000)
    csv_content = f"{ts},100.0,101.0,99.0,100.5,1000.0,{ts+3599999},200000.0,10,500.0,100000.0,0\n"
    buf = io.BytesIO()
    fname = f"{symbol}-{tf}-{year:04d}-{month:02d}.csv"
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(fname, csv_content)
    return buf.getvalue()


def test_load_klines_returns_correct_schema(tmp_path):
    """load_klines returns DataFrame with correct columns and UTC index."""
    zip_bytes = _make_zip_bytes("BTCUSDT", "1h", 2024, 1)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = zip_bytes
    mock_resp.raise_for_status = MagicMock()

    with patch("backtest.data_loader.requests.get", return_value=mock_resp):
        df = load_klines("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31),
                         cache_dir=tmp_path)

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is not None  # UTC-aware
    assert df.dtypes["close"] == "float64"


def test_load_klines_caches_to_disk(tmp_path):
    """Second call for same month skips HTTP."""
    zip_bytes = _make_zip_bytes("BTCUSDT", "1h", 2024, 1)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = zip_bytes
    mock_resp.raise_for_status = MagicMock()

    with patch("backtest.data_loader.requests.get", return_value=mock_resp) as mock_get:
        load_klines("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31), cache_dir=tmp_path)
        load_klines("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31), cache_dir=tmp_path)

    assert mock_get.call_count == 1  # second call hit cache


def test_load_klines_404_returns_empty(tmp_path):
    """404 for a month returns empty DataFrame without raising."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch("backtest.data_loader.requests.get", return_value=mock_resp):
        df = load_klines("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31),
                         cache_dir=tmp_path)

    assert df.empty
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd python
pytest tests/backtest/test_data_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'backtest'` or similar import failures.

- [ ] **Step 4: Implement `data_loader.py`**

Create `python/backtest/data_loader.py`:

```python
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

# Binance CSV column positions
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
        csv_name = zf.namelist()[0]
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, header=None, usecols=list(_COLS.keys()))

    df.columns = list(_COLS.values())
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
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd python
pytest tests/backtest/test_data_loader.py -v
```

Expected: all 13 tests PASSED.

- [ ] **Step 6: Run full suite to check for regressions**

```bash
cd python
pytest -v
```

Expected: 118 existing + 13 new = 131 PASSED, 0 failed.

- [ ] **Step 7: Commit**

```bash
cd python/..
git add python/backtest/__init__.py python/backtest/data_loader.py python/backtest/requirements.txt python/tests/backtest/__init__.py python/tests/backtest/test_data_loader.py
git commit -m "feat: add backtest data_loader with Binance public archive download + cache"
```

---

## Task 2: `runner.py` — bar walk + outcome evaluation

**Files:**
- Create: `python/backtest/runner.py`
- Create: `python/tests/backtest/test_runner.py`

- [ ] **Step 1: Write failing tests for `runner.py`**

Create `python/tests/backtest/test_runner.py`:

```python
"""Tests for backtest.runner outcome evaluation."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backtest.runner import _evaluate_outcome, run_backtest, results_to_dataframe


def _make_flat_df(n: int, price: float = 100.0, freq: str = "1h") -> pd.DataFrame:
    """Flat OHLCV: all bars same price, high+0.5, low-0.5."""
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({
        "open": price, "high": price + 0.5, "low": price - 0.5,
        "close": price, "volume": 1000.0,
    }, index=idx)


# ── _evaluate_outcome ────────────────────────────────────────────────────

class TestEvaluateOutcome:
    def test_buy_win_when_high_hits_tp_first(self):
        df = _make_flat_df(20)
        # Bar 5: high = 110 (above TP=105), low = 99 (above SL=95)
        df.iloc[5, df.columns.get_loc("high")] = 110.0
        outcome, bars = _evaluate_outcome(df, signal_idx=0, side="BUY",
                                          take_profit=105.0, stop_loss=95.0)
        assert outcome == "WIN"
        assert bars == 5

    def test_buy_loss_when_low_hits_sl_first(self):
        df = _make_flat_df(20)
        # Bar 3: low = 90 (below SL=95), high = 100.5 (below TP=105)
        df.iloc[3, df.columns.get_loc("low")] = 90.0
        outcome, bars = _evaluate_outcome(df, signal_idx=0, side="BUY",
                                          take_profit=105.0, stop_loss=95.0)
        assert outcome == "LOSS"
        assert bars == 3

    def test_buy_open_when_neither_hit(self):
        df = _make_flat_df(20)
        # flat bars — high never reaches 200, low never drops below 1
        outcome, bars = _evaluate_outcome(df, signal_idx=0, side="BUY",
                                          take_profit=200.0, stop_loss=1.0,
                                          max_lookahead=10)
        assert outcome == "OPEN"
        assert bars is None

    def test_sell_win_when_low_hits_tp_first(self):
        df = _make_flat_df(20)
        # Bar 4: low = 85 (below TP=90 for SELL), high = 100.5 (below SL=110)
        df.iloc[4, df.columns.get_loc("low")] = 85.0
        outcome, bars = _evaluate_outcome(df, signal_idx=0, side="SELL",
                                          take_profit=90.0, stop_loss=110.0)
        assert outcome == "WIN"
        assert bars == 4

    def test_sell_loss_when_high_hits_sl_first(self):
        df = _make_flat_df(20)
        # Bar 2: high = 115 (above SL=110 for SELL), low = 99.5 (above TP=90)
        df.iloc[2, df.columns.get_loc("high")] = 115.0
        outcome, bars = _evaluate_outcome(df, signal_idx=0, side="SELL",
                                          take_profit=90.0, stop_loss=110.0)
        assert outcome == "LOSS"
        assert bars == 2

    def test_both_hit_same_bar_is_loss(self):
        df = _make_flat_df(20)
        # Bar 1: both TP and SL touched — conservative = LOSS
        df.iloc[1, df.columns.get_loc("high")] = 200.0
        df.iloc[1, df.columns.get_loc("low")] = 1.0
        outcome, bars = _evaluate_outcome(df, signal_idx=0, side="BUY",
                                          take_profit=150.0, stop_loss=50.0)
        assert outcome == "LOSS"
        assert bars == 1

    def test_respects_max_lookahead(self):
        df = _make_flat_df(200)
        outcome, bars = _evaluate_outcome(df, signal_idx=0, side="BUY",
                                          take_profit=200.0, stop_loss=1.0,
                                          max_lookahead=5)
        assert outcome == "OPEN"
        assert bars is None

    def test_signal_at_end_of_df_returns_open(self):
        df = _make_flat_df(5)
        # signal_idx=4 is the last bar — no forward bars
        outcome, bars = _evaluate_outcome(df, signal_idx=4, side="BUY",
                                          take_profit=200.0, stop_loss=1.0)
        assert outcome == "OPEN"
        assert bars is None


# ── results_to_dataframe ─────────────────────────────────────────────────

def test_results_to_dataframe_empty():
    df = results_to_dataframe([])
    assert isinstance(df, pd.DataFrame)
    assert "outcome" in df.columns
    assert len(df) == 0


def test_results_to_dataframe_schema():
    from backtest.runner import BacktestResult
    r = BacktestResult(
        symbol="BTCUSDT", timeframe="1h",
        timestamp=pd.Timestamp("2024-01-01", tz="UTC"),
        side="BUY", grade="A", score=85.0, daily_trend="bullish",
        entry=100.0, stop_loss=95.0, take_profit=110.0, atr_pct=1.5,
        outcome="WIN", bars_to_outcome=3,
    )
    df = results_to_dataframe([r])
    assert len(df) == 1
    assert df["outcome"].iloc[0] == "WIN"
    assert df["bars_to_outcome"].iloc[0] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd python
pytest tests/backtest/test_runner.py -v
```

Expected: `ModuleNotFoundError: No module named 'backtest.runner'`

- [ ] **Step 3: Implement `runner.py`**

Create `python/backtest/runner.py`:

```python
"""
QMIE Backtest — Signal Runner & Outcome Evaluator
===================================================
Walks historical bars through compute_signal, records every non-REJECT
signal, then evaluates each against subsequent bars to find WIN/LOSS/OPEN.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from scanner.signal_engine import ScanResult, compute_signal

logger = logging.getLogger(__name__)

WARMUP_BARS = 300
MAX_LOOKAHEAD = 100


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    timestamp: pd.Timestamp
    side: str
    grade: str
    score: float
    daily_trend: str
    entry: float
    stop_loss: float
    take_profit: float
    atr_pct: float
    outcome: str              # WIN / LOSS / OPEN
    bars_to_outcome: Optional[int]


def _evaluate_outcome(
    df: pd.DataFrame,
    signal_idx: int,
    side: str,
    take_profit: float,
    stop_loss: float,
    max_lookahead: int = MAX_LOOKAHEAD,
) -> tuple[str, Optional[int]]:
    """Scan forward from signal_idx to find first TP or SL touch."""
    for offset in range(1, max_lookahead + 1):
        i = signal_idx + offset
        if i >= len(df):
            break
        bar_high = df["high"].iloc[i]
        bar_low = df["low"].iloc[i]

        if side == "BUY":
            tp_hit = bar_high >= take_profit
            sl_hit = bar_low <= stop_loss
        else:  # SELL
            tp_hit = bar_low <= take_profit
            sl_hit = bar_high >= stop_loss

        if tp_hit and sl_hit:
            return "LOSS", offset   # conservative: gap-through both = LOSS
        if tp_hit:
            return "WIN", offset
        if sl_hit:
            return "LOSS", offset

    return "OPEN", None


def run_backtest(
    symbol: str,
    tf: str,
    df_base: pd.DataFrame,
    htf_rule: str,
    daily_rule: str = "1D",
) -> list[BacktestResult]:
    """
    Walk df_base bar-by-bar from WARMUP_BARS onward.
    Calls compute_signal on each bar, evaluates outcome for non-REJECT signals.

    htf_rule: pandas resample rule for HTF df (e.g. '4h' when tf='1h')
    daily_rule: pandas resample rule for daily trend (always '1D')
    """
    from .data_loader import resample_ohlcv

    df_htf = resample_ohlcv(df_base, htf_rule)
    df_daily = resample_ohlcv(df_base, daily_rule)

    results: list[BacktestResult] = []
    n = len(df_base)

    for i in range(WARMUP_BARS, n):
        bar_ts = df_base.index[i]
        slice_base = df_base.iloc[: i + 1]
        slice_htf = df_htf.loc[:bar_ts]
        slice_daily = df_daily.loc[:bar_ts]

        sig: Optional[ScanResult] = compute_signal(
            slice_base,
            symbol=symbol,
            timeframe=tf,
            htf_df=slice_htf if len(slice_htf) >= 10 else None,
            daily_df=slice_daily if len(slice_daily) >= 200 else None,
        )

        if sig is None or sig.grade == "REJECT" or sig.side == "NEUTRAL":
            continue

        outcome, bars_to = _evaluate_outcome(
            df_base, i, sig.side, sig.take_profit, sig.stop_loss
        )

        results.append(BacktestResult(
            symbol=symbol,
            timeframe=tf,
            timestamp=sig.timestamp,
            side=sig.side,
            grade=sig.grade,
            score=sig.score,
            daily_trend=sig.daily_trend,
            entry=sig.price,
            stop_loss=sig.stop_loss,
            take_profit=sig.take_profit,
            atr_pct=sig.atr_pct,
            outcome=outcome,
            bars_to_outcome=bars_to,
        ))

    return results


def results_to_dataframe(results: list[BacktestResult]) -> pd.DataFrame:
    """Convert list of BacktestResult to a DataFrame."""
    if not results:
        return pd.DataFrame(columns=[
            "symbol", "timeframe", "timestamp", "side", "grade", "score",
            "daily_trend", "entry", "stop_loss", "take_profit", "atr_pct",
            "outcome", "bars_to_outcome",
        ])
    return pd.DataFrame([vars(r) for r in results])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd python
pytest tests/backtest/test_runner.py -v
```

Expected: all 11 tests PASSED.

- [ ] **Step 5: Run full suite to check for regressions**

```bash
cd python
pytest -v
```

Expected: 131 + 11 = 142 PASSED, 0 failed.

- [ ] **Step 6: Commit**

```bash
cd python/..
git add python/backtest/runner.py python/tests/backtest/test_runner.py
git commit -m "feat: add backtest runner with WIN/LOSS/OPEN outcome evaluation"
```

---

## Task 3: `run.py` — CLI entry point

**Files:**
- Create: `python/backtest/run.py`

- [ ] **Step 1: Create `run.py`**

Create `python/backtest/run.py`:

```python
"""
QMIE Backtest CLI
=================
Usage:
    cd python
    python -m backtest.run --symbols BTCUSDT ETHUSDT --tf 1h 4h --start 2023-01-01
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .data_loader import load_klines
from .runner import run_backtest, results_to_dataframe

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# HTF map: base TF → pandas resample rule for HTF
_HTF_MAP = {"1h": "4h", "4h": "1D", "1d": "1W"}

_DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="QMIE Backtest Runner")
    p.add_argument("--symbols", nargs="+", default=_DEFAULT_SYMBOLS,
                   help="Symbols to backtest")
    p.add_argument("--tf", nargs="+", default=["1h", "4h"],
                   help="Timeframes")
    p.add_argument("--start", default=str(date.today() - timedelta(days=730)),
                   help="Start date YYYY-MM-DD (default: 2 years ago)")
    p.add_argument("--end", default=str(date.today() - timedelta(days=1)),
                   help="End date YYYY-MM-DD (default: yesterday)")
    p.add_argument("--out", default=str(Path(__file__).parent / "results"),
                   help="Output directory for parquet files")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_results = []
    combos = [(s, tf) for s in args.symbols for tf in args.tf]
    print(f"Running {len(combos)} symbol/tf combinations ({start} → {end})\n")

    for symbol, tf in combos:
        print(f"  {symbol} {tf} ...", end=" ", flush=True)
        htf_rule = _HTF_MAP.get(tf, "1D")
        df = load_klines(symbol, tf, start, end)
        if len(df) < 350:
            print(f"skipped (only {len(df)} bars)")
            continue
        results = run_backtest(symbol, tf, df, htf_rule=htf_rule)
        all_results.extend(results)
        print(f"{len(results)} signals")

    df_out = results_to_dataframe(all_results)

    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    stamped = out_dir / f"backtest_{ts}.parquet"
    latest = out_dir / "latest.parquet"
    df_out.to_parquet(stamped, index=False)
    df_out.to_parquet(latest, index=False)

    # Print summary table
    print(f"\nTotal signals: {len(df_out)}")
    if len(df_out):
        closed = df_out[df_out["outcome"] != "OPEN"]
        if len(closed):
            grade_order = ["A+", "A", "B", "C"]
            rows = []
            for g in grade_order:
                g_df = closed[closed["grade"] == g]
                if len(g_df) == 0:
                    continue
                rows.append({
                    "Grade": g,
                    "Signals": len(df_out[df_out["grade"] == g]),
                    "Closed": len(g_df),
                    "Win %": f"{100 * (g_df['outcome'] == 'WIN').mean():.1f}%",
                    "Avg bars": f"{g_df['bars_to_outcome'].mean():.1f}",
                })
            summary = pd.DataFrame(rows).set_index("Grade")
            print("\n" + summary.to_string())

    print(f"\nSaved → {latest}")
    print(f"        {stamped}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify CLI runs without error on a smoke test**

```bash
cd python
python -m backtest.run --help
```

Expected: argparse help output printed, no traceback.

- [ ] **Step 3: Run full suite to confirm no regressions**

```bash
cd python
pytest -v
```

Expected: 142 PASSED, 0 failed.

- [ ] **Step 4: Commit**

```bash
cd python/..
git add python/backtest/run.py
git commit -m "feat: add backtest CLI runner — saves results to parquet"
```

---

## Task 4: `app.py` — Streamlit dashboard

**Files:**
- Create: `python/backtest/app.py`

- [ ] **Step 1: Install streamlit**

```bash
cd python
pip install streamlit==1.35.0 pyarrow==16.1.0
```

- [ ] **Step 2: Create `app.py`**

Create `python/backtest/app.py`:

```python
"""
QMIE Backtest Dashboard
========================
Streamlit dashboard for exploring backtest results.

Launch:
    cd python
    streamlit run backtest/app.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

_RESULTS_DIR = Path(__file__).parent / "results"
_GRADE_ORDER = ["A+", "A", "B", "C"]


@st.cache_data
def load_results(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def main():
    st.set_page_config(page_title="QMIE Backtest", layout="wide")
    st.title("QMIE Backtest Dashboard")

    # ── File picker ──────────────────────────────────────────────────
    if not _RESULTS_DIR.exists() or not list(_RESULTS_DIR.glob("*.parquet")):
        st.warning("No results found. Run: `python -m backtest.run` first.")
        return

    parquet_files = sorted(_RESULTS_DIR.glob("*.parquet"), reverse=True)
    file_options = {p.name: str(p) for p in parquet_files}
    chosen = st.sidebar.selectbox("Results file", list(file_options.keys()))
    df = load_results(file_options[chosen])

    # ── Sidebar filters ──────────────────────────────────────────────
    st.sidebar.header("Filters")

    symbols = st.sidebar.multiselect(
        "Symbol", sorted(df["symbol"].unique()),
        default=sorted(df["symbol"].unique()),
    )
    tfs = st.sidebar.multiselect(
        "Timeframe", sorted(df["timeframe"].unique()),
        default=sorted(df["timeframe"].unique()),
    )
    grades = st.sidebar.multiselect("Grade", _GRADE_ORDER, default=_GRADE_ORDER)
    side = st.sidebar.radio("Side", ["Both", "BUY", "SELL"])
    trend = st.sidebar.selectbox(
        "Daily Trend", ["All", "bullish", "bearish", "unknown"]
    )

    min_d = df["timestamp"].dt.date.min()
    max_d = df["timestamp"].dt.date.max()
    date_range = st.sidebar.date_input(
        "Date range", value=(min_d, max_d), min_value=min_d, max_value=max_d
    )

    # ── Apply filters ────────────────────────────────────────────────
    mask = (
        df["symbol"].isin(symbols)
        & df["timeframe"].isin(tfs)
        & df["grade"].isin(grades)
    )
    if side != "Both":
        mask &= df["side"] == side
    if trend != "All":
        mask &= df["daily_trend"] == trend
    if len(date_range) == 2:
        mask &= (df["timestamp"].dt.date >= date_range[0]) & (
            df["timestamp"].dt.date <= date_range[1]
        )

    filtered = df[mask].copy()
    st.caption(f"{len(filtered)} signals after filters ({len(df)} total)")

    if filtered.empty:
        st.info("No signals match current filters.")
        return

    closed = filtered[filtered["outcome"] != "OPEN"]

    # ── Panel 1: Summary table ───────────────────────────────────────
    st.subheader("Hit Rate by Grade")
    if not closed.empty:
        rows = []
        for g in _GRADE_ORDER:
            all_g = filtered[filtered["grade"] == g]
            closed_g = closed[closed["grade"] == g]
            if len(all_g) == 0:
                continue
            win_pct = (
                round(100 * (closed_g["outcome"] == "WIN").mean(), 1)
                if len(closed_g) else 0.0
            )
            avg_bars = round(closed_g["bars_to_outcome"].mean(), 1) if len(closed_g) else None
            rows.append({
                "Grade": g,
                "Signals": len(all_g),
                "Closed": len(closed_g),
                "Win %": win_pct,
                "Avg bars": avg_bars,
            })
        st.dataframe(
            pd.DataFrame(rows).set_index("Grade"), use_container_width=True
        )

    # ── Panel 2: Hit rate bar chart ──────────────────────────────────
    st.subheader("Win % by Grade")
    if not closed.empty:
        chart_data = (
            closed.groupby("grade")["outcome"]
            .apply(lambda s: round(100 * (s == "WIN").mean(), 1))
            .reindex(_GRADE_ORDER)
            .dropna()
            .reset_index()
        )
        chart_data.columns = ["Grade", "Win %"]
        st.bar_chart(chart_data.set_index("Grade"))

    # ── Panel 3: Score distribution ──────────────────────────────────
    st.subheader("Score Distribution: WIN vs LOSS")
    if not closed.empty:
        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"WIN  ({(closed['outcome']=='WIN').sum()} signals)")
            wins = closed[closed["outcome"] == "WIN"]["score"]
            if len(wins):
                st.bar_chart(wins.value_counts(bins=10).sort_index())
        with col2:
            st.caption(f"LOSS  ({(closed['outcome']=='LOSS').sum()} signals)")
            losses = closed[closed["outcome"] == "LOSS"]["score"]
            if len(losses):
                st.bar_chart(losses.value_counts(bins=10).sort_index())

    # ── Panel 4: Signal log ──────────────────────────────────────────
    st.subheader("Signal Log")

    def _colour_outcome(val):
        if val == "WIN":   return "background-color: #d4edda"
        if val == "LOSS":  return "background-color: #f8d7da"
        return "background-color: #e2e3e5"

    display = filtered.sort_values("timestamp", ascending=False).reset_index(drop=True)
    st.dataframe(
        display.style.map(_colour_outcome, subset=["outcome"]),
        use_container_width=True,
        height=400,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run full test suite (no regression)**

```bash
cd python
pytest -v
```

Expected: 142 PASSED, 0 failed.

- [ ] **Step 4: Commit**

```bash
cd python/..
git add python/backtest/app.py
git commit -m "feat: add Streamlit backtest dashboard with grade hit-rate panels"
```

---

## Task 5: Final integration + push

- [ ] **Step 1: Run full test suite one last time**

```bash
cd python
pytest -v --tb=short
```

Expected: 142 PASSED, 0 failed.

- [ ] **Step 2: Smoke test the CLI (requires internet)**

```bash
cd python
python -m backtest.run --symbols BTCUSDT --tf 1h --start 2024-01-01 --end 2024-01-31
```

Expected: downloads data, prints signal count and summary table, saves `backtest/results/latest.parquet`.

- [ ] **Step 3: Smoke test the dashboard**

```bash
cd python
streamlit run backtest/app.py
```

Expected: browser opens, dashboard loads, panels render. Ctrl+C to stop.

- [ ] **Step 4: Add backtest results dir to .gitignore**

Open `python/../.gitignore` (the root `.gitignore`) and add:

```
# Backtest cache and results
python/backtest/data/
python/backtest/results/
```

- [ ] **Step 5: Final commit and push**

```bash
cd python/..
git add .gitignore
git commit -m "chore: ignore backtest data cache and results from git"
git push origin master
```
