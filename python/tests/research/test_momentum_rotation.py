from __future__ import annotations

import numpy as np
import pandas as pd

from research.trend_lab.momentum_rotation import RotationParams, monthly_top_momentum_weights, rotation_net_returns


def test_rotation_weights_sum_to_one_or_zero():
    idx = pd.date_range("2020-01-01", periods=400, freq="B", tz="UTC")
    rng = np.random.default_rng(1)
    panel = pd.DataFrame(
        {f"S{i}": 100 * np.cumprod(1 + rng.normal(0.001, 0.02, len(idx))) for i in range(5)},
        index=idx,
    )
    p = RotationParams(top_n=2, momentum_days=20, sma_days=50, use_sma200_filter=False)
    w = monthly_top_momentum_weights(panel, p)
    sums = w.sum(axis=1)
    assert ((sums <= 1.0001) & (sums >= 0)).all()
    net = rotation_net_returns(panel, w, p)
    assert len(net) == len(panel)
