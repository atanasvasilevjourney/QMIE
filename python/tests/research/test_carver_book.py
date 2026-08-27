"""Carver ranked book: lag, rank filter causality, vol-target pick stays on IS."""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.trend_lab.carver_book import (
    BookParams,
    book_from_raw_weights,
    pick_vol_target,
    rank_mask,
)


def _panel(n: int = 500) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=n, tz="UTC")
    rng = np.random.default_rng(0)
    def path(mu, sig):
        return 100.0 * np.exp(np.cumsum(rng.normal(mu, sig, n)))
    return pd.DataFrame({
        "BTC": path(0.0010, 0.03),
        "QQQ": path(0.0004, 0.012),
        "GLD": path(0.0002, 0.008),
    }, index=idx)


def test_rank_mask_does_not_use_future_close():
    p = _panel()
    w = pd.DataFrame(0.4, index=p.index, columns=p.columns)
    m1 = rank_mask(p, w, lookback=20, top_n=2, min_weight=0.0)
    p2 = p.copy()
    p2.iloc[-1, 0] = p2.iloc[-1, 0] * 3.0
    m2 = rank_mask(p2, w, lookback=20, top_n=2, min_weight=0.0)
    assert m1.iloc[:-1].equals(m2.iloc[:-1])


def test_book_first_bar_flat_and_lagged():
    p = _panel(400)
    raw = pd.DataFrame(0.5, index=p.index, columns=p.columns)
    book = book_from_raw_weights(p, raw, BookParams(vol_target=0.12, lookback=20, top_n=2))
    assert float(book["n_names"].iloc[0]) == 0.0
    assert float(book["gross"].iloc[0]) == 0.0
    # a later bar can be long
    assert float(book["gross"].iloc[80:].max()) > 0


def test_pick_vol_target_returns_grid_value():
    p = _panel(400)
    raw = pd.DataFrame(0.5, index=p.index, columns=p.columns)
    picked = pick_vol_target(p, raw, lookback=20, top_n=2, grid=(0.10, 0.16, 0.24))
    assert picked["vol_target"] in (0.10, 0.16, 0.24)
    assert "table" in picked and len(picked["table"]) == 3
