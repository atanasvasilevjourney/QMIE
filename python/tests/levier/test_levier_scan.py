from __future__ import annotations

import numpy as np
import pandas as pd

from levier.config import LevierConfig
from levier.features import compute_tape_row, tape_label
from levier.live_scan import scan_universe
from levier.rank import bullish_score, rank_rows


def _df30(n: int = 100, drift: float = 0.001) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="30min", tz="UTC")
    close = 10 * (1 + drift) ** np.arange(n)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 5000.0,
        },
        index=idx,
    )


def test_compute_tape_row_above_vwap():
    row = compute_tape_row(_df30(80, drift=0.002))
    assert row["ok"]
    assert row["dist_pct"] > 0
    assert row["atr_pct"] > 0


def test_bullish_score_prefers_extension():
    a = {"ok": True, "dist_pct": 5, "rsi": 70, "adx": 25, "quote_vol_24h": 1e6, "rsi_delta": 2}
    b = {"ok": True, "dist_pct": 1, "rsi": 55, "adx": 15, "quote_vol_24h": 1e6, "rsi_delta": 0}
    assert bullish_score(a) > bullish_score(b)


def test_scan_universe_leaderboard():
    panels = {"AAAUSDT": _df30(100, 0.003), "BBBUSDT": _df30(100, 0.0005)}
    out = scan_universe(panels, LevierConfig())
    assert len(out["leaderboard"]) >= 1
    assert out["leaderboard"][0]["rank"] == 1


def test_tape_label_euphoria():
    assert "EUPHORIA" in tape_label(9.0, 83, 30)
