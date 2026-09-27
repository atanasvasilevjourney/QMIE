"""Prop-style portfolio vol targeting for research rotation books (no orders).

Implements lagged book-vol scaling (Carver book pattern) and IS-only vol pick
under a max-DD floor — aligned with docs/prop-sizing-ftmo-swing.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from .carver import ewm_std
from .metrics import max_dd
from .momentum_rotation import RotationParams, rotation_net_returns

ANN_EQUITY = 252
SCALE_CAP = 2.5


@dataclass(frozen=True)
class RotationVolParams:
    vol_target: float = 0.12
    vol_span: int = 30
    gross_cap: float = 1.0
    ann_days: int = ANN_EQUITY


def lagged_vol_scale(raw_net: pd.Series, *, vol_target: float, vol_span: int, ann_days: int) -> pd.Series:
    """Causal scale: realized vol through t-1."""
    port_vol = ewm_std(raw_net.fillna(0.0), vol_span) * np.sqrt(ann_days)
    scale = (vol_target / port_vol.replace(0.0, np.nan)).clip(lower=0.0, upper=SCALE_CAP)
    return scale.shift(1).fillna(0.0)


def scale_weights_by_series(weights: pd.DataFrame, scale: pd.Series) -> pd.DataFrame:
    s = scale.reindex(weights.index).fillna(0.0)
    w = weights.mul(s, axis=0)
    gross = w.clip(lower=0.0).sum(axis=1)
    cap = (1.0 / gross.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
    return w.mul(cap, axis=0)


def rotation_net_vol_targeted(
    panel: pd.DataFrame,
    weights: pd.DataFrame,
    rot: RotationParams,
    vp: RotationVolParams,
) -> pd.Series:
    """Raw rotation net → lagged vol scale → re-run returns with scaled weights."""
    raw = rotation_net_returns(panel, weights, rot)
    scale = lagged_vol_scale(raw, vol_target=vp.vol_target, vol_span=vp.vol_span, ann_days=vp.ann_days)
    w_scaled = scale_weights_by_series(weights, scale)
    if vp.gross_cap < 1.0:
        gross = w_scaled.clip(lower=0.0).sum(axis=1)
        cap_f = (vp.gross_cap / gross.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
        w_scaled = w_scaled.mul(cap_f, axis=0)
    return rotation_net_returns(panel, w_scaled, rot)


def pick_rotation_vol_target_is(
    panel: pd.DataFrame,
    weights: pd.DataFrame,
    rot: RotationParams,
    is_end: pd.Timestamp,
    *,
    max_dd_floor: float = -0.08,
    grid: Iterable[float] = (0.04, 0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20),
    vol_span: int = 30,
    gross_cap: float = 1.0,
) -> dict[str, float | pd.Series]:
    """Largest ann vol target on IS whose max DD is no worse than ``max_dd_floor``."""
    is_end = pd.Timestamp(is_end)
    chosen = float(min(grid))
    best_net: pd.Series | None = None
    for vt in grid:
        vp = RotationVolParams(vol_target=float(vt), vol_span=vol_span, gross_cap=gross_cap)
        net = rotation_net_vol_targeted(panel, weights, rot, vp)
        is_net = net.loc[:is_end].fillna(0.0)
        if is_net.empty:
            continue
        dd = max_dd((1.0 + is_net).cumprod())
        if dd >= max_dd_floor:
            chosen = float(vt)
            best_net = net
        else:
            break
    if best_net is None:
        vp = RotationVolParams(vol_target=chosen, vol_span=vol_span, gross_cap=gross_cap)
        best_net = rotation_net_vol_targeted(panel, weights, rot, vp)
    return {"vol_target": chosen, "net": best_net, "is_max_dd_floor": max_dd_floor}
