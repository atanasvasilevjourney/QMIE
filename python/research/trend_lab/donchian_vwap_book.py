"""Donchian breakout + anchored VWAP ranked book (notebook 08 logic, importable).

Crypto-only research: long-only trend with vol targeting (convexity / vol expansion),
AVWAP gate, optional compression coil, BTC regime cap. Not live execution.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from scanner.indicators import atr

from .donchian_avwap_util import avwap_from_anchor, seed_avwap_cum, swing_low_ts
from .donchian_nb08 import compression_percentile, donchian_dual

ANN = 365
COST_BPS = 10.0


@dataclass(frozen=True)
class DonchianVwapParams:
    n_entry: int = 55
    n_exit: int = 20
    atr_stop_mult: float = 3.0
    compression_window: int = 60
    compression_pct_max: float = 40.0
    avwap_anchor: str = "breakout_bar"  # breakout_bar | swing_low
    use_avwap_gate: bool = True
    use_compression_gate: bool = True
    top_k: int = 5
    rank_decay_exp: float = 1.0
    target_vol_ann: float = 0.25
    rebalance_rule: str = "W-SUN"
    regime_filter: bool = True
    gross_cap_off_regime: float = 0.30
    min_strength: float = 0.5
    single_name_cap: float = 0.25
    exec_lag: int = 1
    cost_bps: float = COST_BPS


def coin_features(df: pd.DataFrame, p: DonchianVwapParams) -> pd.DataFrame:
    don = donchian_dual(df, p.n_entry, p.n_exit)
    atr_s = atr(df, 14)
    comp_pct = compression_percentile(don["width"], p.compression_window)
    breakout = df["close"] > don["upper"]
    exit_lower = df["close"] < don["lower"]
    dist_upper = (df["close"] - don["upper"]) / (atr_s + 1e-12)
    return pd.DataFrame(
        {
            "close": df["close"],
            "upper": don["upper"],
            "lower": don["lower"],
            "width": don["width"],
            "comp_pct": comp_pct,
            "atr": atr_s,
            "breakout": breakout.astype(float),
            "exit_lower": exit_lower.astype(float),
            "dist_upper": dist_upper,
        },
        index=df.index,
    )


def simulate_coin_path(
    df: pd.DataFrame,
    p: DonchianVwapParams,
    rebalance_days: set,
) -> pd.DataFrame:
    """Entries on rebalance days only; risk exits any day. Incremental AVWAP while in."""
    feats = coin_features(df, p)
    idx = df.index
    n = len(idx)
    eligible = np.zeros(n, dtype=float)
    strength = np.zeros(n, dtype=float)
    dist_upper = feats["dist_upper"].to_numpy(dtype=float)
    breakout = feats["breakout"].to_numpy(dtype=float)
    comp_pct = feats["comp_pct"].to_numpy(dtype=float)
    exit_lower = feats["exit_lower"].to_numpy(dtype=float)
    atr_a = feats["atr"].to_numpy(dtype=float)
    close_a = feats["close"].to_numpy(dtype=float)
    width = feats["width"].to_numpy(dtype=float)

    in_pos = False
    entry_px = np.nan
    cum_pv, cum_v = 0.0, 0.0

    for i, ts in enumerate(idx):
        vol_exp = 0.0
        if i >= 5 and np.isfinite(width[i]) and np.isfinite(width[i - 5]) and width[i - 5] > 0:
            vol_exp = float(width[i] / width[i - 5] - 1.0)

        if in_pos and cum_v > 0:
            av = cum_pv / cum_v
            dist_av = (close_a[i] - av) / (atr_a[i] + 1e-12)
            strength[i] = dist_upper[i] + 0.5 * dist_av + 0.25 * vol_exp
        else:
            strength[i] = dist_upper[i] + 0.25 * vol_exp if np.isfinite(dist_upper[i]) else 0.0

        stop_hit = (
            in_pos
            and np.isfinite(entry_px)
            and np.isfinite(atr_a[i])
            and close_a[i] < entry_px - p.atr_stop_mult * atr_a[i]
        )
        if in_pos and (exit_lower[i] == 1.0 or stop_hit):
            in_pos = False
            entry_px = np.nan
            cum_pv, cum_v = 0.0, 0.0

        want = (
            ts in rebalance_days
            and not in_pos
            and breakout[i] == 1.0
            and np.isfinite(comp_pct[i])
            and strength[i] >= p.min_strength
        )
        if want and p.use_compression_gate and comp_pct[i] > p.compression_pct_max:
            want = False
        if want:
            anc = pd.Timestamp(ts) if p.avwap_anchor == "breakout_bar" else swing_low_ts(df, ts)
            av0 = avwap_from_anchor(df, anc, ts)
            dist0 = (close_a[i] - av0) / (atr_a[i] + 1e-12)
            if p.use_avwap_gate and dist0 < 0:
                want = False
            else:
                cum_pv, cum_v = seed_avwap_cum(df, anc, ts)
        if want:
            in_pos = True
            entry_px = close_a[i]
        elif in_pos and cum_v > 0:
            row = df.loc[ts]
            tp = (row["high"] + row["low"] + row["close"]) / 3.0
            cum_pv += float(tp) * float(row["volume"])
            cum_v += float(row["volume"])

        eligible[i] = 1.0 if in_pos else 0.0

    return pd.DataFrame({"eligible": eligible, "strength": strength}, index=idx)


def rank_weights(
    names: list[str],
    strengths: dict[str, float],
    vols: dict[str, float],
    p: DonchianVwapParams,
) -> dict[str, float]:
    if not names:
        return {}
    ranked = sorted(names, key=lambda n: strengths.get(n, -1e9), reverse=True)
    ranked = [n for n in ranked if strengths.get(n, 0) >= p.min_strength][: p.top_k]
    if not ranked:
        return {}
    raw = np.array([(len(ranked) - i) ** p.rank_decay_exp for i in range(len(ranked))], dtype=float)
    inv_vol = np.array([1.0 / max(vols.get(n, 1e-6), 1e-6) for n in ranked], dtype=float)
    w = raw * inv_vol
    w = w / w.sum()
    if p.single_name_cap < 1:
        w = np.minimum(w, p.single_name_cap)
        if w.sum() > 0:
            w = w / w.sum()
    return {n: float(wi) for n, wi in zip(ranked, w)}


def vol_scale_weights(weights: dict[str, float], port_vol: float, target: float) -> dict[str, float]:
    if port_vol <= 0 or not weights:
        return weights
    scale = min(1.0, target / port_vol)
    return {k: v * scale for k, v in weights.items()}


def btc_regime(btc: pd.DataFrame, n_entry: int) -> pd.Series:
    don = donchian_dual(btc, n_entry, max(5, n_entry // 3))
    return (btc["close"] > don["mid"]).astype(float).rename("regime")


def common_index(ohlcv: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    idx = None
    for df in ohlcv.values():
        idx = df.index if idx is None else idx.intersection(df.index)
    idx = pd.DatetimeIndex(idx).sort_values()
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return idx


def precompute_paths(
    ohlcv: dict[str, pd.DataFrame],
    p: DonchianVwapParams,
    idx: pd.DatetimeIndex,
    rebalance_days: set,
) -> dict[str, pd.DataFrame]:
    return {sym: simulate_coin_path(df.loc[idx], p, rebalance_days) for sym, df in ohlcv.items()}


def run_book_from_paths(
    ohlcv: dict[str, pd.DataFrame],
    btc: pd.DataFrame,
    p: DonchianVwapParams,
    idx: pd.DatetimeIndex,
    rebalance_days: set,
    paths: dict[str, pd.DataFrame],
    *,
    ranked: bool = True,
) -> pd.DataFrame:
    regime = btc_regime(btc, p.n_entry).reindex(idx).ffill().fillna(0)
    syms = list(ohlcv.keys())
    elig = pd.DataFrame({s: paths[s]["eligible"] for s in syms}, index=idx)
    stren = pd.DataFrame({s: paths[s]["strength"] for s in syms}, index=idx)
    rets = pd.DataFrame({s: ohlcv[s]["close"].loc[idx].pct_change(fill_method=None).fillna(0) for s in syms})
    vol20 = rets.rolling(20).std(ddof=1)
    held = pd.DataFrame(0.0, index=idx, columns=syms)
    last = pd.Series(0.0, index=syms)

    for ts in idx:
        if ts in rebalance_days:
            names = [s for s in syms if elig.at[ts, s] > 0]
            w: dict[str, float] = {}
            if names:
                strengths = {s: float(stren.at[ts, s]) for s in names}
                vols = {s: float(vol20.at[ts, s]) if pd.notna(vol20.at[ts, s]) else 1e-6 for s in names}
                w = rank_weights(names, strengths, vols, p) if ranked else {s: 1.0 / len(names) for s in names}
                gross = sum(w.values())
                reg = float(regime.at[ts])
                if p.regime_filter and reg < 0.5:
                    gross = min(gross, p.gross_cap_off_regime)
                elif not p.regime_filter:
                    gross = min(gross, p.gross_cap_off_regime)
                if gross > 0 and w:
                    w = {k: v * gross / sum(w.values()) for k, v in w.items()}
                port_vol = float(
                    np.sqrt(sum((float(vol20.at[ts, s]) or 0) ** 2 * (w.get(s, 0) ** 2) for s in w))
                ) * np.sqrt(ANN)
                w = vol_scale_weights(w, port_vol, p.target_vol_ann)
            last = pd.Series(0.0, index=syms)
            for s, wi in w.items():
                last[s] = wi
        for s in syms:
            held.at[ts, s] = float(last[s]) if elig.at[ts, s] > 0 else 0.0

    held_exec = held.shift(p.exec_lag).fillna(0)
    gross_ret = (held_exec * rets).sum(axis=1)
    turnover = held_exec.diff().abs().fillna(held_exec.abs()).sum(axis=1)
    net = gross_ret - turnover * (p.cost_bps / 1e4)
    return pd.DataFrame({"net": net, "equity": (1 + net).cumprod(), "turnover": turnover, "gross": gross_ret})


def rebalance_day_set(idx: pd.DatetimeIndex, rule: str) -> set:
    if rule.upper() in ("D", "1D", "DAILY"):
        return set(idx)
    return set(pd.Series(1, index=idx).resample(rule).last().dropna().index)


def run_book(
    ohlcv: dict[str, pd.DataFrame],
    btc: pd.DataFrame,
    p: DonchianVwapParams,
    *,
    ranked: bool = True,
) -> pd.DataFrame:
    idx = common_index(ohlcv)
    rebalance_days = rebalance_day_set(idx, p.rebalance_rule)
    paths = precompute_paths(ohlcv, p, idx, rebalance_days)
    return run_book_from_paths(ohlcv, btc, p, idx, rebalance_days, paths, ranked=ranked)


def dial_target_vol_is(
    ohlcv: dict[str, pd.DataFrame],
    btc: pd.DataFrame,
    base: DonchianVwapParams,
    is_end: pd.Timestamp,
    *,
    target_dd: float = -0.08,
    grid: np.ndarray | None = None,
    ranked: bool = True,
) -> tuple[float, pd.Series]:
    """IS-only search on ``target_vol_ann`` to stay at or above ``target_dd`` max DD."""
    from .metrics import max_dd

    if grid is None:
        grid = np.round(np.arange(0.06, 0.31, 0.01), 2)
    chosen_vt = float(base.target_vol_ann)
    chosen_net: pd.Series | None = None
    best_dd = -1.0
    for vt in grid:
        p = DonchianVwapParams(**{**base.__dict__, "target_vol_ann": float(vt)})
        net = run_book(ohlcv, btc, p, ranked=ranked)["net"]
        is_net = net.loc[:is_end].fillna(0.0)
        dd = max_dd((1.0 + is_net).cumprod())
        if dd >= target_dd and dd >= best_dd:
            best_dd = dd
            chosen_vt = float(vt)
            chosen_net = net
    if chosen_net is None:
        p = DonchianVwapParams(**{**base.__dict__, "target_vol_ann": float(grid[0])})
        return float(grid[0]), run_book(ohlcv, btc, p, ranked=ranked)["net"]
    return chosen_vt, chosen_net
