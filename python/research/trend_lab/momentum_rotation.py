"""Monthly momentum rotation (top-N risers) vs +SMA200 filter. Research only."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class RotationParams:
    top_n: int = 10
    momentum_days: int = 126
    sma_days: int = 200
    use_sma200_filter: bool = False
    rebalance_rule: str = "ME"
    cost_bps: float = 5.0
    exec_lag: int = 1


def monthly_top_momentum_weights(panel: pd.DataFrame, p: RotationParams) -> pd.DataFrame:
    idx = panel.index
    rebal = pd.DatetimeIndex(pd.Series(1, index=idx).resample(p.rebalance_rule).last().dropna().index)
    mom = panel.pct_change(p.momentum_days, fill_method=None)
    sma = panel.rolling(p.sma_days, min_periods=p.sma_days).mean()
    snaps: list[pd.Series] = []
    snap_idx: list[pd.Timestamp] = []

    for ts in rebal:
        if ts not in idx:
            loc = idx.searchsorted(ts, side="right") - 1
            if loc < 0:
                continue
            ts = idx[loc]
        row_m = mom.loc[ts]
        eligible = row_m.dropna().index.tolist()
        if p.use_sma200_filter:
            above = sma.loc[ts]
            eligible = [
                c for c in eligible
                if pd.notna(above.get(c)) and float(panel.loc[ts, c]) > float(above[c])
            ]
        hold = pd.Series(0.0, index=panel.columns)
        if eligible:
            ranked = row_m[eligible].sort_values(ascending=False).head(p.top_n).index.tolist()
            for c in ranked:
                hold[c] = 1.0 / len(ranked)
        snaps.append(hold)
        snap_idx.append(ts)

    if not snaps:
        return pd.DataFrame(0.0, index=idx, columns=panel.columns)
    snap_df = pd.DataFrame(snaps, index=pd.DatetimeIndex(snap_idx))
    w = snap_df.reindex(idx).ffill().fillna(0.0)
    w = w.reindex(columns=panel.columns, fill_value=0.0)
    return w


def rotation_net_returns(panel: pd.DataFrame, weights: pd.DataFrame, p: RotationParams) -> pd.Series:
    rets = panel.pct_change(fill_method=None).fillna(0.0)
    held = weights.shift(p.exec_lag).fillna(0.0)
    gross = (held * rets).sum(axis=1)
    turnover = held.diff().abs().fillna(held.abs()).sum(axis=1)
    return (gross - turnover * (p.cost_bps / 1e4)).rename("net")


def compare_rotations(panel: pd.DataFrame, *, top_n: int = 10) -> dict[str, pd.Series]:
    base = RotationParams(top_n=top_n, use_sma200_filter=False)
    filt = RotationParams(top_n=top_n, use_sma200_filter=True)
    w0 = monthly_top_momentum_weights(panel, base)
    w1 = monthly_top_momentum_weights(panel, filt)
    return {
        f"top{top_n}_momentum_monthly": rotation_net_returns(panel, w0, base),
        f"top{top_n}_momentum_sma200_monthly": rotation_net_returns(panel, w1, filt),
    }
