from __future__ import annotations

import numpy as np
import pandas as pd

from long_vol.config import LongVolConfig
from long_vol.live_scan import liquidity_ok, scan_closed_bar


def _panel(n: int = 200) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    close = 100 + np.cumsum(np.random.default_rng(1).normal(0, 0.02, n))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 50000.0,
        },
        index=idx,
    )


def test_liquidity_ok_passes_high_volume():
    df = _panel(100)
    ok, meta = liquidity_ok(df, min_quote_vol=1_000_000, max_spread_median=0.02)
    assert ok is True
    assert meta["quote_vol_24h"] > 1_000_000


def test_scan_insufficient_bars():
    cfg = LongVolConfig()
    df = _panel(50)
    cand, _ = scan_closed_bar("ETHUSDT", df, cfg=cfg, btc15=df)
    assert cand.reason == "insufficient_bars"
