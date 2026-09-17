"""Ranked multi-asset Carver book (BTC + ETFs). Research only. No orders.

Calendar is US sessions (QQQ/GLD). BTC is as-of joined (last UTC daily
close on or before the session date). ``ann_days=252``. Weights are
lagged once; portfolio vol scale uses lagged realized book vol.

The vol dial is chosen on IS to sit near a 10% drawdown. Sharpe 1.4–1.5
is a goal, not an OOS constraint — we do not search OOS until it prints.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .carver import ewm_std, full_carver
from .metrics import kpis_from_net
from .protocol import SPLIT

ANN_SESSIONS = 252
COST_BPS = 2.0
GROSS_CAP = 1.5
SCALE_CAP = 2.5
TARGET_DD = -0.10
TARGET_SHARPE = (1.40, 1.50)


@dataclass(frozen=True)
class BookParams:
    vol_target: float = 0.16
    lookback: int = 60
    top_n: int = 2
    min_weight: float = 0.0
    use_cs: bool = True
    cost_bps: float = COST_BPS
    exec_lag: int = 1
    gross_cap: float = GROSS_CAP
    dd_trip: float | None = None  # e.g. -0.11; None = off
    dd_recover: float = -0.06
    dd_cut: float = 0.25


def carver_weight_panel(
    panel: pd.DataFrame,
    *,
    use_cs: bool = True,
    ann_days: int = ANN_SESSIONS,
) -> pd.DataFrame:
    """Per-name Carver forecast weights at unit vol_target=1. Port scale comes later."""
    cols = {}
    fdms = {}
    for name in panel.columns:
        w, _, fdm = full_carver(
            panel, name, use_cs=use_cs, vol_target=1.0, ann_days=ann_days, long_only=True,
        )
        cols[name] = w.reindex(panel.index).fillna(0.0)
        fdms[name] = fdm
    out = pd.DataFrame(cols, index=panel.index)
    out.attrs["fdm"] = fdms
    return out


def rank_mask(panel: pd.DataFrame, raw_w: pd.DataFrame, *, lookback: int, top_n: int, min_weight: float) -> pd.DataFrame:
    """Keep top_n names by lookback ROC among those with Carver weight > min_weight."""
    roc = panel.pct_change(lookback, fill_method=None)
    mask = pd.DataFrame(False, index=panel.index, columns=panel.columns)
    names = list(panel.columns)
    for ts in panel.index:
        eligible = [
            c for c in names
            if float(raw_w.at[ts, c]) > min_weight and pd.notna(roc.at[ts, c])
        ]
        if not eligible:
            continue
        scored = sorted(eligible, key=lambda c: float(roc.at[ts, c]), reverse=True)[:top_n]
        for c in scored:
            mask.at[ts, c] = True
    return mask


def book_from_raw_weights(
    panel: pd.DataFrame,
    raw_w: pd.DataFrame,
    params: BookParams,
    *,
    ann_days: int = ANN_SESSIONS,
) -> pd.DataFrame:
    """Rank filter → lag → lagged vol scale → optional DD cut. Causal."""
    mask = rank_mask(panel, raw_w, lookback=params.lookback, top_n=params.top_n, min_weight=params.min_weight)
    w = raw_w.where(mask, 0.0)
    rets = panel.pct_change(fill_method=None).fillna(0.0)
    held0 = w.shift(params.exec_lag).fillna(0.0)
    raw_net = (held0 * rets).sum(axis=1)
    port_vol = ewm_std(raw_net, 30) * np.sqrt(ann_days)
    scale = (params.vol_target / port_vol.replace(0.0, np.nan)).clip(lower=0.0, upper=SCALE_CAP)
    scale = scale.shift(1).fillna(0.0)  # vol through t-1
    held = held0.mul(scale, axis=0)
    gross = held.clip(lower=0.0).sum(axis=1)
    cap_f = (params.gross_cap / gross.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
    held = held.mul(cap_f, axis=0)
    if params.dd_trip is not None:
        held = _dd_cut_held(held, rets, trip=params.dd_trip, recover=params.dd_recover, cut=params.dd_cut)
    turnover = held.diff().abs().fillna(held.abs()).sum(axis=1)
    net = (held * rets).sum(axis=1) - turnover * (params.cost_bps / 1e4)
    eq = (1.0 + net).cumprod()
    out = pd.DataFrame({
        "net": net,
        "equity": eq,
        "turnover": turnover,
        "gross": held.clip(lower=0.0).sum(axis=1),
        "n_names": (held > 0).sum(axis=1),
        "scale": scale,
        **{f"w_{c}": held[c] for c in held.columns},
    })
    return out


def _dd_cut_held(
    held: pd.DataFrame,
    rets: pd.DataFrame,
    *,
    trip: float,
    recover: float,
    cut: float,
) -> pd.DataFrame:
    """Causal: equity through t-1. Multiplies all names by cut after a trip."""
    net = (held * rets).sum(axis=1)
    eq = (1.0 + net).cumprod()
    dd = (eq / eq.cummax() - 1.0).shift(1)
    reduced = False
    factors = []
    for t in held.index:
        d = dd.loc[t] if t in dd.index else 0.0
        if pd.isna(d):
            d = 0.0
        if (not reduced) and d <= trip:
            reduced = True
        if reduced and d >= recover:
            reduced = False
        factors.append(cut if reduced else 1.0)
    return held.mul(pd.Series(factors, index=held.index), axis=0)


def slice_kpis(book: pd.DataFrame, start, end, *, ann: int = ANN_SESSIONS) -> dict[str, float]:
    sl = book.loc[start:end]
    if sl.empty:
        return kpis_from_net(pd.Series(dtype=float), ann=ann)
    k = kpis_from_net(sl["net"], ann=ann)
    k["avg_names"] = float(sl["n_names"].mean()) if "n_names" in sl else float("nan")
    k["avg_gross"] = float(sl["gross"].mean()) if "gross" in sl else float("nan")
    return k


def pick_vol_target(
    panel_is: pd.DataFrame,
    raw_w_is: pd.DataFrame,
    *,
    lookback: int = 60,
    top_n: int = 2,
    grid: Iterable[float] = (0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20),
    target_dd: float = TARGET_DD,
    sharpe_band: tuple[float, float] = TARGET_SHARPE,
) -> dict[str, Any]:
    """IS-only: prefer max DD near 10%, then Sharpe inside 1.4–1.5 if available."""
    rows = []
    for vt in grid:
        p = BookParams(vol_target=float(vt), lookback=lookback, top_n=top_n)
        book = book_from_raw_weights(panel_is, raw_w_is.reindex(panel_is.index).fillna(0.0), p)
        k = kpis_from_net(book["net"], ann=ANN_SESSIONS)
        dd_gap = abs(float(k["max_dd"]) - target_dd) if np.isfinite(k["max_dd"]) else 9.0
        s = float(k["sharpe"]) if np.isfinite(k["sharpe"]) else -9.0
        in_band = sharpe_band[0] <= s <= sharpe_band[1]
        rows.append({
            "vol_target": float(vt),
            **k,
            "dd_gap": dd_gap,
            "in_sharpe_band": in_band,
        })
    table = pd.DataFrame(rows).sort_values(["dd_gap", "vol_target"])
    near = table[table["dd_gap"] <= 0.025]
    pool = near[near["in_sharpe_band"]] if near["in_sharpe_band"].any() else near
    if pool.empty:
        pool = table
    # among pool, closest Sharpe to band midpoint
    mid = 0.5 * (sharpe_band[0] + sharpe_band[1])
    pool = pool.copy()
    pool["sharpe_gap"] = (pool["sharpe"] - mid).abs()
    best = pool.sort_values(["dd_gap", "sharpe_gap"]).iloc[0]
    return {"vol_target": float(best["vol_target"]), "is_kpis": best.to_dict(), "table": table}


def walk_forward(
    panel: pd.DataFrame,
    raw_w: pd.DataFrame,
    *,
    folds: list[tuple[str, str, str, str]],
    lookback: int,
    top_n: int,
) -> pd.DataFrame:
    """Each fold: pick vol_target on that fold's IS, apply to fold OOS. Never peeks past IS."""
    rows = []
    for is_a, is_b, oos_a, oos_b in folds:
        is_p = panel.loc[is_a:is_b]
        oos_p = panel.loc[oos_a:oos_b]
        if len(is_p) < 300 or len(oos_p) < 40:
            continue
        picked = pick_vol_target(is_p, raw_w.reindex(is_p.index).fillna(0.0), lookback=lookback, top_n=top_n)
        p = BookParams(vol_target=picked["vol_target"], lookback=lookback, top_n=top_n)
        # run on IS+OOS so vol ewm is continuous, then slice OOS nets
        span = panel.loc[is_a:oos_b]
        book = book_from_raw_weights(span, raw_w.reindex(span.index).fillna(0.0), p)
        k = slice_kpis(book, oos_a, oos_b)
        rows.append({
            "is": f"{is_a}→{is_b}",
            "oos": f"{oos_a}→{oos_b}",
            "vol_target": picked["vol_target"],
            **k,
        })
    return pd.DataFrame(rows)


