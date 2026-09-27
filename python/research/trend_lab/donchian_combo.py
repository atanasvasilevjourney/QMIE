"""SSRN 5209907 Donchian Combo weights (research only)."""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (5, 10, 20, 30, 60, 90, 150, 250, 360)
DON_VOL_TARGET = 0.25
SIGMA_DAYS = 90
LEV_CAP = 2.0
COST_BPS = 10.0
REBAL_THRESH = 0.20
EXEC_LAG = 1
ANN = 365

MCAP_TOP20 = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "TRXUSDT", "ZECUSDT", "DOGEUSDT",
    "HYPEUSDT", "ADAUSDT", "LINKUSDT", "XLMUSDT", "UNIUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT",
    "NEARUSDT", "DOTUSDT", "ENAUSDT", "SUIUSDT",
]


def combo_weight_series(close: pd.Series) -> pd.Series:
    """Equal-weight average of 9 Donchian sub-models (mid-band trail, vol-sized)."""
    c = close.to_numpy(dtype=float)
    n_bars = len(c)
    sigma = close.pct_change(fill_method=None).rolling(SIGMA_DAYS).std(ddof=1).to_numpy(dtype=float) * np.sqrt(ANN)
    mids, ups = {}, {}
    for n in HORIZONS:
        up = close.rolling(n, min_periods=n).max().to_numpy(dtype=float)
        dn = close.rolling(n, min_periods=n).min().to_numpy(dtype=float)
        mids[n] = (up + dn) / 2
        ups[n] = up
    nh = len(HORIZONS)
    in_pos = np.zeros(nh, dtype=bool)
    trail = np.full(nh, np.nan)
    w_exec = np.zeros(nh)
    w_combo = np.zeros(n_bars)
    for i in range(n_bars):
        ci = c[i]
        sig = sigma[i]
        for j, n in enumerate(HORIZONS):
            mid, up = mids[n][i], ups[n][i]
            if not in_pos[j]:
                if np.isfinite(up) and ci >= up:
                    in_pos[j] = True
                    trail[j] = mid
            else:
                if np.isfinite(trail[j]) and ci < trail[j]:
                    in_pos[j] = False
                    trail[j] = np.nan
                elif np.isfinite(mid):
                    trail[j] = max(trail[j], mid)
            w_tgt = 0.0
            if in_pos[j] and np.isfinite(sig) and sig > 0:
                w_tgt = min(LEV_CAP, DON_VOL_TARGET / sig)
            if abs(w_tgt - w_exec[j]) > REBAL_THRESH:
                w_exec[j] = w_tgt
        w_combo[i] = w_exec.mean()
    return pd.Series(w_combo, index=close.index)


def equal_weight_portfolio(
    raw_w: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    cost_bps: float = COST_BPS,
    exec_lag: int = EXEC_LAG,
) -> pd.Series:
    """Mean of per-asset net returns (notebook 09 style)."""
    rets = panel.pct_change(fill_method=None).fillna(0.0)
    held = raw_w.shift(exec_lag).fillna(0.0)
    nets = {}
    for c in raw_w.columns:
        w = held[c]
        nets[c] = w * rets[c] - w.diff().abs().fillna(w.abs()) * (cost_bps / 1e4)
    return pd.DataFrame(nets).mean(axis=1)
