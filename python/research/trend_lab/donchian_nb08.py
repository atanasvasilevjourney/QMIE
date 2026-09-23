"""Notebook 08 Donchian dual-channel weights (daily), for Carver blends.

Prior-bar Donchian (``shift(1)`` on high/low). Long-only state machine:
breakout entry, lower-band or ATR stop exit. Vol-sized weight while in.

AVWAP / compression / weekly rebalance are **off** by default here so this
module pairs cleanly with daily ``carver_weight_panel``. Turn gates on via
``Donchian08Params`` if reproducing full notebook 08 paths.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from scanner.indicators import atr

ANN = 365


@dataclass(frozen=True)
class Donchian08Params:
    n_entry: int = 55
    n_exit: int = 20
    atr_stop_mult: float = 3.0
    compression_window: int = 60
    compression_pct_max: float = 40.0
    use_compression_gate: bool = False
    use_avwap_gate: bool = False
    min_strength: float = 0.0
    target_vol_ann: float = 0.25
    lev_cap: float = 2.0
    vol_lookback: int = 20


def donchian_dual(df: pd.DataFrame, n_entry: int, n_exit: int) -> pd.DataFrame:
    hi = df["high"].shift(1).rolling(n_entry, min_periods=n_entry).max()
    lo = df["low"].shift(1).rolling(n_exit, min_periods=n_exit).min()
    mid = (hi + lo) / 2.0
    width = (hi - lo) / (df["close"] + 1e-12)
    return pd.DataFrame({"upper": hi, "lower": lo, "mid": mid, "width": width}, index=df.index)


def compression_percentile(width: pd.Series, window: int) -> pd.Series:
    def _pct(x: np.ndarray) -> float:
        if len(x) < 2:
            return np.nan
        last = x[-1]
        return float((x[:-1] <= last).mean() * 100.0)

    return width.rolling(window, min_periods=window).apply(_pct, raw=True)


def donchian_nb08_weight_series(df: pd.DataFrame, p: Donchian08Params | None = None) -> pd.Series:
    """Daily weight 0…lev_cap while in a Donchian 08-style long."""
    p = p or Donchian08Params()
    don = donchian_dual(df, p.n_entry, p.n_exit)
    atr_s = atr(df, 14)
    comp_pct = compression_percentile(don["width"], p.compression_window)
    ret = df["close"].pct_change(fill_method=None)
    vol = ret.rolling(p.vol_lookback).std(ddof=1) * np.sqrt(ANN)

    upper = don["upper"].to_numpy(dtype=float)
    lower = don["lower"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    comp = comp_pct.to_numpy(dtype=float)
    atr_a = atr_s.to_numpy(dtype=float)
    vol_a = vol.to_numpy(dtype=float)

    n = len(df)
    w_out = np.zeros(n)
    in_pos = False
    entry_px = np.nan

    for i in range(n):
        stop_hit = (
            in_pos
            and np.isfinite(entry_px)
            and np.isfinite(atr_a[i])
            and close[i] < entry_px - p.atr_stop_mult * atr_a[i]
        )
        if in_pos and (np.isfinite(lower[i]) and close[i] < lower[i] or stop_hit):
            in_pos = False
            entry_px = np.nan

        want = (
            not in_pos
            and np.isfinite(upper[i])
            and close[i] > upper[i]
        )
        if want and p.use_compression_gate and (not np.isfinite(comp[i]) or comp[i] > p.compression_pct_max):
            want = False
        # AVWAP gate omitted in daily path unless extended later (needs anchor loop from nb 08)

        if want:
            in_pos = True
            entry_px = close[i]

        if in_pos and np.isfinite(vol_a[i]) and vol_a[i] > 0:
            w_out[i] = min(p.lev_cap, p.target_vol_ann / vol_a[i])
        else:
            w_out[i] = 0.0

    return pd.Series(w_out, index=df.index, name="w_don08")


def donchian_nb08_weight_panel(
    ohlcv: dict[str, pd.DataFrame],
    p: Donchian08Params | None = None,
) -> pd.DataFrame:
    p = p or Donchian08Params()
    cols = {sym: donchian_nb08_weight_series(df, p) for sym, df in ohlcv.items()}
    idx = None
    for s in cols.values():
        idx = s.index if idx is None else idx.intersection(s.index)
    idx = pd.DatetimeIndex(idx).sort_values()
    return pd.DataFrame({sym: cols[sym].reindex(idx).fillna(0.0) for sym in cols}, index=idx)
