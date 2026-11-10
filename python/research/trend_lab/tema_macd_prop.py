"""TEMA + MACD daily system for prop research (QQQ / GLD / BTC).

Grid-searches **Calmar** on IS only; optional IS max-DD floor (FTMO static proxy).
Does not retune live QMIE ``W_*`` or 4h frozen TEMA promotion path.

Leverage defaults to **1×** with ``compound_trades`` and ``risk_frac`` for prop-style
isolated risk per ticket (not 10× crypto lab).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from datetime import date
from itertools import product
from typing import Any, Iterator

import numpy as np
import pandas as pd

from scanner.indicators import adx, atr, rsi

from .data import load_etf, load_symbol, mixed_panel
from .features import macd, tma_agreement
from .metrics import kpis_from_net
from .protocol import SPLIT
from .tema_system import compound_trades, tema_bar_equity

ANN_PROP = 252
PROP_START_EQ = 100_000.0


@dataclass(frozen=True)
class TemaMacdParams:
    fast: int = 9
    mid: int = 90
    slow: int = 199
    min_adx: float = 20.0
    min_atr_pct: float = 0.4
    max_atr_pct: float = 4.0
    sl_atr: float = 1.5
    tp_atr: float = 2.5
    max_bars: int = 60
    leverage: float = 1.0
    stake: float = 100.0
    cost_bps: float = 2.0
    agree_min: int = 1
    use_macd: bool = True
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    macd_hist_min: float = 0.0
    risk_frac: float = 0.01


def close_to_ohlcv(close: pd.Series) -> pd.DataFrame:
    """Synthetic OHLC from close (ETFs). Causal; for ATR/ADX only."""
    c = close.astype(float).dropna()
    o = c.shift(1).fillna(c)
    hl = pd.concat([o, c], axis=1)
    h = hl.max(axis=1) * 1.001
    l = hl.min(axis=1) * 0.999
    return pd.DataFrame(
        {"open": o, "high": h, "low": l, "close": c, "volume": 1.0},
        index=c.index,
    )


def load_trio_daily_ohlcv(
    *,
    start: date | None = None,
    end: date | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Daily OHLCV for BTC (Vision), QQQ, GLD (ETF close → synthetic OHLC)."""
    start = start or SPLIT.is_start
    end = end or SPLIT.oos_end
    sources: dict[str, str] = {}
    out: dict[str, pd.DataFrame] = {}
    btc_df, src = load_symbol("BTCUSDT", "1d", start=start, end=end)
    sources["BTC"] = src
    out["BTC"] = btc_df[["open", "high", "low", "close", "volume"]].astype(float)
    for t in ("QQQ", "GLD"):
        s, src = load_etf(t)
        sources[t] = src
        s = s.loc[pd.Timestamp(start, tz="UTC") : pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
        out[t] = close_to_ohlcv(s)
    return out, sources


def tema_macd_trades(df: pd.DataFrame, p: TemaMacdParams) -> pd.DataFrame:
    """Long-only TEMA stack + optional MACD histogram gate. One position at a time."""
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
    if p.use_macd:
        hist = macd(c, p.macd_fast, p.macd_slow, p.macd_signal)["macd_hist"]
        long_ok = long_ok & (hist > p.macd_hist_min)
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
        if i + 1 >= n:
            break
        entry_i = i + 1
        entry = float(c_a[i])
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
            exit_i = min(n, entry_i + p.max_bars) - 1
            outcome, exit_px = "TIME", float(c_a[exit_i])
        ret = (exit_px - entry) / entry
        notional = p.stake * p.leverage
        pnl = notional * ret
        liquidated = pnl < -p.stake
        if liquidated:
            pnl = -p.stake
        pnl -= notional * (p.cost_bps / 1e4) * 2
        r_mult = (exit_px - entry) / (entry - sl) if entry > sl else np.nan
        rows.append({
            "entry_time": idx[i],
            "exit_time": idx[exit_i],
            "entry": entry,
            "exit": exit_px,
            "outcome": outcome,
            "ret": ret,
            "pnl": pnl,
            "liquidated": liquidated,
            "r": r_mult,
            "bars": int(exit_i - entry_i + 1),
        })
        i = exit_i + 1
    return pd.DataFrame(rows)


def _prop_net(index: pd.DatetimeIndex, trades: pd.DataFrame, p: TemaMacdParams) -> pd.Series:
    if trades.empty:
        return pd.Series(0.0, index=index, name="net")
    tr = compound_trades(
        trades,
        start_eq=PROP_START_EQ,
        risk_frac=p.risk_frac,
        leverage=p.leverage,
        cost_bps=p.cost_bps,
    )
    bar = tema_bar_equity(index, tr, start_eq=PROP_START_EQ)
    return bar["net"].fillna(0.0)


def eval_tema_macd_prop(
    ohlcv: pd.DataFrame,
    p: TemaMacdParams,
    *,
    is_end: pd.Timestamp,
    ann: int = ANN_PROP,
) -> dict[str, Any]:
    trades = tema_macd_trades(ohlcv, p)
    net = _prop_net(ohlcv.index, trades, p)
    cut = pd.Timestamp(is_end, tz="UTC") if is_end.tzinfo is None else is_end
    oos_start = cut + pd.Timedelta(days=1)
    return {
        "params": asdict(p),
        "n_trades_full": int(len(trades)),
        "is": kpis_from_net(net.loc[:cut], ann=ann),
        "oos": kpis_from_net(net.loc[oos_start:], ann=ann),
        "net": net,
        "trades": trades,
    }


def _param_field_names() -> set[str]:
    return {f.name for f in fields(TemaMacdParams)}


def iter_grid(*, quick: bool = True) -> Iterator[TemaMacdParams]:
    """Brute-force grid. IS-only scoring in ``brute_force_calmar_is``."""
    if quick:
        tema_triples = [(9, 90, 199), (9, 60, 120), (12, 50, 150)]
        macd_sets = [(12, 26, 9), (8, 21, 9)]
        sls = (1.25, 1.5, 2.0)
        tps = (2.0, 2.5, 3.0)
        adxs = (15.0, 20.0, 25.0)
        agree = (1, 2)
        use_macd = (False, True)
    else:
        tema_triples = [(9, 90, 199), (9, 60, 120), (10, 80, 160), (12, 50, 150)]
        macd_sets = [(12, 26, 9), (8, 21, 9), (10, 30, 9)]
        sls = (1.0, 1.25, 1.5, 2.0)
        tps = (2.0, 2.5, 3.0, 3.5)
        adxs = (15.0, 20.0, 25.0)
        agree = (1, 2)
        use_macd = (False, True)
    base = TemaMacdParams()
    for (fa, mi, sl), (mf, ms, msig), sl_atr, tp_atr, min_adx, ag, um in product(
        tema_triples, macd_sets, sls, tps, adxs, agree, use_macd,
    ):
        yield replace(
            base,
            fast=fa,
            mid=mi,
            slow=sl,
            macd_fast=mf,
            macd_slow=ms,
            macd_signal=msig,
            sl_atr=sl_atr,
            tp_atr=tp_atr,
            min_adx=min_adx,
            agree_min=ag,
            use_macd=um,
        )


def brute_force_calmar_is(
    ohlcv: pd.DataFrame,
    *,
    is_end: pd.Timestamp,
    quick: bool = True,
    max_dd_floor: float = -0.10,
    min_trades: int = 8,
    ann: int = ANN_PROP,
) -> tuple[pd.DataFrame, TemaMacdParams | None]:
    """Maximize Calmar on IS among combos with max_dd >= floor and min trades."""
    is_end = pd.Timestamp(is_end, tz="UTC") if is_end.tzinfo is None else is_end
    is_idx = ohlcv.index[ohlcv.index <= is_end]
    if len(is_idx) < 120:
        raise ValueError("IS too short for TEMA+MACD grid")
    is_df = ohlcv.loc[is_idx]
    names = _param_field_names()
    rows: list[dict[str, Any]] = []
    for p in iter_grid(quick=quick):
        tr = tema_macd_trades(is_df, p)
        if len(tr) < min_trades:
            continue
        net = _prop_net(is_df.index, tr, p)
        k = kpis_from_net(net, ann=ann)
        if not np.isfinite(k.get("calmar", np.nan)):
            continue
        if k["max_dd"] < max_dd_floor:
            continue
        row = {k: getattr(p, k) for k in names}
        row.update(k)
        row["n_trades"] = len(tr)
        rows.append(row)
    if not rows:
        return pd.DataFrame(), None
    table = pd.DataFrame(rows).sort_values(["calmar", "sharpe"], ascending=False)
    best_row = table.iloc[0]
    best = TemaMacdParams(**{k: best_row[k] for k in names})
    return table, best


def ftmo_proxy(net: pd.Series, *, daily_loss: float = 0.05) -> dict[str, float]:
    net = net.fillna(0.0)
    eq = PROP_START_EQ * (1.0 + net).cumprod()
    bal = eq.shift(1).fillna(PROP_START_EQ)
    day_pnl_pct = (bal * net) / bal
    return {
        "worst_daily_loss_pct": float(day_pnl_pct.min()),
        "days_breach_5pct": int((day_pnl_pct < -daily_loss).sum()),
    }
