from __future__ import annotations

import pandas as pd

from long_vol.config import FeaturesConfig
from long_vol.features.long_vol_features import compute_long_vol_features


def _synthetic_15m(n_days: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2024-06-01", periods=n_days * 96, freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
        },
        index=idx,
    )


def test_truncated_run_matches_full_at_cutoff():
    df = _synthetic_15m(10)
    cfg = FeaturesConfig(vwap_bars=96, width_pct_lookback_1h_bars=48)
    full = compute_long_vol_features(df, cfg=cfg)
    cut = df.index[400]
    partial = compute_long_vol_features(df.loc[:cut], cfg=cfg)
    cols = ["vwap24", "dist_atr", "don_up_1h", "width_pct"]
    for c in cols:
        if c not in partial.df15.columns:
            continue
        fval = full.df15.loc[cut, c]
        pval = partial.df15.loc[cut, c]
        if pd.isna(fval) and pd.isna(pval):
            continue
        assert fval == pval or abs(float(fval) - float(pval)) < 1e-9
