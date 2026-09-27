from __future__ import annotations

import pandas as pd

from research.trend_lab.mentor_prop import canary_defensive_multiplier, days_to_profit_pct, mentor_gated_weights


def test_mentor_gate_zeros_when_flag_off():
    idx = pd.date_range("2020-01-01", periods=5, freq="D", tz="UTC")
    w = pd.DataFrame({"A": [0.5] * 5}, index=idx)
    f = pd.DataFrame({"A": [0.0, 1.0, 1.0, 0.0, 1.0]}, index=idx)
    g = mentor_gated_weights(w, f)
    assert g.iloc[0, 0] == 0.0
    assert g.iloc[1, 0] == 0.5


def test_days_to_profit():
    net = pd.Series([0.01, 0.01, 0.01, 0.01])
    assert days_to_profit_pct(net, 0.10) is None
    net2 = pd.Series([0.05, 0.06])
    assert days_to_profit_pct(net2, 0.10) == 2


def test_canary_multiplier_bounds():
    idx = pd.date_range("2020-01-01", periods=100, freq="D", tz="UTC")
    s = pd.Series(range(100), index=idx, dtype=float) + 100
    m = canary_defensive_multiplier(s, s * 1.01, s * 0.99)
    assert m.min() >= 0.25
    assert m.max() <= 1.0
