"""Flow screener helpers — mocked REST, no network."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.flow_metrics import _cvd_slope, _ohlc_proxy_delta


def test_ohlc_proxy_delta_balanced_bar_near_zero():
    df = pd.DataFrame(
        {"open": [100.0], "high": [110.0], "low": [90.0], "close": [100.0], "volume": [1000.0]},
        index=pd.DatetimeIndex(["2026-01-01"], tz="UTC"),
    )
    d = _ohlc_proxy_delta(df)
    assert d.iloc[0] == pytest.approx(0.0, abs=1e-6)


def test_cvd_slope_positive_when_buy_pressure():
    delta = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert _cvd_slope(delta, lookback=3) == pytest.approx(11.0)
