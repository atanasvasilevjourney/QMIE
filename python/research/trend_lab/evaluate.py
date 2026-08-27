"""IS / OOS evaluation helpers. Fit never sees OOS."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from .metrics import kpis
from .optimize import kpis_spot, kpis_tema
from .protocol import WARMUP_BARS, SPLIT, split_frame
from .spot_system import SpotParams, spot_signal
from .tema_system import TemaParams, tema_trades


def eval_spot(full: pd.DataFrame, params: SpotParams) -> dict[str, Any]:
    parts = split_frame(full)
    is_fr = spot_signal(parts["is"], params)
    oos_fr = spot_signal(parts["oos_seeded"], params)
    oos_only = oos_fr.reindex(parts["oos"].index)
    oos_net = oos_only["net"].fillna(0.0)
    oos_eq = (1.0 + oos_net).cumprod()
    oos_only = oos_only.copy()
    oos_only["equity"] = oos_eq
    bh_is = _bh(parts["is"].iloc[WARMUP_BARS:])
    bh_oos = _bh(parts["oos"])
    n_in = int((oos_only["signal"].diff().fillna(0) > 0).sum())
    return {
        "params": asdict(params),
        "is": kpis_spot(is_fr),
        "oos": kpis(oos_net, oos_eq, trades=n_in),
        "bh_is": bh_is,
        "bh_oos": bh_oos,
        "is_frame": is_fr.iloc[WARMUP_BARS:],
        "oos_frame": oos_only,
        "full_oos_seeded": oos_fr,
    }


def eval_tema(full: pd.DataFrame, params: TemaParams) -> dict[str, Any]:
    parts = split_frame(full)
    is_cut = parts["is"].index[min(WARMUP_BARS, len(parts["is"]) - 1)]
    is_tr = tema_trades(parts["is"], params)
    if not is_tr.empty:
        is_tr = is_tr.loc[is_tr["entry_time"] >= is_cut].reset_index(drop=True)
    oos_tr = tema_trades(parts["oos_seeded"], params)
    oos_start = pd.Timestamp(SPLIT.oos_start, tz="UTC")
    if not oos_tr.empty:
        oos_tr = oos_tr.loc[oos_tr["entry_time"] >= oos_start].reset_index(drop=True)
    return {
        "params": asdict(params),
        "is": kpis_tema(parts["is"].index, is_tr),
        "oos": kpis_tema(parts["oos"].index, oos_tr),
        "is_trades": is_tr,
        "oos_trades": oos_tr,
        "parts": parts,
    }


def reverse_split_diagnostic(full: pd.DataFrame, params: SpotParams) -> dict[str, Any]:
    """Train on 2023→now, test on 2019–2022. Leakage diagnostic only — not a result."""
    parts = split_frame(full)
    # "fit" window is OOS in our protocol; "test" is IS
    fit_fr = spot_signal(parts["oos"], params)
    test_fr = spot_signal(parts["is"], params)
    return {
        "note": "LEAKAGE DIAGNOSTIC — future used as fit. Do not select parameters from this.",
        "fit_on_future": kpis_spot(fit_fr),
        "test_on_past": kpis_spot(test_fr),
    }


def _bh(ohlcv: pd.DataFrame) -> dict[str, float]:
    if ohlcv.empty:
        return kpis(pd.Series(dtype=float), pd.Series(dtype=float))
    net = ohlcv["close"].pct_change().fillna(0.0)
    eq = (1.0 + net).cumprod()
    return kpis(net, eq)
