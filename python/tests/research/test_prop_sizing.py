from __future__ import annotations

import pandas as pd

from research.trend_lab.momentum_rotation import RotationParams, monthly_top_momentum_weights
from research.trend_lab.prop_sizing import (
    lagged_vol_scale,
    pick_rotation_vol_target_is,
    rotation_net_vol_targeted,
    RotationVolParams,
)


def test_lagged_vol_scale_is_causal():
    idx = pd.date_range("2020-01-01", periods=80, freq="B", tz="UTC")
    raw = pd.Series(0.01, index=idx)
    raw.iloc[40:] = 0.02
    sc = lagged_vol_scale(raw, vol_target=0.12, vol_span=10, ann_days=252)
    assert sc.iloc[0] == 0.0
    assert sc.iloc[1] >= 0.0


def test_higher_vol_target_increases_scale():
    idx = pd.date_range("2019-01-01", periods=120, freq="B", tz="UTC")
    raw = pd.Series([0.01, -0.008, 0.012, -0.005] * 30, index=idx, dtype=float)
    low = lagged_vol_scale(raw, vol_target=0.06, vol_span=10, ann_days=252)
    high = lagged_vol_scale(raw, vol_target=0.18, vol_span=10, ann_days=252)
    assert high.iloc[60:].mean() > low.iloc[60:].mean()


def test_pick_rotation_vol_target_is_monotone_grid():
    idx = pd.date_range("2019-01-01", periods=500, freq="B", tz="UTC")
    t = pd.Series(range(500), index=idx, dtype=float)
    panel = pd.DataFrame({"X": 100 + t * 0.05, "Y": 100 + t * 0.02})
    p = RotationParams(top_n=1, momentum_days=30, rebalance_rule="ME")
    w = monthly_top_momentum_weights(panel, p)
    is_end = idx[350]
    out = pick_rotation_vol_target_is(panel, w, p, is_end, max_dd_floor=-0.50)
    assert out["vol_target"] >= 0.04
    assert len(out["net"]) == len(idx)
