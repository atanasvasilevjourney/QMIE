"""Carver-style continuous sizing vs binary ensemble.

Ported from the uploaded ``carver_engine_with_cross_sectional`` notebook
(Strat 17–19). Crypto ``ANN_DAYS=365``. Long-only. exec_lag=1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .protocol import ANN_DAYS

FC_TARGET = 10.0
FC_CAP = 20.0
COST_BPS = 3.25
VOL_TARGET = 0.20
EWMAC_PAIRS = [(8, 32, 5.95), (16, 64, 4.10), (32, 128, 2.79), (64, 256, 1.91)]
EWMAC_FDM = 1.13


def ewm_std(x: pd.Series, span: int) -> pd.Series:
    a = 2.0 / (span + 1.0)
    m = x.ewm(alpha=a, adjust=False).mean()
    m2 = (x * x).ewm(alpha=a, adjust=False).mean()
    var = (m2 - m * m).clip(lower=0.0)
    bc = (2.0 - 2.0 * a) / (2.0 - a)
    return np.sqrt(var / bc)


def vol_stack(close: pd.Series, *, ann_days: int = ANN_DAYS) -> pd.DataFrame:
    ann = np.sqrt(ann_days)
    ret = close.pct_change(fill_method=None).clip(-0.9, 9.0)
    vol_short = ewm_std(ret, 30) * ann
    vol_long = vol_short.rolling(5 * ann_days, min_periods=ann_days).mean()
    vol = pd.Series(
        np.where(vol_long.isna(), vol_short, 0.70 * vol_short + 0.30 * vol_long),
        index=close.index,
        name="vol",
    )
    sigma_p = (close * vol / ann).rename("sigma_p")
    return pd.DataFrame({"ret": ret, "vol_short": vol_short, "vol_long": vol_long, "vol": vol, "sigma_p": sigma_p})


def position_from_forecast(
    forecast: pd.Series,
    vol: pd.Series,
    *,
    vol_target: float = VOL_TARGET,
    long_only: bool = True,
) -> pd.Series:
    w = (forecast / FC_TARGET) * (vol_target / vol)
    w = w.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    lo = 0.0 if long_only else -1.0
    return w.clip(lo, 1.0).rename("weight")


def backtest(close: pd.Series, weight: pd.Series, *, cost_bps: float = COST_BPS, exec_lag: int = 1) -> pd.DataFrame:
    ret = close.pct_change(fill_method=None).fillna(0.0)
    held = weight.shift(exec_lag).fillna(0.0)
    turnover = held.diff().abs().fillna(held.abs())
    net = held * ret - turnover * (cost_bps / 1e4)
    return pd.DataFrame({
        "ret": ret,
        "weight": weight,
        "held": held,
        "net": net,
        "equity": (1.0 + net).cumprod(),
    })


def ewmac_forecast(close: pd.Series, sigma_p: pd.Series) -> pd.Series:
    subs = []
    for f, s, sc in EWMAC_PAIRS:
        raw = (close.ewm(span=f, adjust=False).mean() - close.ewm(span=s, adjust=False).mean()) / sigma_p
        subs.append((raw * sc).clip(-FC_CAP, FC_CAP))
    return (sum(subs) / len(subs) * EWMAC_FDM).clip(-FC_CAP, FC_CAP)


def breakout_forecast(close: pd.Series) -> pd.Series:
    subs = []
    for n, sc, sm in [(40, 0.70, 10), (80, 0.73, 20), (160, 0.74, 40), (320, 0.74, 80)]:
        mn, mx = close.rolling(n).min(), close.rolling(n).max()
        rng = mx - mn
        spir = ((close - mn) / rng).where(rng > 0, 0.5)
        subs.append(((spir - 0.5) * 40.0).ewm(span=sm, adjust=False).mean().mul(sc).clip(-FC_CAP, FC_CAP))
    return (sum(subs) / len(subs) * 1.17).clip(-FC_CAP, FC_CAP)


def accel_forecast(close: pd.Series, sigma_p: pd.Series) -> pd.Series:
    bases = []
    for f, s, sc in EWMAC_PAIRS:
        bases.append(((close.ewm(span=f, adjust=False).mean() - close.ewm(span=s, adjust=False).mean()) / sigma_p * sc).clip(-FC_CAP, FC_CAP))
    ap, scs = [8, 16, 32, 64], [1.87, 1.90, 1.98, 2.05]
    subs = [((bases[i] - bases[i].shift(ap[i])) * scs[i]).clip(-FC_CAP, FC_CAP) for i in range(4)]
    return (sum(subs) / len(subs) * 1.55).clip(-FC_CAP, FC_CAP)


def skew_forecast(ret: pd.Series) -> pd.Series:
    subs = []
    for w, sc, sm in [(60, 33.3, 15), (120, 37.2, 30), (240, 39.2, 60)]:
        g = ret.rolling(w, min_periods=w // 2).skew()
        subs.append((-g).ewm(span=sm, adjust=False).mean().mul(sc).clip(-FC_CAP, FC_CAP))
    return (sum(subs) / len(subs) * 1.18).clip(-FC_CAP, FC_CAP)


def vol_attenuation(vol: pd.Series) -> pd.Series:
    p = vol.rolling(1260, min_periods=252).rank(pct=True)
    p = p.ewm(span=10, adjust=False).mean()
    return (1.5 - p).clip(0.5, 1.5).fillna(1.0).rename("vol_att")


def normalised_price(close: pd.Series, *, ann_days: int = ANN_DAYS) -> pd.Series:
    v = vol_stack(close, ann_days=ann_days)
    ann = np.sqrt(ann_days)
    rn = (v["ret"] / (v["vol"] / ann)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return (100.0 * rn.cumsum()).rename("PN")


def cs_momentum_forecast(
    panel: pd.DataFrame,
    target: str,
    horizons: tuple[int, ...] = (40, 80),
    *,
    ann_days: int = ANN_DAYS,
) -> pd.Series:
    pn = pd.DataFrame({
        c: normalised_price(panel[c].dropna(), ann_days=ann_days).reindex(panel.index).ffill()
        for c in panel.columns
    })
    a = pn.mean(axis=1)
    r = pn[target] - a
    subs = []
    for h in horizons:
        raw = (r - r.shift(h)) / h
        sm = raw.ewm(span=max(2, h // 4), adjust=False).mean()
        sc = 10.0 / sm.abs().mean() if sm.abs().mean() > 0 else 1.0
        subs.append((sm * sc).clip(-FC_CAP, FC_CAP))
    return (sum(subs) / len(subs) * 1.10).clip(-FC_CAP, FC_CAP).rename("CSmom")


def fdm_from_corr(w: np.ndarray, c: np.ndarray, fdm_max: float = 2.5) -> float:
    w = np.asarray(w, float)
    w = w / w.sum()
    var = float(w @ c @ w)
    return float(min(fdm_max, 1.0 / np.sqrt(var))) if var > 0 else 1.0


def combine_forecasts(forecasts: dict[str, pd.Series], weights: dict[str, float]) -> tuple[pd.Series, float]:
    names = list(forecasts)
    f = pd.concat([forecasts[n].rename(n) for n in names], axis=1)
    w = np.array([weights[n] for n in names], float)
    w = w / w.sum()
    c = f.dropna().corr().reindex(index=names, columns=names).values
    c = np.nan_to_num(c, nan=0.0)
    np.fill_diagonal(c, 1.0)
    fdm = fdm_from_corr(w, c)
    combined = (f.mul(w, axis=1).sum(axis=1) * fdm).clip(-FC_CAP, FC_CAP)
    return combined, fdm


def full_carver(
    panel: pd.DataFrame,
    target: str,
    *,
    use_cs: bool = True,
    vol_target: float = VOL_TARGET,
    ann_days: int = ANN_DAYS,
    long_only: bool = True,
) -> tuple[pd.Series, pd.Series, float]:
    close = panel[target].dropna()
    vs = vol_stack(close, ann_days=ann_days)
    forecasts = {
        "EWMAC": ewmac_forecast(close, vs.sigma_p),
        "Breakout": breakout_forecast(close),
        "Accel": accel_forecast(close, vs.sigma_p),
        "Skew": skew_forecast(vs.ret),
    }
    weights = {"EWMAC": 0.15, "Breakout": 0.15, "Accel": 0.15, "Skew": 0.20}
    if use_cs and panel.shape[1] >= 3:
        forecasts["CSmom"] = cs_momentum_forecast(panel, target, ann_days=ann_days).reindex(close.index)
        weights["CSmom"] = 0.15
    combined, fdm = combine_forecasts(forecasts, weights)
    fc_att = combined * vol_attenuation(vs.vol)
    w = position_from_forecast(
        fc_att.clip(-FC_CAP, FC_CAP), vs.vol, vol_target=vol_target, long_only=long_only,
    )
    return w, combined, fdm


def dd_circuit_breaker(weight: pd.Series, equity: pd.Series, *, trip: float = -0.12, recover: float = -0.06, cut: float = 0.25) -> pd.Series:
    """Cut size after a peak-to-trough hit. Causal: uses equity up to t-1."""
    dd = equity / equity.cummax() - 1.0
    dd_lag = dd.shift(1)
    reduced = False
    out = []
    for t, w in weight.items():
        d = dd_lag.loc[t] if t in dd_lag.index else 0.0
        if pd.isna(d):
            d = 0.0
        if (not reduced) and d <= trip:
            reduced = True
        if reduced and d >= recover:
            reduced = False
        out.append(float(w) * (cut if reduced else 1.0))
    return pd.Series(out, index=weight.index, name="weight_dd")
