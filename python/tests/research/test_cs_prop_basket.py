from __future__ import annotations

import numpy as np
import pandas as pd

from research.trend_lab.cs_prop_basket import (
    CsBasketParams,
    basket_net_returns,
    cs_conviction_weights,
    cs_vote_matrix,
)


def _panel(n: int = 200, k: int = 5) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=n, tz="UTC")
    rng = np.random.default_rng(1)
    cols = {}
    for i in range(k):
        cols[f"A{i}"] = 100 * np.exp(np.cumsum(rng.normal(0.0002 * (i + 1), 0.01, n)))
    return pd.DataFrame(cols, index=idx)


def test_votes_bounded():
    panel = _panel(120, 4)
    p = CsBasketParams(horizons=(5, 10, 20), min_votes=2, top_n=2, gross_target=0.5)
    v = cs_vote_matrix(panel, p)
    assert v.max().max() <= len(p.horizons)
    assert v.min().min() >= 0


def test_weights_gross_cap():
    panel = _panel(150, 6)
    p = CsBasketParams(min_votes=1, top_n=3, gross_target=0.68)
    w = cs_conviction_weights(panel, p)
    gross = w.sum(axis=1)
    assert gross.max() <= p.gross_target + 1e-9
    net = basket_net_returns(panel, w, p)
    assert len(net) == len(panel)
