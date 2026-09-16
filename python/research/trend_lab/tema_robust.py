"""TEMA robustness: walk-forward folds, DF neighborhood, IS-only sensitivity.

Never pass true OOS into a grid or Optuna. Frozen 9/90/199 is always the
baseline row. 2022 is the stress fold, not a fit window.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Iterable

import pandas as pd

from .metrics import kpis
from .optimize import df_neighborhood_score
from .protocol import WARMUP_BARS, inner_validation_start
from .tema_system import (
    TemaParams,
    daily_equity,
    daily_net,
    tema_bar_equity,
    tema_trades,
    trade_stats,
)

FROZEN = TemaParams()  # 9/90/199, SL 1.5 / TP 2.5

# Expanding IS → next calendar year. 2022 is the crash fold.
DEFAULT_FOLDS: list[tuple[str, str, str, str]] = [
    ("2020-01-01", "2020-12-31", "2021-01-01", "2021-12-31"),
    ("2020-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
    ("2020-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
    ("2020-01-01", "2023-12-31", "2024-01-01", "2026-12-31"),
]


def seed_window(full: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, *, warmup: int = WARMUP_BARS) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """OHLCV for [start, end] prefixed with last ``warmup`` bars before start."""
    window = full.loc[start:end]
    before = full.loc[: start - pd.Timedelta(milliseconds=1)]
    seed = before.iloc[-warmup:] if len(before) > warmup else before
    seeded = pd.concat([seed, window])
    seeded = seeded[~seeded.index.duplicated(keep="last")].sort_index()
    return seeded, window.index


def trades_in_window(
    full: pd.DataFrame,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    params: TemaParams,
) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    if end_ts.hour == 0 and end_ts.minute == 0:
        end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    seeded, idx = seed_window(full, start_ts, end_ts)
    tr = tema_trades(seeded, params)
    if tr.empty:
        return tr, idx
    tr = tr.loc[(tr["entry_time"] >= start_ts) & (tr["entry_time"] <= end_ts)].reset_index(drop=True)
    return tr, idx


def daily_kpis(index: pd.DatetimeIndex, trades: pd.DataFrame, *, start_eq: float = 10_000.0) -> dict[str, float]:
    bar = tema_bar_equity(index, trades, start_eq=start_eq)
    d_eq = daily_equity(bar["equity"])
    d_net = daily_net(bar["equity"])
    if d_eq.empty:
        return {**kpis(pd.Series(dtype=float), pd.Series(dtype=float), trades=int(len(trades))), **trade_stats(trades)}
    return {**kpis(d_net, d_eq, trades=int(len(trades))), **trade_stats(trades)}


def run_tema_daily(ohlcv: pd.DataFrame, params: TemaParams | dict[str, float]) -> pd.DataFrame:
    """``net`` / ``equity`` on daily marks — DF neighborhood runner."""
    if isinstance(params, dict):
        p = TemaParams(
            fast=int(params.get("fast", FROZEN.fast)),
            mid=int(params.get("mid", FROZEN.mid)),
            slow=int(params.get("slow", FROZEN.slow)),
            min_adx=float(params.get("min_adx", FROZEN.min_adx)),
            min_atr_pct=float(params.get("min_atr_pct", FROZEN.min_atr_pct)),
            max_atr_pct=float(params.get("max_atr_pct", FROZEN.max_atr_pct)),
            sl_atr=float(params.get("sl_atr", FROZEN.sl_atr)),
            tp_atr=float(params.get("tp_atr", FROZEN.tp_atr)),
            leverage=float(params.get("leverage", FROZEN.leverage)),
            stake=float(params.get("stake", FROZEN.stake)),
        )
    else:
        p = params
    tr = tema_trades(ohlcv, p)
    bar = tema_bar_equity(ohlcv.index, tr)
    d_eq = daily_equity(bar["equity"])
    d_net = daily_net(bar["equity"])
    if d_eq.empty:
        return pd.DataFrame({"net": pd.Series(dtype=float), "equity": pd.Series(dtype=float)})
    return pd.DataFrame({"net": d_net, "equity": d_eq})


def walk_forward(
    full: pd.DataFrame,
    params: TemaParams = FROZEN,
    folds: Iterable[tuple[str, str, str, str]] = DEFAULT_FOLDS,
) -> pd.DataFrame:
    """Frozen (or given) params on each fold OOS. Params are not re-fit here."""
    rows = []
    for is_a, is_b, oos_a, oos_b in folds:
        tr, idx = trades_in_window(full, oos_a, oos_b, params)
        k = daily_kpis(idx, tr)
        rows.append({
            "is": f"{is_a}→{is_b}",
            "oos": f"{oos_a}→{oos_b}",
            "stress": "2022" in oos_a,
            **k,
        })
    return pd.DataFrame(rows)


def sensitivity_periods(is_ohlcv: pd.DataFrame, *, leverage: float = 10.0) -> pd.DataFrame:
    rows = []
    triples = (
        (5, 34, 150), (8, 55, 200), (9, 90, 199), (13, 55, 200),
        (13, 90, 199), (21, 90, 199), (9, 55, 199), (9, 90, 250),
    )
    for fast, mid, slow in triples:
        if not (fast < mid < slow):
            continue
        p = TemaParams(fast=fast, mid=mid, slow=slow, leverage=leverage)
        k = daily_kpis(is_ohlcv.index, tema_trades(is_ohlcv, p))
        rows.append({"fast": fast, "mid": mid, "slow": slow, "frozen": (fast, mid, slow) == (9, 90, 199), **k})
    return pd.DataFrame(rows).sort_values("sharpe", ascending=False)


def sensitivity_sl_tp(is_ohlcv: pd.DataFrame, *, leverage: float = 10.0) -> pd.DataFrame:
    rows = []
    for sl in (1.0, 1.2, 1.5, 2.0, 2.5):
        for tp in (1.5, 2.0, 2.5, 3.0, 3.5):
            if tp <= sl:
                continue
            p = replace(FROZEN, sl_atr=sl, tp_atr=tp, leverage=leverage)
            k = daily_kpis(is_ohlcv.index, tema_trades(is_ohlcv, p))
            rows.append({"sl_atr": sl, "tp_atr": tp, "frozen": sl == 1.5 and tp == 2.5, **k})
    return pd.DataFrame(rows).sort_values("sharpe", ascending=False)


def sensitivity_gates(is_ohlcv: pd.DataFrame, *, leverage: float = 10.0) -> pd.DataFrame:
    rows = []
    for adx_min in (12.0, 18.0, 20.0, 25.0):
        for atr_min in (0.2, 0.4, 0.8):
            p = replace(FROZEN, min_adx=adx_min, min_atr_pct=atr_min, leverage=leverage)
            k = daily_kpis(is_ohlcv.index, tema_trades(is_ohlcv, p))
            rows.append({"min_adx": adx_min, "min_atr_pct": atr_min, "frozen": adx_min == 20.0 and atr_min == 0.4, **k})
    return pd.DataFrame(rows).sort_values("sharpe", ascending=False)


def frozen_neighborhood(
    is_ohlcv: pd.DataFrame,
    *,
    which: str = "periods",
) -> dict[str, Any]:
    """DF neighborhood around frozen TEMA. Inner-IS val only. Never OOS.

    ``which='periods'``: fast/mid/slow (27 neighbors).
    ``which='exits'``: sl/tp/min_adx (27 neighbors).
    """
    inner = inner_validation_start(is_ohlcv.index)
    if which == "exits":
        center = {
            "sl_atr": float(FROZEN.sl_atr),
            "tp_atr": float(FROZEN.tp_atr),
            "min_adx": float(FROZEN.min_adx),
        }
        steps = {
            "sl_atr": [1.2, 1.5, 1.8],
            "tp_atr": [2.2, 2.5, 2.8],
            "min_adx": [18.0, 20.0, 22.0],
        }
    else:
        center = {
            "fast": float(FROZEN.fast),
            "mid": float(FROZEN.mid),
            "slow": float(FROZEN.slow),
        }
        steps = {
            "fast": [7.0, 9.0, 13.0],
            "mid": [70.0, 90.0, 110.0],
            "slow": [180.0, 199.0, 220.0],
        }
    return df_neighborhood_score(
        is_ohlcv=is_ohlcv,
        inner_val_start=inner,
        center=center,
        neighbor_steps=steps,
        run_fn=run_tema_daily,
        min_is_sharpe=0.3,
    )


def frozen_center() -> dict[str, float]:
    p = asdict(FROZEN)
    return {k: float(p[k]) if isinstance(p[k], (int, float)) else p[k] for k in p}