def neighborhood(
    panel_is: pd.DataFrame,
    raw_w: pd.DataFrame,
    center: BookParams,
    *,
    inner_frac: float = 0.2,
) -> pd.DataFrame:
    """DF-style: train vs last-20% IS val. Vol ±, lookback ±, top_n ±. Never OOS."""
    cut = int(len(panel_is) * (1.0 - inner_frac))
    train = panel_is.iloc[:cut]
    val = panel_is.iloc[cut:]
    vts = sorted({round(center.vol_target * x, 4) for x in (0.8, 1.0, 1.2)})
    lbs = sorted({max(20, center.lookback + d) for d in (-20, 0, 20)})
    tns = sorted({n for n in (center.top_n - 1, center.top_n, center.top_n + 1) if 1 <= n <= panel_is.shape[1]})
    rows = []
    for vt in vts:
        for lb in lbs:
            for tn in tns:
                p = BookParams(vol_target=vt, lookback=lb, top_n=tn)
                tr = book_from_raw_weights(train, raw_w.reindex(train.index).fillna(0.0), p)
                va = book_from_raw_weights(val, raw_w.reindex(val.index).fillna(0.0), p)
                kt = kpis_from_net(tr["net"], ann=ANN_SESSIONS)
                kv = kpis_from_net(va["net"], ann=ANN_SESSIONS)
                rows.append({
                    "vol_target": vt, "lookback": lb, "top_n": tn,
                    "sharpe_train": kt["sharpe"], "sharpe_val": kv["sharpe"],
                    "max_dd_train": kt["max_dd"], "max_dd_val": kv["max_dd"],
                })
    return pd.DataFrame(rows)


def is_oos_index(panel: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    is_end = pd.Timestamp(SPLIT.is_end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    oos_start = pd.Timestamp(SPLIT.oos_start, tz="UTC")
    return is_end, oos_start
