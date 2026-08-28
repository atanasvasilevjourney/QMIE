"""Approach 2 — 4h TEMA stack, isolated 10x. Frozen live lengths 9/90/199.

Entry when triple-EMA agreement >= 1 (same threshold as QMIE TMA vote).
SL 1.5×ATR / TP 2.5×ATR; same-bar both → SL. Isolated margin: loss capped
at stake. Leverage sizes notional only — not an order.

Grid/Optuna may search nearby periods on IS. Promote-to-live is forbidden.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from scanner.indicators import adx, atr, rsi

from .features import tma_agreement


@dataclass(frozen=True)
class TemaParams:
    fast: int = 9
    mid: int = 90
    slow: int = 199
    min_adx: float = 20.0
    min_atr_pct: float = 0.4
    max_atr_pct: float = 4.0
    sl_atr: float = 1.5
    tp_atr: float = 2.5
    max_bars: int = 100
    leverage: float = 10.0
    stake: float = 100.0
    cost_bps: float = 4.0
    agree_min: int = 1


def tema_trades(df: pd.DataFrame, p: TemaParams) -> pd.DataFrame:
    """Event-driven long-only book. One position at a time per symbol."""
    c = df["close"]
    h = df["high"]
    l = df["low"]
    agree = tma_agreement(c, p.fast, p.mid, p.slow)
    pdi, mdi, adx_s = adx(df, 14)
    atr_s = atr(df, 14)
    atr_pct = 100.0 * atr_s / c
    rsi_s = rsi(c, 14)
    long_ok = (
        (agree >= p.agree_min)
        & (adx_s >= p.min_adx)
        & (pdi > mdi)
        & (atr_pct >= p.min_atr_pct)
        & (atr_pct <= p.max_atr_pct)
        & (rsi_s <= 80.0)
    )
    rows = []
    i = 0
    n = len(df)
    idx = df.index
    c_a = c.to_numpy()
    h_a = h.to_numpy()
    l_a = l.to_numpy()
    atr_a = atr_s.to_numpy()
    ok_a = long_ok.fillna(False).to_numpy()
    while i < n:
        if not ok_a[i] or not np.isfinite(atr_a[i]):
            i += 1
            continue
        # enter next bar open ≈ this close (closed-bar discipline)
        if i + 1 >= n:
            break
        entry_i = i + 1
        entry = float(c_a[i])  # signal on i, fill at i close; conservative vs next open
        sl = entry - p.sl_atr * float(atr_a[i])
        tp = entry + p.tp_atr * float(atr_a[i])
        outcome = "OPEN"
        exit_px = float(c_a[-1])
        exit_i = n - 1
        for j in range(entry_i, min(n, entry_i + p.max_bars)):
            hit_sl = l_a[j] <= sl
            hit_tp = h_a[j] >= tp
            if hit_sl and hit_tp:
                outcome, exit_px, exit_i = "SL", sl, j
                break
            if hit_sl:
                outcome, exit_px, exit_i = "SL", sl, j
                break
            if hit_tp:
                outcome, exit_px, exit_i = "TP", tp, j
                break
        else:
            outcome, exit_px, exit_i = "TIME", float(c_a[min(n, entry_i + p.max_bars) - 1]), min(n, entry_i + p.max_bars) - 1
        ret = (exit_px - entry) / entry
        notional = p.stake * p.leverage
        pnl = notional * ret
        # isolated: lose at most stake
        liquidated = pnl < -p.stake
        if liquidated:
            pnl = -p.stake
        pnl -= notional * (p.cost_bps / 1e4) * 2  # round-trip
        r_mult = (exit_px - entry) / (entry - sl) if entry > sl else np.nan
        rows.append({
            "entry_time": idx[i],
            "exit_time": idx[exit_i],
            "entry": entry,
            "exit": exit_px,
            "sl": sl,
            "tp": tp,
            "outcome": outcome,
            "ret": ret,
            "pnl": pnl,
            "liquidated": liquidated,
            "r": r_mult,
            "bars": int(exit_i - entry_i + 1),
            "adx": float(adx_s.iloc[i]),
            "agree": float(agree.iloc[i]),
        })
        i = exit_i + 1
    return pd.DataFrame(rows)


def tema_equity(trades: pd.DataFrame, *, start_eq: float = 10_000.0) -> pd.Series:
    if trades.empty:
        return pd.Series(dtype=float, name="equity")
    eq = start_eq
    pts = []
    for _, r in trades.iterrows():
        eq = eq + float(r["pnl"])
        pts.append((r["exit_time"], eq))
    s = pd.Series({t: v for t, v in pts}, name="equity").sort_index()
    return s


def tema_bar_equity(
    index: pd.DatetimeIndex,
    trades: pd.DataFrame,
    *,
    start_eq: float = 10_000.0,
) -> pd.DataFrame:
    """Mark-to-cash equity on the bar index. PnL booked at exit_time (no MTM)."""
    cash = pd.Series(0.0, index=index, name="pnl")
    if not trades.empty:
        grouped = trades.groupby("exit_time")["pnl"].sum()
        common = grouped.index.intersection(index)
        cash.loc[common] = grouped.loc[common].astype(float)
        # exits that land between bars (shouldn't) → next bar
        missing = grouped.index.difference(index)
        if len(missing):
            pos = index.searchsorted(missing, side="left")
            for ts, i in zip(missing, pos):
                if i < len(index):
                    cash.iloc[i] += float(grouped.loc[ts])
    eq = (start_eq + cash.cumsum()).rename("equity")
    net = eq.pct_change().fillna(0.0).rename("net")
    return pd.DataFrame({"pnl": cash, "equity": eq, "net": net})


def n_liquidations(trades: pd.DataFrame) -> int:
    if trades.empty:
        return 0
    return int(trades["liquidated"].fillna(False).sum())


BARS_PER_DAY_4H = 6
ANN_4H = 365 * BARS_PER_DAY_4H  # 2190; only for raw 4h-bar Sharpe


def daily_equity(eq: pd.Series) -> pd.Series:
    """Last mark of each UTC day. KPIs on this series use ANN_DAYS=365."""
    eq = eq.dropna()
    if eq.empty:
        return eq
    return eq.resample("1D").last().dropna().rename(eq.name or "equity")


def daily_net(eq: pd.Series) -> pd.Series:
    d = daily_equity(eq)
    if d.empty:
        return pd.Series(dtype=float, name="net")
    return d.pct_change().fillna(0.0).rename("net")


def rescale_trades(
    trades: pd.DataFrame,
    scale: pd.Series | float,
    *,
    base_stake: float,
    leverage: float,
    cost_bps: float,
    min_scale: float = 0.0,
    max_scale: float = 2.5,
) -> pd.DataFrame:
    """Reprice an existing trade list at a new isolated stake.

    ``scale`` is looked up at ``entry_time`` (as-of, no future). Isolated cap
    is reapplied to the new stake. Same entries/exits — size only.
    """
    if trades.empty:
        out = trades.copy()
        out["stake"] = pd.Series(dtype=float)
        out["scale"] = pd.Series(dtype=float)
        return out
    out = trades.copy()
    scales: list[float] = []
    if isinstance(scale, (int, float)):
        s0 = float(np.clip(float(scale), min_scale, max_scale))
        scales = [s0] * len(out)
    else:
        sc = scale.sort_index()
        for ts in out["entry_time"]:
            v = sc.asof(ts)
            if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
                v = 0.0
            scales.append(float(np.clip(float(v), min_scale, max_scale)))
    stake_eff = base_stake * np.asarray(scales, dtype=float)
    ret = out["ret"].to_numpy(dtype=float)
    notional = stake_eff * leverage
    pnl = notional * ret - notional * (cost_bps / 1e4) * 2.0
    liq = pnl < -stake_eff
    pnl = np.where(liq, -stake_eff, pnl)
    out["stake"] = stake_eff
    out["scale"] = np.asarray(scales, dtype=float)
    out["pnl"] = pnl
    out["liquidated"] = liq
    return out


def compound_trades(
    trades: pd.DataFrame,
    *,
    start_eq: float,
    risk_frac: float,
    leverage: float,
    cost_bps: float,
) -> pd.DataFrame:
    """Each trade risks ``risk_frac`` of *current* equity as isolated stake.

    ``risk_frac=0.01`` is a 1% wallet. ``risk_frac=1.0`` is the whole account
    as isolated margin (one full SL can be ~10–20% of book, not 100%, because
    SL is 1.5×ATR on the 10× notional).
    """
    if trades.empty:
        return trades.copy()
    eq = float(start_eq)
    rows = []
    for _, r in trades.iterrows():
        rec = r.to_dict()
        stake_i = max(0.0, eq * float(risk_frac))
        notional = stake_i * leverage
        pnl = notional * float(r["ret"]) - notional * (cost_bps / 1e4) * 2.0
        liq = pnl < -stake_i
        if liq:
            pnl = -stake_i
        eq = eq + pnl
        rec["stake"] = stake_i
        rec["pnl"] = pnl
        rec["liquidated"] = bool(liq)
        rec["equity"] = eq
        rows.append(rec)
        if eq <= 0:
            break
    return pd.DataFrame(rows)


def trade_stats(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {
            "n": 0.0,
            "win_rate": float("nan"),
            "expectancy_usdt": float("nan"),
            "mean_r": float("nan"),
            "median_r": float("nan"),
            "liquidations": 0.0,
            "mean_bars": float("nan"),
            "tp_share": float("nan"),
            "sl_share": float("nan"),
            "time_share": float("nan"),
        }
    n = float(len(trades))
    oc = trades["outcome"].astype(str)
    return {
        "n": n,
        "win_rate": float((trades["pnl"] > 0).mean()),
        "expectancy_usdt": float(trades["pnl"].mean()),
        "mean_r": float(trades["r"].mean()) if "r" in trades else float("nan"),
        "median_r": float(trades["r"].median()) if "r" in trades else float("nan"),
        "liquidations": float(n_liquidations(trades)),
        "mean_bars": float(trades["bars"].mean()) if "bars" in trades else float("nan"),
        "tp_share": float((oc == "TP").mean()),
        "sl_share": float((oc == "SL").mean()),
        "time_share": float((oc == "TIME").mean()),
    }
