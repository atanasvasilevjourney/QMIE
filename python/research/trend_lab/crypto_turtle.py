"""Roman-karpovich/crypto-turtle style Turtle (Donchian) validation.

Reference rules (daily, prior-window channels):
  * Long entry:  close > prev 20-day high
  * Long exit:   close < prev 10-day low  (also initial stop reference)
  * Short entry: close < prev 20-day low
  * Short exit:  close > prev 10-day high
  * Long confirm:  RSI(14) > 50 and ATR(14)/close > 0.5%
  * Short confirm: RSI(14) < 50 and ATR(14)/close > 0.5%

Research-only. No Bybit / no live orders. Uses Vision 1d OHLCV and QMIE IS/OOS
protocol. Intrabar stop uses high/low path (stop before signal exit).

Does not retune live ``W_*``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

Side = Literal["long", "short"]


@dataclass(frozen=True)
class TurtleCryptoParams:
    entry_lookback: int = 20
    exit_lookback: int = 10
    atr_period: int = 14
    rsi_period: int = 14
    rsi_long_min: float = 50.0
    rsi_short_max: float = 50.0
    min_atr_pct: float = 0.005
    slippage_pct: float = 0.001
    commission_pct: float = 0.001
    use_volume_filter: bool = False
    vol_period: int = 20
    vol_multiplier: float = 1.2


@dataclass
class TurtleTrade:
    direction: Side
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    profit_pct: float
    exit_reason: str
    bars_held: int


def _atr_simple(df: pd.DataFrame, period: int) -> pd.Series:
    """Simple TR mean — matches crypto-turtle ``compute_atr``."""
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _rsi_simple(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def turtle_signal_frame(df: pd.DataFrame, p: TurtleCryptoParams) -> pd.DataFrame:
    """Channel levels and boolean entry/exit flags (bar close)."""
    hi_e = df["high"].rolling(p.entry_lookback).max()
    lo_e = df["low"].rolling(p.entry_lookback).min()
    hi_x = df["high"].rolling(p.exit_lookback).max()
    lo_x = df["low"].rolling(p.exit_lookback).min()
    prev_20_high = hi_e.shift(1)
    prev_20_low = lo_e.shift(1)
    prev_10_high = hi_x.shift(1)
    prev_10_low = lo_x.shift(1)
    c = df["close"]
    atr = _atr_simple(df, p.atr_period)
    rsi = _rsi_simple(c, p.rsi_period)
    atr_pct = atr / c.replace(0, np.nan)
    vol_ok = pd.Series(True, index=df.index)
    if p.use_volume_filter and "volume" in df.columns:
        vol_avg = df["volume"].rolling(p.vol_period).mean()
        vol_ok = df["volume"] > (p.vol_multiplier * vol_avg)
    long_entry = (c > prev_20_high) & (rsi > p.rsi_long_min) & (atr_pct > p.min_atr_pct) & vol_ok
    short_entry = (c < prev_20_low) & (rsi < p.rsi_short_max) & (atr_pct > p.min_atr_pct) & vol_ok
    long_exit = c < prev_10_low
    short_exit = c > prev_10_high
    return pd.DataFrame(
        {
            "close": c,
            "prev_20d_high": prev_20_high,
            "prev_20d_low": prev_20_low,
            "prev_10d_high": prev_10_high,
            "prev_10d_low": prev_10_low,
            "atr": atr,
            "atr_pct": atr_pct,
            "rsi": rsi,
            "long_entry": long_entry.fillna(False),
            "short_entry": short_entry.fillna(False),
            "long_exit": long_exit.fillna(False),
            "short_exit": short_exit.fillna(False),
        },
        index=df.index,
    )


def backtest_turtle_crypto(df: pd.DataFrame, p: TurtleCryptoParams) -> tuple[pd.DataFrame, list[TurtleTrade]]:
    """Daily replay: enter next open after confirmed signal; stop at entry 10d level."""
    sig = turtle_signal_frame(df, p)
    trades: list[TurtleTrade] = []
    pos: Side | None = None
    entry_price = 0.0
    entry_time: pd.Timestamp | None = None
    stop = 0.0
    entry_i = 0

    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)

    for i in range(1, len(df)):
        ts = df.index[i]
        if pos is None:
            le = bool(sig["long_entry"].iloc[i - 1])
            se = bool(sig["short_entry"].iloc[i - 1])
            if not le and not se:
                continue
            side: Side = "long" if le else "short"
            fill = float(o.iloc[i]) * (1 + p.slippage_pct if side == "long" else 1 - p.slippage_pct)
            if side == "long":
                stop = float(sig["prev_10d_low"].iloc[i - 1])
            else:
                stop = float(sig["prev_10d_high"].iloc[i - 1])
            if not np.isfinite(stop) or stop <= 0:
                continue
            pos = side
            entry_price = fill
            entry_time = ts
            entry_i = i
            continue

        open_i, high_i, low_i, close_i = map(float, (o.iloc[i], h.iloc[i], l.iloc[i], c.iloc[i]))
        exit_price: float | None = None
        reason = ""

        if pos == "long":
            path = [open_i, low_i, close_i]
            for px in path:
                if px <= stop:
                    exit_price = stop * (1 - p.slippage_pct)
                    reason = "stop"
                    break
            if exit_price is None and bool(sig["long_exit"].iloc[i]):
                exit_price = close_i * (1 - p.slippage_pct)
                reason = "signal_exit"
        else:
            path = [open_i, high_i, close_i]
            for px in path:
                if px >= stop:
                    exit_price = stop * (1 + p.slippage_pct)
                    reason = "stop"
                    break
            if exit_price is None and bool(sig["short_exit"].iloc[i]):
                exit_price = close_i * (1 + p.slippage_pct)
                reason = "signal_exit"

        if exit_price is None:
            continue

        if pos == "long":
            gross = (exit_price - entry_price) / entry_price
        else:
            gross = (entry_price - exit_price) / entry_price
        comm = p.commission_pct * 2
        profit_pct = gross - comm
        trades.append(
            TurtleTrade(
                direction=pos,
                entry_time=entry_time or ts,
                exit_time=ts,
                entry_price=entry_price,
                exit_price=exit_price,
                profit_pct=float(profit_pct),
                exit_reason=reason,
                bars_held=i - entry_i,
            )
        )
        pos = None

    out = sig.copy()
    out["position"] = 0
    return out, trades


def backtest_summary(trades: list[TurtleTrade]) -> dict[str, float]:
    if not trades:
        return {"total_trades": 0, "win_rate_pct": 0.0, "total_profit_pct": 0.0, "avg_profit_pct": 0.0}
    profits = np.array([t.profit_pct for t in trades])
    wins = profits > 0
    return {
        "total_trades": float(len(trades)),
        "win_rate_pct": float(wins.mean() * 100),
        "total_profit_pct": float(profits.sum() * 100),
        "avg_profit_pct": float(profits.mean() * 100),
    }


def attribution_by_side(trades: list[TurtleTrade]) -> pd.DataFrame:
    rows = []
    for side in ("long", "short"):
        sub = [t for t in trades if t.direction == side]
        s = backtest_summary(sub)
        s["side"] = side
        rows.append(s)
    return pd.DataFrame(rows)


def export_signals_csv(df: pd.DataFrame, sig: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = sig.copy()
    out.insert(0, "open_time", df.index)
    out.to_csv(path, index=False)


def plot_turtle_signals(
    df: pd.DataFrame,
    sig: pd.DataFrame,
    symbol: str,
    path: Path,
) -> None:
    """crypto-turtle style: exits first, entries on top."""
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    t = df.index
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(t, sig["close"], color="black", linewidth=1, label="Close")
    ax.plot(t, sig["prev_20d_high"], color="green", linestyle="--", label="Prev 20d High")
    ax.plot(t, sig["prev_20d_low"], color="red", linestyle="--", label="Prev 20d Low")
    ax.plot(t, sig["prev_10d_high"], color="orange", linestyle=":", label="Prev 10d High")
    ax.plot(t, sig["prev_10d_low"], color="blue", linestyle=":", label="Prev 10d Low")
    le = sig["long_exit"]
    ax.scatter(t[le], sig.loc[le, "close"], marker="v", color="red", s=60, label="Long Exit")
    se = sig["short_exit"]
    ax.scatter(t[se], sig.loc[se, "close"], marker="^", color="orange", s=60, label="Short Exit")
    li = sig["long_entry"]
    ax.scatter(t[li], sig.loc[li, "close"], marker="^", color="green", s=80, label="Long Entry")
    si = sig["short_entry"]
    off = sig.loc[si, "close"] * 0.998
    ax.scatter(t[si], off, marker="v", color="blue", s=80, label="Short Entry")
    ax.set_title(f"Historical Signals — {symbol} (crypto-turtle style)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_backtest_trades(
    df: pd.DataFrame,
    trades: list[TurtleTrade],
    symbol: str,
    path: Path,
) -> None:
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(df.index, df["close"], color="black", linewidth=1, label="Close")
    seen: set[str] = set()
    for tr in trades:
        if tr.direction == "long":
            ax.scatter(tr.entry_time, tr.entry_price, marker="^", color="green", s=80)
            ax.scatter(tr.exit_time, tr.exit_price, marker="v", color="red", s=80)
            lbl_e, lbl_x = "Long Entry", "Long Exit"
        else:
            ax.scatter(tr.entry_time, tr.entry_price, marker="v", color="red", s=80)
            ax.scatter(tr.exit_time, tr.exit_price, marker="^", color="green", s=80)
            lbl_e, lbl_x = "Short Entry", "Short Exit"
        if lbl_e not in seen:
            ax.scatter([], [], marker="^" if tr.direction == "long" else "v", color="green", label=lbl_e)
            seen.add(lbl_e)
        if lbl_x not in seen:
            ax.scatter([], [], marker="v" if tr.direction == "long" else "^", color="red", label=lbl_x)
            seen.add(lbl_x)
        ax.annotate(
            f"{tr.profit_pct * 100:.2f}%",
            xy=(tr.exit_time, tr.exit_price),
            fontsize=7,
            color="red" if tr.profit_pct < 0 else "green",
        )
    ax.set_title(f"Backtest — {symbol}")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def eval_turtle_crypto(
    full: pd.DataFrame,
    p: TurtleCryptoParams,
    *,
    warmup: int,
) -> dict[str, Any]:
    from .metrics import kpis
    from .protocol import SPLIT, split_frame

    parts = split_frame(full, warmup=warmup)
    _, is_trades = backtest_turtle_crypto(parts["is"], p)
    _, oos_trades = backtest_turtle_crypto(parts["oos_seeded"], p)
    oos_start = pd.Timestamp(SPLIT.oos_start, tz="UTC")
    is_cut = parts["is"].index[min(warmup, len(parts["is"]) - 1)]
    is_tr = [t for t in is_trades if t.entry_time >= is_cut]
    oos_tr = [t for t in oos_trades if t.entry_time >= oos_start]

    def _net(trs: list[TurtleTrade], index: pd.DatetimeIndex) -> pd.Series:
        net = pd.Series(0.0, index=index)
        for t in trs:
            if t.exit_time in net.index:
                net.loc[t.exit_time] += t.profit_pct
        return net

    is_net = _net(is_tr, parts["is"].index[warmup:])
    oos_net = _net(oos_tr, parts["oos"].index)
    is_eq = (1.0 + is_net).cumprod()
    oos_eq = (1.0 + oos_net).cumprod()
    sig_full = turtle_signal_frame(full, p)

    return {
        "params": p.__dict__,
        "is": kpis(is_net, is_eq, trades=len(is_tr)),
        "oos": kpis(oos_net, oos_eq, trades=len(oos_tr)),
        "is_summary": backtest_summary(is_tr),
        "oos_summary": backtest_summary(oos_tr),
        "oos_attribution": attribution_by_side(oos_tr),
        "is_trades": is_tr,
        "oos_trades": oos_tr,
        "signal_frame": sig_full,
    }
