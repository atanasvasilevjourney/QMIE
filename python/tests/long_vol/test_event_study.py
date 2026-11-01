from __future__ import annotations

import numpy as np
import pandas as pd

from long_vol.backtest.event_study import forward_returns_from_next_open, run_event_study
from long_vol.config import LongVolConfig


def _df15(n: int = 200) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    close = 100 + np.cumsum(np.random.default_rng(1).normal(0, 0.05, n))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000.0,
        },
        index=idx,
    )


def test_forward_returns_next_open():
    df = _df15(50)
    ts = df.index[10:12]
    out = forward_returns_from_next_open(df, ts, fee_bps=0)
    assert len(out) == 2
    assert "ret_1h_pct" in out.columns


def test_run_event_study_empty_triggers_ok():
    cfg = LongVolConfig()
    res = run_event_study({"X": _df15(100)}, cfg)
    assert isinstance(res.events, pd.DataFrame)
