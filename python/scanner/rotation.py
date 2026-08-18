"""
QMIE — Asset Rotation (ARS-style)
=================================
Relative-strength rotation for the ranked allocator. Decision basis is
normalized lookback return only — no RSI / MACD / Supertrend.

This is an original implementation of the *method* documented by
Uptrick ARS (lookback strength, cash threshold, optional MA filter,
dual allocation, second BTC-weak defensive mode). It is not a port of
the invite-only Pine source.

Does not place orders. Suggested weights are a 100-point risk budget.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .indicators import ema, rma
from .signal_engine import ScanResult


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length, min_periods=length).mean()


def wma(series: pd.Series, length: int) -> pd.Series:
    """Linear-weighted MA, most recent bar has the largest weight."""
    if length <= 0:
        raise ValueError("wma length must be > 0")
    weights = np.arange(1, length + 1, dtype=float)

    def _dot(window: np.ndarray) -> float:
        return float(np.dot(window, weights) / weights.sum())

    return series.rolling(length, min_periods=length).apply(_dot, raw=True)


def moving_average(close: pd.Series, length: int, kind: str) -> pd.Series:
    k = (kind or "ema").strip().lower()
    if k == "sma":
        return sma(close, length)
    if k in ("rma", "smma"):
        return rma(close, length)
    if k == "wma":
        return wma(close, length)
    return ema(close, length)  # ema / ewma default


def normalized_score(close: pd.Series, length: int) -> float:
    """Percent change vs close[length] bars ago. NaN if not enough history."""
    if length <= 0 or len(close) <= length:
        return float("nan")
    prev = float(close.iloc[-1 - length])
    last = float(close.iloc[-1])
    if prev == 0 or np.isnan(prev) or np.isnan(last):
        return float("nan")
    return (last / prev - 1.0) * 100.0


def ma_holds(close: pd.Series, length: int, kind: str) -> bool:
    """True if last close is above the MA. Fail-open when MA is undefined."""
    if length <= 0 or len(close) < length:
        return True
    ma = moving_average(close, length, kind)
    val = float(ma.iloc[-1]) if len(ma) else float("nan")
    last = float(close.iloc[-1])
    if np.isnan(val) or np.isnan(last):
        return True
    return last > val


def attach_rotation_metrics(
    result: ScanResult,
    close: pd.Series,
    *,
    norm_length: int,
    ma_length: int,
    ma_type: str,
) -> ScanResult:
    result.norm_score = normalized_score(close, norm_length)
    result.ma_ok = ma_holds(close, ma_length, ma_type)
    return result


def stub_scan(symbol: str, timeframe: str, df: pd.DataFrame) -> ScanResult:
    """Placeholder so rotation can rank a name with no A-grade setup."""
    ts = df.index[-1]
    px = float(df["close"].iloc[-1])
    return ScanResult(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=ts,
        side="NEUTRAL",
        grade="REJECT",
        score=0.0,
        price=px,
        stop_loss=px,
        take_profit=px,
        atr_value=0.0,
        atr_pct=0.0,
        rsi_value=50.0,
        adx_value=0.0,
        htf_aligned=None,
        nearest_res=0.0,
        nearest_sup=0.0,
    )


@dataclass
class RotationDecision:
    regime: str                 # LIVE | CASH | PAXG
    defensive: Optional[str]    # None | threshold | btc_weak
    winners: list[ScanResult]
    scores: list[dict]


def _finite(x: Optional[float]) -> bool:
    return x is not None and not (isinstance(x, float) and np.isnan(x))


def _btc_weak(quotes: list[ScanResult], btc_symbol: str) -> bool:
    btc = next((q for q in quotes if q.symbol.upper() == btc_symbol.upper()), None)
    if btc is None:
        return False
    if _finite(btc.norm_score) and btc.norm_score < 0:
        return True
    if btc.ma_ok is False:
        return True
    return False


def _paxg_ok(quotes: list[ScanResult], paxg_symbol: str, threshold: float) -> Optional[ScanResult]:
    px = next((q for q in quotes if q.symbol.upper() == paxg_symbol.upper()), None)
    if px is None:
        return None
    if px.ma_ok is False:
        return None
    if _finite(px.norm_score) and px.norm_score < threshold:
        return None
    return px


def decide_rotation(
    quotes: list[ScanResult],
    *,
    threshold: float,
    ma_filter: bool,
    dual: bool,
    defensive2: str,
    btc_symbol: str = "BTCUSDT",
    paxg_symbol: str = "PAXGUSDT",
    cluster_max: int = 1,
) -> RotationDecision:
    """Pick 1 (or 2) long-only winners, else CASH / PAXG.

    Defensive 1: all enabled scores < threshold → CASH.
    Defensive 2 (BTC-weak): cash | paxg | paxg_then_cash | off.
    """
    from .allocator import _pick  # local to avoid cycle at import

    scored: list[dict] = []
    eligible: list[ScanResult] = []
    for q in quotes:
        ns = q.norm_score
        row = {
            "symbol": q.symbol,
            "norm_score": None if not _finite(ns) else round(float(ns), 4),
            "ma_ok": q.ma_ok,
            "eligible": False,
        }
        ok_score = _finite(ns) and float(ns) >= threshold
        ok_ma = (not ma_filter) or (q.ma_ok is not False)
        if ok_score and ok_ma:
            eligible.append(q)
            row["eligible"] = True
        scored.append(row)

    scored.sort(key=lambda r: (-(r["norm_score"] if r["norm_score"] is not None else -1e18), r["symbol"]))
    eligible.sort(key=lambda r: (-(r.norm_score or -1e18), r.symbol))

    d2 = (defensive2 or "off").strip().lower()
    if d2 not in ("off", "cash", "paxg", "paxg_then_cash"):
        d2 = "off"

    if d2 != "off" and _btc_weak(quotes, btc_symbol):
        if d2 == "paxg":
            hold = _paxg_ok(quotes, paxg_symbol, threshold)
            if hold is not None:
                return RotationDecision("PAXG", "btc_weak", [hold], scored)
            return RotationDecision("CASH", "btc_weak", [], scored)
        if d2 == "paxg_then_cash":
            hold = _paxg_ok(quotes, paxg_symbol, threshold)
            if hold is not None:
                return RotationDecision("PAXG", "btc_weak", [hold], scored)
            return RotationDecision("CASH", "btc_weak", [], scored)
        return RotationDecision("CASH", "btc_weak", [], scored)

    if not eligible:
        return RotationDecision("CASH", "threshold", [], scored)

    n = 2 if dual else 1
    picked = _pick(eligible, n, cluster_max)
    if not picked:
        return RotationDecision("CASH", "threshold", [], scored)
    return RotationDecision("LIVE", None, picked, scored)


def simulate_equity(
    prices: dict[str, pd.Series],
    holdings: pd.Series,
    *,
    initial: float = 10_000.0,
    fee_pct: float = 0.1,
    slippage_pct: float = 0.05,
) -> pd.Series:
    """Bar-close equity. `holdings` is the symbol (or 'CASH') held *through* each bar.

    Switch cost = fee + slippage on the notional, charged when the name changes.
    """
    idx = holdings.index
    aligned = {s: p.reindex(idx).ffill() for s, p in prices.items()}
    equity = np.empty(len(idx), dtype=float)
    eq = initial
    prev = None
    cost = (fee_pct + slippage_pct) / 100.0
    for i, ts in enumerate(idx):
        name = holdings.iloc[i]
        if prev is not None and name != prev:
            eq *= (1.0 - cost)
        if name and name != "CASH" and name in aligned and i > 0:
            px = aligned[name]
            if pd.notna(px.iloc[i]) and pd.notna(px.iloc[i - 1]) and px.iloc[i - 1] != 0:
                eq *= float(px.iloc[i] / px.iloc[i - 1])
        equity[i] = eq
        prev = name
    return pd.Series(equity, index=idx, name="equity")
