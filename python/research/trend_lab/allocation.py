"""Ranked spot book + chop gate + blend. Signal-only; quantity stays 0 live.

Mirrors QMIE allocator intent (top-N, cluster-aware ranking) on daily
closes. Does not dispatch and does not place orders.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scanner.indicators import adx

from .metrics import kpis
from .protocol import ANN_DAYS


CLUSTERS: dict[str, str] = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "BNBUSDT": "BNB",
    "XRPUSDT": "OTHER",
    "LTCUSDT": "OTHER",
    "ADAUSDT": "OTHER",
    "LINKUSDT": "ETH",
    "SOLUSDT": "SOL",
    "DOGEUSDT": "OTHER",
    "DOTUSDT": "OTHER",
    "AVAXUSDT": "OTHER",
}


def chop_gate(ohlcv: pd.DataFrame, min_adx: float = 18.0) -> pd.Series:
    """1 when ADX says a trend exists. Causal (bar-close ADX)."""
    _, _, adx_s = adx(ohlcv, 14)
    return (adx_s >= min_adx).astype(float).rename("chop_gate")


def blend_weights(carver: pd.Series, ensemble: pd.Series, *, mix: float = 0.5) -> pd.Series:
    """mix=1 is pure Carver; mix=0 is pure binary ensemble. Both already lagged by caller."""
    a = carver.reindex(ensemble.index).fillna(0.0)
    b = ensemble.reindex(carver.index).fillna(0.0) if len(carver) else ensemble
    idx = a.index.union(b.index).sort_values()
    a = a.reindex(idx).fillna(0.0)
    b = b.reindex(idx).fillna(0.0)
    w = (mix * a + (1.0 - mix) * b).clip(0.0, 1.0)
    return w.rename("blend")


def ranked_spot_book(
    close_panel: pd.DataFrame,
    held_panel: pd.DataFrame,
    *,
    lookback: int = 60,
    top_n: int = 3,
    vol_parity: bool = False,
    cluster_max: int = 1,
    cost_bps: float = 8.0,
    exec_lag: int = 1,
) -> pd.DataFrame:
    """Each bar: rank eligible names by lookback ROC, take top_n, lag weights.

    ``held_panel`` must already be the *signal* (not lagged); this function
    applies ``exec_lag``.
    """
    close_panel = close_panel.sort_index()
    held_panel = held_panel.reindex(close_panel.index).fillna(0.0)
    roc = close_panel.pct_change(lookback, fill_method=None)
    vol = close_panel.pct_change(fill_method=None).rolling(20).std()
    names = list(close_panel.columns)
    weights = pd.DataFrame(0.0, index=close_panel.index, columns=names)

    for ts in close_panel.index:
        eligible = [c for c in names if float(held_panel.at[ts, c]) > 0 and pd.notna(roc.at[ts, c])]
        if not eligible:
            continue
        scored = sorted(eligible, key=lambda c: float(roc.at[ts, c]), reverse=True)
        picked: list[str] = []
        clusters: dict[str, int] = {}
        for c in scored:
            cl = CLUSTERS.get(c, "OTHER")
            if cluster_max and clusters.get(cl, 0) >= cluster_max:
                continue
            picked.append(c)
            clusters[cl] = clusters.get(cl, 0) + 1
            if len(picked) >= top_n:
                break
        if not picked:
            continue
        if vol_parity:
            inv = np.array([1.0 / max(float(vol.at[ts, c]), 1e-8) if pd.notna(vol.at[ts, c]) else 1.0 for c in picked])
            w = inv / inv.sum()
        else:
            # rank weights n, n-1, … (same as allocator.weighting=rank)
            raw = np.arange(len(picked), 0, -1, dtype=float)
            w = raw / raw.sum()
        for c, wi in zip(picked, w):
            weights.at[ts, c] = float(wi)

    held_w = weights.shift(exec_lag).fillna(0.0)
    rets = close_panel.pct_change(fill_method=None).fillna(0.0)
    gross = (held_w * rets).sum(axis=1)
    turnover = held_w.diff().abs().fillna(held_w.abs()).sum(axis=1)
    net = gross - turnover * (cost_bps / 1e4)
    eq = (1.0 + net).cumprod()
    n_names = (held_w > 0).sum(axis=1)
    return pd.DataFrame({
        "net": net,
        "equity": eq,
        "turnover": turnover,
        "n_names": n_names,
        "gross": gross,
        **{f"w_{c}": held_w[c] for c in names},
    })


def equal_weight_book(
    close_panel: pd.DataFrame,
    held_panel: pd.DataFrame,
    *,
    cost_bps: float = 8.0,
    exec_lag: int = 1,
) -> pd.DataFrame:
    held = held_panel.reindex(close_panel.index).fillna(0.0)
    n = held.sum(axis=1).replace(0, np.nan)
    w = held.div(n, axis=0).fillna(0.0).shift(exec_lag).fillna(0.0)
    rets = close_panel.pct_change(fill_method=None).fillna(0.0)
    gross = (w * rets).sum(axis=1)
    turnover = w.diff().abs().fillna(w.abs()).sum(axis=1)
    net = gross - turnover * (cost_bps / 1e4)
    return pd.DataFrame({"net": net, "equity": (1.0 + net).cumprod(), "turnover": turnover, "n_names": (w > 0).sum(axis=1)})


def bh_equal(close_panel: pd.DataFrame) -> pd.DataFrame:
    rets = close_panel.pct_change(fill_method=None).fillna(0.0)
    n = close_panel.notna().sum(axis=1).clip(lower=1)
    net = rets.where(close_panel.notna(), np.nan).mean(axis=1).fillna(0.0)
    return pd.DataFrame({"net": net, "equity": (1.0 + net).cumprod(), "n_names": n})


def book_kpis(book: pd.DataFrame) -> dict[str, float]:
    return {
        **kpis(book["net"], book["equity"]),
        "avg_names": float(book["n_names"].mean()) if "n_names" in book else float("nan"),
        "ann_turnover": float(book["turnover"].sum() * ANN_DAYS / max(len(book), 1)) if "turnover" in book else float("nan"),
    }
