"""AdaptiveTrend replication (arXiv:2602.11708) — research only.

Stripped-down, reproducible core from Bui & Nguyen (2026):
  * 6h momentum entry (ROC over lookback L)
  * ATR trailing stop (multiplier alpha)
  * Optional long/short with lambda long capital split (portfolio layer)

Full paper adds monthly grid search per asset and mcap filters on 150+
pairs. This module uses **fixed** hyperparameters (alpha=2.5, lambda=0.70)
and a small Vision universe so QMIE can test without overfitting machinery.

6h bars: resampled from native 4h Vision klines (crypto 24/7).
Does not retune live ``W_*`` or dispatch alerts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import numpy as np
import pandas as pd

from backtest.data_loader import resample_ohlcv
from scanner.indicators import atr as wilder_atr

from .data import load_symbol
from .metrics import kpis
from .protocol import SPLIT, WARMUP_BARS, split_frame

Side = Literal["long", "short"]

# Paper Table 1 window (Jan 2022 – Dec 2024 OOS after 2021 IS calibration)
PAPER_IS_END = date(2021, 12, 31)
PAPER_OOS_START = date(2022, 1, 1)
PAPER_OOS_END = date(2024, 12, 31)


@dataclass(frozen=True)
class AdaptiveTrendParams:
    lookback: int = 20
    theta_entry: float = 0.02
    theta_short: float = 0.02
    atr_period: int = 14
    atr_mult: float = 2.5
    lambda_long: float = 0.70
    taker_bps: float = 4.0
    max_bars: int = 200
    allow_short: bool = True


@dataclass
class AtTrade:
    symbol: str
    side: Side
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    net_return: float
    bars_held: int
    exit_reason: str


def load_6h(symbol: str, *, start: date | None = None, end: date | None = None) -> tuple[pd.DataFrame, str]:
    start = start or SPLIT.is_start
    end = end or SPLIT.oos_end
    df4, src = load_symbol(symbol, "4h", start=start, end=end)
    if df4.empty:
        return df4, src
    df6 = resample_ohlcv(df4, "6h")
    tag = f"{src}|4h->6h"
    return df6, tag


def momentum_series(close: pd.Series, lookback: int) -> pd.Series:
    lag = close.shift(lookback)
    return ((close - lag) / lag.replace(0, np.nan)).rename("mom")


def backtest_adaptivetrend_symbol(
    df: pd.DataFrame,
    symbol: str,
    p: AdaptiveTrendParams,
) -> tuple[pd.DataFrame, list[AtTrade]]:
    """One open position at a time per symbol (long or short)."""
    if df.empty:
        return pd.DataFrame(), []
    c = df["close"].astype(float)
    mom = momentum_series(c, p.lookback)
    atr_s = wilder_atr(df, p.atr_period)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    cost = p.taker_bps / 1e4

    trades: list[AtTrade] = []
    side: Side | None = None
    entry_px = stop = 0.0
    entry_time: pd.Timestamp | None = None
    entry_i = 0

    for i in range(1, len(df)):
        ts = df.index[i]
        if side is None:
            m_prev = float(mom.iloc[i - 1]) if np.isfinite(mom.iloc[i - 1]) else 0.0
            atr_prev = float(atr_s.iloc[i - 1])
            if not np.isfinite(atr_prev) or atr_prev <= 0:
                continue
            go_long = m_prev > p.theta_entry
            go_short = p.allow_short and m_prev < -p.theta_short
            if not go_long and not go_short:
                continue
            side = "long" if go_long else "short"
            entry_px = float(o.iloc[i]) * (1 + cost if side == "long" else 1 - cost)
            if side == "long":
                stop = entry_px - p.atr_mult * atr_prev
            else:
                stop = entry_px + p.atr_mult * atr_prev
            entry_time = ts
            entry_i = i
            continue

        atr_i = float(atr_s.iloc[i]) if np.isfinite(atr_s.iloc[i]) else float(atr_s.iloc[i - 1])
        hi, lo, cl, op = float(h.iloc[i]), float(l.iloc[i]), float(c.iloc[i]), float(o.iloc[i])

        if side == "long" and np.isfinite(atr_i):
            stop = max(stop, cl - p.atr_mult * atr_i)
        elif side == "short" and np.isfinite(atr_i):
            stop = min(stop, cl + p.atr_mult * atr_i)

        exit_px: float | None = None
        reason = ""
        if side == "long":
            if op < stop:
                exit_px = op * (1 - cost)
                reason = "gap_stop"
            elif lo <= stop:
                exit_px = stop * (1 - cost)
                reason = "stop"
        else:
            if op > stop:
                exit_px = op * (1 + cost)
                reason = "gap_stop"
            elif hi >= stop:
                exit_px = stop * (1 + cost)
                reason = "stop"

        if exit_px is None and (i - entry_i) >= p.max_bars:
            exit_px = cl * (1 - cost if side == "long" else 1 + cost)
            reason = "time"

        if exit_px is None:
            continue

        if side == "long":
            net = (exit_px - entry_px) / entry_px
        else:
            net = (entry_px - exit_px) / entry_px
        trades.append(
            AtTrade(
                symbol=symbol,
                side=side,
                entry_time=entry_time or ts,
                exit_time=ts,
                entry_price=entry_px,
                exit_price=exit_px,
                net_return=float(net),
                bars_held=i - entry_i,
                exit_reason=reason,
            )
        )
        side = None

    out = pd.DataFrame({"close": c, "mom": mom, "atr": atr_s}, index=df.index)
    return out, trades


def _net_from_trades(trades: list[AtTrade], index: pd.DatetimeIndex) -> pd.Series:
    net = pd.Series(0.0, index=index)
    for t in trades:
        if t.exit_time in net.index:
            net.loc[t.exit_time] += t.net_return
    return net


def _apply_side_weights(net: pd.Series, trades: list[AtTrade], lam: float) -> pd.Series:
    """Scale each trade return by lambda (long) or (1-lambda) (short)."""
    out = pd.Series(0.0, index=net.index)
    for t in trades:
        w = lam if t.side == "long" else (1.0 - lam)
        if t.exit_time in out.index:
            out.loc[t.exit_time] += w * t.net_return
    return out


def eval_adaptivetrend_universe(
    symbols: list[str],
    p: AdaptiveTrendParams,
    *,
    warmup: int = WARMUP_BARS,
    paper_window: bool = False,
) -> dict[str, Any]:
    """Equal-weight combine per-symbol books; each symbol one position max."""
    per_sym: dict[str, Any] = {}
    oos_nets: list[pd.Series] = []
    is_nets: list[pd.Series] = []
    all_oos_trades: list[AtTrade] = []
    all_is_trades: list[AtTrade] = []

    for sym in symbols:
        df, src = load_6h(sym)
        if len(df) < warmup + p.lookback + 10:
            continue
        parts = split_frame(df, warmup=warmup)
        if paper_window:
            is_df = df.loc[: pd.Timestamp(PAPER_IS_END, tz="UTC")]
            oos_df = df.loc[pd.Timestamp(PAPER_OOS_START, tz="UTC") : pd.Timestamp(PAPER_OOS_END, tz="UTC")]
            seed = is_df.iloc[-warmup:] if len(is_df) >= warmup else is_df
            oos_seeded = pd.concat([seed, oos_df]).sort_index()
            oos_seeded = oos_seeded[~oos_seeded.index.duplicated(keep="last")]
        else:
            is_df = parts["is"]
            oos_seeded = parts["oos_seeded"]
            oos_df = parts["oos"]

        _, is_tr = backtest_adaptivetrend_symbol(is_df, sym, p)
        _, oos_tr = backtest_adaptivetrend_symbol(oos_seeded, sym, p)
        oos_start = pd.Timestamp(PAPER_OOS_START if paper_window else SPLIT.oos_start, tz="UTC")
        is_cut = is_df.index[min(warmup, len(is_df) - 1)]
        is_tr = [t for t in is_tr if t.entry_time >= is_cut]
        oos_tr = [t for t in oos_tr if t.entry_time >= oos_start]
        all_oos_trades.extend(oos_tr)
        all_is_trades.extend(is_tr)

        is_ix = is_df.index[warmup:]
        is_net = _apply_side_weights(_net_from_trades(is_tr, is_ix), is_tr, p.lambda_long)
        oos_net = _apply_side_weights(_net_from_trades(oos_tr, oos_df.index), oos_tr, p.lambda_long)
        if len(symbols) > 1:
            is_net = is_net / len(symbols)
            oos_net = oos_net / len(symbols)
        is_nets.append(is_net)
        oos_nets.append(oos_net)
        per_sym[sym] = {
            "source": src,
            "oos_trades": len(oos_tr),
            "oos_long": sum(1 for t in oos_tr if t.side == "long"),
            "oos_short": sum(1 for t in oos_tr if t.side == "short"),
        }

    if not oos_nets:
        empty = pd.Series(dtype=float)
        return {"params": p.__dict__, "per_symbol": {}, "is": kpis(empty, empty), "oos": kpis(empty, empty)}

    is_combined = pd.concat(is_nets, axis=1).fillna(0.0).sum(axis=1)
    oos_combined = pd.concat(oos_nets, axis=1).fillna(0.0).sum(axis=1)
    is_eq = (1.0 + is_combined).cumprod()
    oos_eq = (1.0 + oos_combined).cumprod()
    ann = 365 * 4  # ~6h bars per day proxy for vol scaling footnote; KPI sharpe uses bar returns

    longs = [t for t in all_oos_trades if t.side == "long"]
    shorts = [t for t in all_oos_trades if t.side == "short"]

    def _att(trs: list[AtTrade]) -> dict[str, float]:
        if not trs:
            return {"n": 0, "avg_ret_pct": 0.0}
        r = np.array([t.net_return for t in trs])
        return {"n": len(trs), "avg_ret_pct": float(r.mean() * 100), "win_rate": float((r > 0).mean())}

    return {
        "params": p.__dict__,
        "per_symbol": per_sym,
        "is": kpis(is_combined, is_eq, trades=len(all_is_trades), ann=ann),
        "oos": kpis(oos_combined, oos_eq, trades=len(all_oos_trades), ann=ann),
        "oos_long": _att(longs),
        "oos_short": _att(shorts),
        "oos_net": oos_combined,
        "oos_eq": oos_eq,
        "paper_window": paper_window,
    }
