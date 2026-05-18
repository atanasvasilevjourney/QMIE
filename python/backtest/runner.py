"""
QMIE Backtest — Signal Runner & Outcome Evaluator
===================================================
Walks historical bars through compute_signal, records every non-REJECT
signal, then evaluates each against subsequent bars to find WIN/LOSS/OPEN.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from scanner.signal_engine import ScanResult, compute_signal

logger = logging.getLogger(__name__)

WARMUP_BARS = 300
MAX_LOOKAHEAD = 100


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    timestamp: pd.Timestamp
    side: str
    grade: str
    score: float
    daily_trend: str
    entry: float
    stop_loss: float
    take_profit: float
    atr_pct: float
    adx_value: float          # ADX at signal time (for post-hoc filtering)
    rr_ratio: float           # reward / risk at signal time
    outcome: str              # WIN / LOSS / OPEN
    bars_to_outcome: Optional[int]
    realized_r: Optional[float]  # +rr_ratio on WIN, -1.0 on LOSS, None on OPEN
    mae_r: Optional[float]    # max adverse excursion in R units (how far against us)
    mfe_r: Optional[float]    # max favorable excursion in R units (how far in our favour)


def _evaluate_outcome(
    df: pd.DataFrame,
    signal_idx: int,
    side: str,
    entry: float,
    take_profit: float,
    stop_loss: float,
    max_lookahead: int = MAX_LOOKAHEAD,
) -> tuple[str, Optional[int], Optional[float], Optional[float]]:
    """Scan forward from signal_idx to find first TP or SL touch.

    Returns (outcome, bars_to_outcome, mae_r, mfe_r).
    MAE/MFE are in R units: 1.0 R = one stop-loss distance from entry.
    """
    risk = abs(entry - stop_loss)
    max_adverse: float = 0.0   # worst move against us (in R)
    max_favorable: float = 0.0  # best move in our favour (in R)

    for offset in range(1, max_lookahead + 1):
        i = signal_idx + offset
        if i >= len(df):
            break
        bar_high = df["high"].iloc[i]
        bar_low = df["low"].iloc[i]

        if side == "BUY":
            adverse = (entry - bar_low) / risk if risk > 0 else 0.0
            favorable = (bar_high - entry) / risk if risk > 0 else 0.0
            tp_hit = bar_high >= take_profit
            sl_hit = bar_low <= stop_loss
        else:  # SELL
            adverse = (bar_high - entry) / risk if risk > 0 else 0.0
            favorable = (entry - bar_low) / risk if risk > 0 else 0.0
            tp_hit = bar_low <= take_profit
            sl_hit = bar_high >= stop_loss

        max_adverse = max(max_adverse, adverse)
        max_favorable = max(max_favorable, favorable)

        if tp_hit and sl_hit:
            return "LOSS", offset, round(max_adverse, 3), round(max_favorable, 3)
        if tp_hit:
            return "WIN", offset, round(max_adverse, 3), round(max_favorable, 3)
        if sl_hit:
            return "LOSS", offset, round(max_adverse, 3), round(max_favorable, 3)

    mae = round(max_adverse, 3) if max_adverse > 0 else None
    mfe = round(max_favorable, 3) if max_favorable > 0 else None
    return "OPEN", None, mae, mfe


def run_backtest(
    symbol: str,
    tf: str,
    df_base: pd.DataFrame,
    htf_rule: str,
    daily_rule: str = "1D",
) -> list[BacktestResult]:
    """
    Walk df_base bar-by-bar from WARMUP_BARS onward.
    Calls compute_signal on each bar, evaluates outcome for non-REJECT signals.

    htf_rule: pandas resample rule for HTF df (e.g. '4h' when tf='1h')
    daily_rule: pandas resample rule for daily trend (always '1D')
    """
    from .data_loader import resample_ohlcv

    df_htf = resample_ohlcv(df_base, htf_rule)
    df_daily = resample_ohlcv(df_base, daily_rule)

    results: list[BacktestResult] = []
    n = len(df_base)

    # Use a fixed-size rolling window — compute_signal only needs ~300 bars
    # of lookback. Passing df[:i+1] grows O(n²); 400-bar window is O(n).
    WINDOW = 400

    for i in range(WARMUP_BARS, n):
        bar_ts = df_base.index[i]
        slice_base = df_base.iloc[max(0, i - WINDOW + 1): i + 1]
        slice_htf = df_htf.loc[:bar_ts].iloc[-WINDOW:]
        slice_daily = df_daily.loc[:bar_ts]

        sig: Optional[ScanResult] = compute_signal(
            slice_base,
            symbol=symbol,
            timeframe=tf,
            htf_df=slice_htf if len(slice_htf) >= 10 else None,
            daily_df=slice_daily if len(slice_daily) >= 200 else None,
        )

        if sig is None or sig.grade == "REJECT" or sig.side == "NEUTRAL":
            continue

        outcome, bars_to, mae_r, mfe_r = _evaluate_outcome(
            df_base, i, sig.side, sig.price, sig.take_profit, sig.stop_loss
        )

        risk = abs(sig.price - sig.stop_loss)
        reward = abs(sig.take_profit - sig.price)
        rr_ratio = round(reward / risk, 3) if risk > 0 else 0.0
        if outcome == "WIN":
            realized_r: Optional[float] = rr_ratio
        elif outcome == "LOSS":
            realized_r = -1.0
        else:
            realized_r = None

        results.append(BacktestResult(
            symbol=symbol,
            timeframe=tf,
            timestamp=sig.timestamp,
            side=sig.side,
            grade=sig.grade,
            score=sig.score,
            daily_trend=sig.daily_trend,
            entry=sig.price,
            stop_loss=sig.stop_loss,
            take_profit=sig.take_profit,
            atr_pct=sig.atr_pct,
            adx_value=sig.adx_value,
            rr_ratio=rr_ratio,
            outcome=outcome,
            bars_to_outcome=bars_to,
            realized_r=realized_r,
            mae_r=mae_r,
            mfe_r=mfe_r,
        ))

    return results


def results_to_dataframe(results: list[BacktestResult]) -> pd.DataFrame:
    """Convert list of BacktestResult to a DataFrame."""
    if not results:
        return pd.DataFrame(columns=[
            "symbol", "timeframe", "timestamp", "side", "grade", "score",
            "daily_trend", "entry", "stop_loss", "take_profit", "atr_pct", "adx_value",
            "rr_ratio", "outcome", "bars_to_outcome", "realized_r", "mae_r", "mfe_r",
        ])
    return pd.DataFrame([vars(r) for r in results])
