"""
Shared test fixtures.

Synthetic OHLCV data builders so we don't need real network. Each
generator returns a clean DataFrame with the schema the scanner
expects: open/high/low/close/volume + UTC DatetimeIndex.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Make `python/` importable as the project root for tests
_PY_ROOT = Path(__file__).resolve().parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

# Ensure config has a webhook secret for tests that import `main`
os.environ.setdefault("WEBHOOK_SECRET", "test-secret-do-not-use-in-prod")
os.environ.setdefault("DISCORD_ENABLED", "false")
os.environ.setdefault("TELEGRAM_ENABLED", "false")


# ─── Helpers ────────────────────────────────────────────────────────────
def _df_from_close(close: np.ndarray, *, freq: str = "1h",
                   start: str = "2024-01-01") -> pd.DataFrame:
    """Build a OHLCV DataFrame from a close-price array. high/low are
    derived with small noise; volume is a constant. Index is UTC."""
    n = len(close)
    rng = np.random.default_rng(42)
    noise_hi = np.abs(rng.normal(0, 0.001, n)) * close
    noise_lo = np.abs(rng.normal(0, 0.001, n)) * close
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum.reduce([open_, close, close + noise_hi])
    low = np.minimum.reduce([open_, close, close - noise_lo])
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": np.full(n, 1000.0),
    }, index=pd.date_range(start, periods=n, freq=freq, tz="UTC"))


# ─── Fixtures ───────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def bull_trend_df() -> pd.DataFrame:
    """Clear uptrend: linear ramp + tiny noise. 400 bars."""
    n = 400
    base = np.linspace(100.0, 200.0, n)
    rng = np.random.default_rng(1)
    close = base + rng.normal(0, 0.5, n)
    return _df_from_close(close)


@pytest.fixture(scope="session")
def bear_trend_df() -> pd.DataFrame:
    """Clear downtrend: linear decline + tiny noise. 400 bars."""
    n = 400
    base = np.linspace(200.0, 100.0, n)
    rng = np.random.default_rng(2)
    close = base + rng.normal(0, 0.5, n)
    return _df_from_close(close)


@pytest.fixture(scope="session")
def choppy_df() -> pd.DataFrame:
    """No trend: random walk around 100. 400 bars."""
    n = 400
    rng = np.random.default_rng(3)
    rets = rng.normal(0, 0.005, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    return _df_from_close(close)


@pytest.fixture(scope="session")
def htf_bull_df() -> pd.DataFrame:
    """Independent HTF (4h) bullish data, 400 bars long enough for the
    EMA200-warmup gate inside compute_signal."""
    n = 400
    base = np.linspace(100.0, 200.0, n)
    rng = np.random.default_rng(4)
    close = base + rng.normal(0, 0.5, n)
    return _df_from_close(close, freq="4h")


@pytest.fixture
def constant_close_df() -> pd.DataFrame:
    """Edge case: zero volatility (price doesn't move). 300 bars."""
    n = 300
    close = np.full(n, 100.0)
    df = pd.DataFrame({
        "open": close, "high": close, "low": close,
        "close": close, "volume": np.full(n, 1000.0),
    }, index=pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"))
    return df


@pytest.fixture
def short_df() -> pd.DataFrame:
    """Insufficient warmup: only 25 bars. Below triple-ST's 30-bar floor
    AND below compute_signal's 220-bar floor."""
    n = 25
    close = np.linspace(100.0, 110.0, n)
    return _df_from_close(close)
