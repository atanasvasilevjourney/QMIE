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
    outcome: str              # WIN / LOSS / OPEN
    bars_to_outcome: Optional[int]


def _evaluate_outcome(
    df: pd.DataFrame,
    signal_idx: int,
    side: str,
    take_profit: float,
    stop_loss: float,
    max_lookahead: int = MAX_LOOKAHEAD,
) -> tuple[str, Optional[int]]:
    """Scan forward from signal_idx to find first TP or SL touch."""
    for offset in range(1, max_lookahead + 1):
        i = signal_idx + offset
        if i >= len(df):
            break
        bar_high = df["high"].iloc[i]
        bar_low = df["low"].iloc[i]

        if side == "BUY":
            tp_hit = bar_high >= take_profit
            sl_hit = bar_low <= stop_loss
        else:  # SELL
            tp_hit = bar_low <= take_profit
            sl_hit = bar_high >= stop_loss

        if tp_hit and sl_hit:
            return "LOSS", offset   # conservative: gap-through both = LOSS
        if tp_hit:
            return "WIN", offset
        if sl_hit:
            return "LOSS", offset

    return "OPEN", None


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

    for i in range(WARMUP_BARS, n):
        bar_ts = df_base.index[i]
        slice_base = df_base.iloc[: i + 1]
        slice_htf = df_htf.loc[:bar_ts]
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

        outcome, bars_to = _evaluate_outcome(
            df_base, i, sig.side, sig.take_profit, sig.stop_loss
        )

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
            outcome=outcome,
            bars_to_outcome=bars_to,
        ))

    return results


def results_to_dataframe(results: list[BacktestResult]) -> pd.DataFrame:
    """Convert list of BacktestResult to a DataFrame."""
    if not results:
        return pd.DataFrame(columns=[
            "symbol", "timeframe", "timestamp", "side", "grade", "score",
            "daily_trend", "entry", "stop_loss", "take_profit", "atr_pct",
            "outcome", "bars_to_outcome",
        ])
    return pd.DataFrame([vars(r) for r in results])
