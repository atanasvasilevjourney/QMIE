"""Approach 1 — spot book: 1D EMA alignment + Donchian breakout + confluence.

Mirrors QMIE Trend Radar / DailyExpansion intent:
  * take on spot (leverage = 1)
  * prior-box / prior-channel stop
  * no TEMA ATR TP
  * closed-bar only; held = signal.shift(1)

Does not dispatch QMIE-DailyExpansion and does not retune W_*.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from scanner.indicators import adx, ema, rsi

from .features import alma, donchian, kama, macd, zscore


@dataclass(frozen=True)
class SpotParams:
    ema_fast: int = 9
    ema_slow: int = 199
    donchian: int = 20
    min_adx: float = 20.0
    rsi_max: float = 75.0
    use_kama: bool = False
    use_macd: bool = False
    use_zscore: bool = False
    use_alma: bool = False
    z_max: float = 2.0
    cost_bps: float = 8.0  # spot taker-ish


def spot_signal(df: pd.DataFrame, p: SpotParams) -> pd.DataFrame:
    c = df["close"]
    e_f = ema(c, p.ema_fast)
    e_s = ema(c, p.ema_slow)
    aligned = e_f > e_s
    don = donchian(df, p.donchian)
    breakout = c > don["donch_high"]
    pdi, mdi, adx_s = adx(df, 14)
    trend = (adx_s >= p.min_adx) & (pdi > mdi)
    rsi_ok = rsi(c, 14) <= p.rsi_max
    extra = pd.Series(True, index=df.index)
    if p.use_kama:
        ks, _ = kama(c, n=10)
        kl, _ = kama(c, n=60)
        extra = extra & (ks > kl)
    if p.use_macd:
        extra = extra & (macd(c)["macd_hist"] > 0)
    if p.use_zscore:
        extra = extra & (zscore(c, 20) <= p.z_max)
    if p.use_alma:
        extra = extra & (alma(c, 9) > alma(c, 9).shift(1))
    raw = (aligned & breakout & trend & rsi_ok & extra).astype(float)
    # stay long while aligned and not below prior box
    stay = aligned & (c > don["donch_low"]) & trend
    pos = raw.copy()
    # once in, hold while stay; binary ensemble (full port)
    held_flag = 0.0
    out = np.zeros(len(df))
    raw_a = raw.to_numpy()
    stay_a = stay.fillna(False).to_numpy()
    for i in range(len(df)):
        if held_flag > 0:
            held_flag = 1.0 if stay_a[i] else 0.0
        elif raw_a[i] == 1:
            held_flag = 1.0
        out[i] = held_flag
    signal = pd.Series(out, index=df.index, name="signal")
    held = signal.shift(1).fillna(0.0).rename("held")
    ret = c.pct_change().fillna(0.0)
    turnover = held.diff().abs().fillna(held.abs())
    net = held * ret - turnover * (p.cost_bps / 1e4)
    return pd.DataFrame({
        "close": c,
        "signal": signal,
        "held": held,
        "ret": ret,
        "net": net,
        "equity": (1.0 + net).cumprod(),
        "aligned": aligned.astype(float),
        "breakout": breakout.astype(float),
        "adx": adx_s,
        "donch_low": don["donch_low"],
        "donch_high": don["donch_high"],
    })
