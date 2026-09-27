"""Khalsa Follow-Through Index (TSSB / Masters / indicatorPy port).

Research only. Uses ``indicatorPy`` (translated from FTI.CPP). Values are
causal when combined with ``shift(1)`` before trading.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from indicators.trend.fti import FTI

_FTI = FTI()
# TSSB-style defaults (BlockSize=128, HalfLength=32, periods 5–65)
# 2 * half_length must be >= max_period (TSSB constraint)
DEFAULT_PARAMS = ("best_fti", 128, 33, 5, 65)


def fti_best(close: pd.Series, *, params: tuple = DEFAULT_PARAMS) -> pd.Series:
    """``best_fti`` score in approximately [-50, 50]."""
    var, p1, p2, p3, p4 = params
    arr = _FTI.calculate(var, float(p1), float(p2), float(p3), float(p4), close.to_numpy(dtype=float))
    return pd.Series(arr, index=close.index, name="fti")


def fti_panel(panel: pd.DataFrame, *, params: tuple = DEFAULT_PARAMS) -> pd.DataFrame:
    return pd.DataFrame({c: fti_best(panel[c], params=params) for c in panel.columns})
