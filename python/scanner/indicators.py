"""
QMIE — Indicator Math  (Pine v6 compatible)
===========================================
CRITICAL: every indicator here must produce values that match
TradingView's Pine v6 implementations bar-for-bar on the same
candle data. Any drift here → server alerts disagree with the
chart visualizer → user loses trust.

Key gotcha: Pine's `ta.atr`, `ta.rma`, `ta.rsi`, `ta.adx` all use
**Wilders smoothing (RMA)**, NOT a standard EMA.
RMA(n) ≡ pandas.ewm(alpha=1/n, adjust=False).
Plain pandas `.ewm(span=n)` uses alpha=2/(n+1) and is WRONG here.

We deliberately avoid pandas_ta / ta-lib for two reasons:
  1. Their conventions differ subtly from Pine (offsets, seeds).
  2. Heavy native deps complicate deployment.

Inputs are always a pandas DataFrame with columns:
  open, high, low, close, volume   (float64)
  index = pd.DatetimeIndex (UTC)

All functions return Series aligned to the input index.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════
#  Wilders' RMA — the building block for ATR, RSI, ADX
# ═══════════════════════════════════════════════════════════════════════
def rma(series: pd.Series, length: int) -> pd.Series:
    """Pine `ta.rma` exact: y[length-1] = SMA(0..length-1), then
    y[t] = (1/length)*x[t] + (1 - 1/length)*y[t-1].

    Implementation note: pandas `ewm(adjust=False)` seeds with x[0],
    not the SMA, which causes a small but nonzero divergence from
    Pine for the first ~5×length bars. We seed manually for bit-exact
    parity with TradingView.
    """
    if length <= 0:
        raise ValueError("rma length must be > 0")
    arr = series.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)
    if n < length:
        return pd.Series(out, index=series.index, name=series.name)

    alpha = 1.0 / length
    one_minus_alpha = 1.0 - alpha
    # Seed at index `length-1` with SMA of first `length` values
    seed_window = arr[:length]
    if np.any(np.isnan(seed_window)):
        # Fall back to ewm if NaNs in seed window (very rare for OHLC)
        return series.ewm(alpha=alpha, adjust=False, min_periods=length).mean()
    out[length - 1] = float(seed_window.mean())
    for i in range(length, n):
        v = arr[i]
        if np.isnan(v):
            out[i] = out[i - 1]
        else:
            out[i] = alpha * v + one_minus_alpha * out[i - 1]
    return pd.Series(out, index=series.index, name=series.name)


# ═══════════════════════════════════════════════════════════════════════
#  EMA — used for the 200-EMA macro filter
# ═══════════════════════════════════════════════════════════════════════
def ema(series: pd.Series, length: int) -> pd.Series:
    """Pine `ta.ema`. alpha = 2/(length+1)."""
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


# ═══════════════════════════════════════════════════════════════════════
#  ATR — Pine `ta.atr(length)` ≡ RMA(TR, length)
# ═══════════════════════════════════════════════════════════════════════
def true_range(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return rma(true_range(df), length)


# ═══════════════════════════════════════════════════════════════════════
#  RSI — Pine `ta.rsi(close, length)`
#  Wilder's smoothing of gain/loss
# ═══════════════════════════════════════════════════════════════════════
def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.fillna(50.0)


# ═══════════════════════════════════════════════════════════════════════
#  ADX — Pine `ta.adx`. Returns (plus_di, minus_di, adx).
# ═══════════════════════════════════════════════════════════════════════
def adx(df: pd.DataFrame, length: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    high, low = df["high"], df["low"]
    up_move   = high.diff()
    down_move = -low.diff()

    plus_dm  = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
                         index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
                         index=df.index)

    tr  = true_range(df)
    atr_ = rma(tr, length)
    plus_di  = 100.0 * rma(plus_dm,  length) / atr_.replace(0, np.nan)
    minus_di = 100.0 * rma(minus_dm, length) / atr_.replace(0, np.nan)

    dx = (100.0 * (plus_di - minus_di).abs() /
          (plus_di + minus_di).replace(0, np.nan))
    adx_val = rma(dx.fillna(0.0), length)
    return plus_di.fillna(0.0), minus_di.fillna(0.0), adx_val.fillna(0.0)


# ═══════════════════════════════════════════════════════════════════════
#  Supertrend — matches Pine `ta.supertrend(factor, atrLen)`
#  Returns (supertrend_value, direction)
#    direction:  +1 = uptrend (price above), -1 = downtrend
# ═══════════════════════════════════════════════════════════════════════
def supertrend(df: pd.DataFrame, factor: float, atr_len: int) -> tuple[pd.Series, pd.Series]:
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    n = len(df)
    if n == 0:
        idx = df.index
        return pd.Series(dtype=float, index=idx), pd.Series(dtype=int, index=idx)

    a = atr(df, atr_len).to_numpy()
    hl2 = (h + l) / 2.0
    upper_basic = hl2 + factor * a
    lower_basic = hl2 - factor * a

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    direction = np.full(n, 1, dtype=int)
    st = np.full(n, np.nan)

    # Need ATR seeded → first valid index
    first = atr_len
    if first >= n:
        idx = df.index
        return (pd.Series(st, index=idx), pd.Series(direction, index=idx))

    upper[first] = upper_basic[first]
    lower[first] = lower_basic[first]
    direction[first] = 1 if c[first] > upper_basic[first] else -1
    st[first] = lower[first] if direction[first] == 1 else upper[first]

    for i in range(first + 1, n):
        # Lock-down upper band
        if upper_basic[i] < upper[i - 1] or c[i - 1] > upper[i - 1]:
            upper[i] = upper_basic[i]
        else:
            upper[i] = upper[i - 1]
        # Lock-up lower band
        if lower_basic[i] > lower[i - 1] or c[i - 1] < lower[i - 1]:
            lower[i] = lower_basic[i]
        else:
            lower[i] = lower[i - 1]

        # Direction flip rules (Pine semantics)
        if direction[i - 1] == -1 and c[i] > upper[i - 1]:
            direction[i] = 1
        elif direction[i - 1] == 1 and c[i] < lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]

        st[i] = lower[i] if direction[i] == 1 else upper[i]

    return (pd.Series(st, index=df.index, name="supertrend"),
            pd.Series(direction, index=df.index, name="st_dir"))


# ═══════════════════════════════════════════════════════════════════════
#  Pivot-based Support / Resistance
#  Mirrors `ta.pivothigh(high, left, right)` / `ta.pivotlow`
#  A pivot is a bar whose high (low) is strictly greater (less) than
#  `left` bars on its left and `right` bars on its right.
#  The pivot is detected `right` bars AFTER the fact (causal).
# ═══════════════════════════════════════════════════════════════════════
def pivots(series: pd.Series, left: int = 8, right: int = 8,
           kind: str = "high") -> pd.Series:
    """Return a Series with NaN except at pivot bars where the value is the
    pivot price. The pivot is *placed at the bar of the pivot itself* (not
    the detection bar) for visual fidelity with Pine's `plotshape`. The
    detection bar is `right` bars later — see `confirmed_pivots()` for
    the causal version.
    """
    arr = series.to_numpy()
    n = len(arr)
    out = np.full(n, np.nan)
    op = np.greater if kind == "high" else np.less
    for i in range(left, n - right):
        window_left  = arr[i - left:i]
        window_right = arr[i + 1:i + 1 + right]
        if window_left.size < left or window_right.size < right:
            continue
        v = arr[i]
        if op(v, window_left).all() and op(v, window_right).all():
            out[i] = v
    return pd.Series(out, index=series.index)


@dataclass
class SRZones:
    """Up to 6 most-recent supports + 6 resistances, sorted by recency."""
    supports:    list[float]
    resistances: list[float]


def recent_sr_zones(df: pd.DataFrame, *, left: int = 8, right: int = 8,
                    keep: int = 6) -> SRZones:
    """Find the most recent `keep` confirmed pivot highs (resistance) and
    pivot lows (support). 'Confirmed' = pivot is at least `right` bars
    in the past relative to the latest bar."""
    last_idx = len(df) - 1
    confirmed_cutoff = last_idx - right

    pivot_highs = pivots(df["high"], left, right, kind="high")
    pivot_lows  = pivots(df["low"],  left, right, kind="low")

    # Walk backwards collecting most-recent confirmed pivots
    res: list[float] = []
    sup: list[float] = []
    for i in range(confirmed_cutoff, -1, -1):
        if not np.isnan(pivot_highs.iloc[i]) and len(res) < keep:
            res.append(float(pivot_highs.iloc[i]))
        if not np.isnan(pivot_lows.iloc[i]) and len(sup) < keep:
            sup.append(float(pivot_lows.iloc[i]))
        if len(res) >= keep and len(sup) >= keep:
            break
    return SRZones(supports=sup, resistances=res)


def nearest_sr_distance(price: float, zones: SRZones, atr_value: float
                        ) -> tuple[float, float]:
    """Return (distance_to_nearest_resistance_in_ATR, distance_to_nearest_support_in_ATR).
    Inf if no zone available."""
    if atr_value <= 0:
        return float("inf"), float("inf")
    res_above = [z for z in zones.resistances if z >= price]
    sup_below = [z for z in zones.supports    if z <= price]
    d_res = (min(res_above) - price) / atr_value if res_above else float("inf")
    d_sup = (price - max(sup_below)) / atr_value if sup_below else float("inf")
    return d_res, d_sup


# ═══════════════════════════════════════════════════════════════════════
#  Confluence helper for triple-Supertrend
# ═══════════════════════════════════════════════════════════════════════
def triple_supertrend_dir(df: pd.DataFrame
                          ) -> tuple[int, int, int, int, pd.Series, pd.Series]:
    """Compute the three Pine ST presets (10/3, 11/2, 12/1).
    Returns (dir1, dir2, dir3, agreement, primary_line, primary_dir_series).
    The primary (3.0/10) line and its direction series are returned so
    callers (signal_engine) can derive SL placement without recomputing.
    Direction values use our +1=up convention (already inverted from Pine).
    """
    if len(df) < 30:
        empty = pd.Series([], dtype=float, index=df.index[:0])
        return 0, 0, 0, 0, empty, empty
    line1, d1_series = supertrend(df, 3.0, 10)
    _,     d2_series = supertrend(df, 2.0, 11)
    _,     d3_series = supertrend(df, 1.0, 12)
    a = int(d1_series.iloc[-1])
    b = int(d2_series.iloc[-1])
    c = int(d3_series.iloc[-1])
    return a, b, c, a + b + c, line1, d1_series


# ═══════════════════════════════════════════════════════════════════════
#  EMA Ribbon  (8 / 21 / 55 / 89)
# ═══════════════════════════════════════════════════════════════════════
def ema_ribbon_dir(df: pd.DataFrame) -> tuple[int, float]:
    """EMA ribbon 8/21/55/89. Returns (direction, contribution).

    Bullish: e8>e21>e55>e89 AND close>e8  → (+1, 1.0)  fully fanned up
    Partial: e8>e21>e55 AND close>e21     → (+1, 0.6)  3/4 in order
    Weak:    close > e55                  → (+1, 0.3)  above mid ribbon
    Mirror for bearish. Compressed/mixed  → (0, 0.0)
    """
    if len(df) < 90:
        return 0, 0.0
    close = df["close"]
    e8  = float(ema(close, 8).iloc[-1])
    e21 = float(ema(close, 21).iloc[-1])
    e55 = float(ema(close, 55).iloc[-1])
    e89 = float(ema(close, 89).iloc[-1])
    c   = float(close.iloc[-1])
    if e8 > e21 > e55 > e89 and c > e8:    return +1, 1.0
    if e8 > e21 > e55 and c > e21:         return +1, 0.6
    if c > e55:                             return +1, 0.3
    if e8 < e21 < e55 < e89 and c < e8:    return -1, 1.0
    if e8 < e21 < e55 and c < e21:         return -1, 0.6
    if c < e55:                             return -1, 0.3
    return 0, 0.0


# ═══════════════════════════════════════════════════════════════════════
#  Market Structure  (BOS / CHoCH)
# ═══════════════════════════════════════════════════════════════════════
def market_structure_dir(df: pd.DataFrame, left: int = 5, right: int = 5,
                          lookback: int = 4) -> tuple[int, float]:
    """BOS detection via ascending/descending confirmed pivot sequence.

    Bullish BOS: last `lookback` pivot lows are all ascending (HH+HL)  → (+1, 1.0)
    Partial:     majority ascending                                     → (+1, 0.5)
    Bearish BOS: last `lookback` pivot highs are all descending (LH+LL) → (-1, 1.0)
    Partial:     majority descending                                    → (-1, 0.5)
    Choppy/mixed                                                        → (0, 0.0)

    Uses confirmed pivots only (right bars look-ahead already past).
    """
    min_bars = (left + right) * lookback
    if len(df) < min_bars:
        return 0, 0.0
    ph = pivots(df["high"], left, right, "high").dropna()
    pl = pivots(df["low"],  left, right, "low").dropna()
    if len(ph) < lookback or len(pl) < lookback:
        return 0, 0.0
    recent_highs = ph.iloc[-lookback:].values
    recent_lows  = pl.iloc[-lookback:].values
    n = lookback - 1  # number of consecutive pairs
    bull = sum(recent_lows[i]  > recent_lows[i - 1]  for i in range(1, lookback))
    bear = sum(recent_highs[i] < recent_highs[i - 1] for i in range(1, lookback))
    majority = (n + 1) // 2  # ceiling of half
    if bull == n:          return +1, 1.0
    if bull >= majority:   return +1, 0.5
    if bear == n:          return -1, 1.0
    if bear >= majority:   return -1, 0.5
    return 0, 0.0


# ═══════════════════════════════════════════════════════════════════════
#  Liquidity Sweep  (wick grab of recent swing high / low)
# ═══════════════════════════════════════════════════════════════════════
def liquidity_sweep_dir(df: pd.DataFrame, lookback: int = 20,
                         bars_back: int = 3) -> tuple[int, float]:
    """Detect a wick-based liquidity sweep on recent completed bars.

    Bullish sweep: bar low < rolling swing low AND bar close > swing low
                   (price grabbed stops below swing low then reversed)  → (+1, 1.0)
    Bearish sweep: bar high > rolling swing high AND bar close < swing high
                                                                        → (-1, 1.0)
    Checks the last `bars_back` completed bars; returns on first match.
    No sweep detected                                                   → (0, 0.0)
    """
    if len(df) < lookback + bars_back:
        return 0, 0.0
    for i in range(bars_back, 0, -1):
        end   = len(df) - i
        start = end - lookback
        if start < 0:
            continue
        sw_low    = float(df["low"].iloc[start:end].min())
        sw_high   = float(df["high"].iloc[start:end].max())
        bar_low   = float(df["low"].iloc[end])
        bar_high  = float(df["high"].iloc[end])
        bar_close = float(df["close"].iloc[end])
        if bar_low < sw_low and bar_close > sw_low:
            return +1, 1.0
        if bar_high > sw_high and bar_close < sw_high:
            return -1, 1.0
    return 0, 0.0
