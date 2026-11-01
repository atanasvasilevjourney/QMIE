"""Long-vol integration with scheduler (mock exchange)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from long_vol.config import LongVolConfig
from scanner.scheduler import ScannerScheduler


def _df(n: int = 200) -> pd.DataFrame:
    idx = pd.date_range("2024-06-01", periods=n, freq="15min", tz="UTC")
    c = 100 + np.cumsum(np.random.default_rng(0).normal(0, 0.02, n))
    return pd.DataFrame(
        {"open": c, "high": c + 0.3, "low": c - 0.3, "close": c, "volume": 80000.0},
        index=idx,
    )


@pytest.fixture
def long_vol_scheduler():
    client = MagicMock()
    client.fetch_klines = AsyncMock(return_value=_df(200))
    universe = MagicMock()
    universe.get = AsyncMock(return_value=["ETHUSDT"])
    dispatcher = MagicMock()
    dispatcher.dispatch_inbound = AsyncMock(return_value=False)
    cfg = LongVolConfig()
    dumped = cfg.model_dump()
    dumped["features"]["width_pct_lookback_1h_bars"] = 48
    cfg = LongVolConfig.model_validate(dumped)
    sched = ScannerScheduler(
        client=client,
        universe=universe,
        dispatcher=dispatcher,
        timeframes=["4h"],
        htf_map={"4h": "1d"},
        long_vol_enabled=True,
        long_vol_notify=False,
        long_vol_cfg=cfg,
        long_vol_kline_limit=200,
    )
    return sched, dispatcher, client


@pytest.mark.asyncio
async def test_long_vol_pass_populates_candidates(long_vol_scheduler):
    sched, dispatcher, client = long_vol_scheduler
    await sched._long_vol_pass()
    assert sched.stats["long_vol_passes"] == 1
    assert isinstance(sched.last_long_vol, list)
    assert len(sched.last_long_vol) == 1
    assert client.fetch_klines.await_count >= 2
    dispatcher.dispatch_inbound.assert_not_called()
