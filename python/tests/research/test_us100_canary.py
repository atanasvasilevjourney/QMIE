from __future__ import annotations

import pandas as pd

from research.trend_lab.us100_canary import us100_bull_canary


def test_canary_is_binary():
    idx = pd.date_range("2020-01-01", periods=250, freq="B", tz="UTC")
    close = pd.Series(range(250), index=idx, dtype=float) + 100
    c = us100_bull_canary(close, mode="both")
    assert set(c.dropna().unique()).issubset({0.0, 1.0})
