"""
QMIE — Signal Engine
====================
Pine-compatible scoring engine. Given a confirmed-candle DataFrame
for the scan timeframe and (optionally) one for the higher
timeframe, compute a directional signal with grade.

Scoring (sum=100):
   Supertrend (triple-confluence) ............... 20
   EMA200 macro filter ........................... 15
   RSI zone + direction ........................... 15
   ADX trend strength ............................ 15
   HTF alignment ................................. 20
   S/R distance (room to move) ................... 10
   Volatility regime (ATR%) ....................... 5

Letter grades:
   A+   ≥ 90
   A    ≥ 80
   B    ≥ 65
   C    ≥ 50
   REJ  < 50  (or anti-aligned)

Direction:
   Each component independently votes BUY / SELL / NEUTRAL.
   Weighted majority of weighted votes determines side.
   If sides are mixed strongly, score is penalised.

This logic MUST mirror `pine/quant_strategy.pine`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .indicators import (
    adx, atr, ema, recent_sr_zones, rsi, supertrend,
    triple_supertrend_dir, nearest_sr_distance,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
@dataclass
class ScanResult:
    symbol:        str
    timeframe:     str
    timestamp:     pd.Timestamp
    side:          str                # "BUY" / "SELL" / "NEUTRAL"
    grade:         str                # "A+" / "A" / "B" / "C" / "REJECT"
    score:         float
    price:         float
    stop_loss:     float
    take_profit:   float
    atr_value:     float
    atr_pct:       float
    rsi_value:     float
    adx_value:     float
    htf_aligned:   Optional[bool]
    nearest_res:   float              # ATR-distance to nearest resistance
    nearest_sup:   float              # ATR-distance to nearest support
    components:    dict = field(default_factory=dict)  # per-module raw votes
    reason:        str = ""
    daily_trend:   str = "unknown"     # "bullish" / "bearish" / "unknown"
    funding_rate:  Optional[float] = None  # latest 8h rate, injected by scheduler


@dataclass
class Weights:
    supertrend: int = 20
    ema:        int = 15
    rsi:        int = 15
    adx:        int = 15
    htf:        int = 20
    sr:         int = 10
    vol:        int = 5

    @property
    def total(self) -> int:
        return self.supertrend + self.ema + self.rsi + self.adx + self.htf + self.sr + self.vol


# Module vote: -1 = sell-side support, 0 = neutral / penalty, +1 = buy-side support
def _component(direction: int, weight: int, contribution_pct: float = 1.0) -> int:
    """Return signed weighted contribution. contribution_pct ∈ [0, 1]."""
    contribution_pct = max(0.0, min(1.0, contribution_pct))
    return int(round(direction * weight * contribution_pct))


# ═══════════════════════════════════════════════════════════════════════
#  Main scoring
# ═══════════════════════════════════════════════════════════════════════
def compute_signal(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    htf_df: Optional[pd.DataFrame] = None,
    daily_df: Optional[pd.DataFrame] = None,
    weights: Weights = Weights(),
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 2.5,
) -> Optional[ScanResult]:
    """
    Returns a ScanResult on every confirmed bar (even REJECT). Returns
    None only when there isn't enough data to compute (warm-up period).
    """
    if df is None or len(df) < 220:
        return None

    close = df["close"]
    last_close = float(close.iloc[-1])
    last_ts = df.index[-1]

    # ─── 1. Supertrend (triple) ──────────────────────────────────────────
    d1, d2, d3, agreement, st_line, st_dir_series = triple_supertrend_dir(df)
    if len(st_line) == 0:
        return None
    st_dir_last = int(st_dir_series.iloc[-1])
    # Direction = sign(agreement); contribution scales with magnitude.
    # agreement ∈ {-3,-1,+1,+3} (impossible to be ±2 with three ±1 votes).
    #   ±3 → all three agree → full strength (1.0)
    #   ±1 → 2/3 majority   → partial   (1/3)
    if agreement >= 1:    st_d, st_c = +1, abs(agreement) / 3.0
    elif agreement <= -1: st_d, st_c = -1, abs(agreement) / 3.0
    else:                 st_d, st_c =  0, 0.0
    st_score = _component(st_d, weights.supertrend, st_c)

    # ─── 2. EMA200 ───────────────────────────────────────────────────────
    e200 = ema(close, 200)
    e200_last = float(e200.iloc[-1])
    if pd.isna(e200_last):
        return None
    if last_close > e200_last:
        ema_d, ema_c = +1, min(1.0, abs(last_close - e200_last) / e200_last * 50)
    elif last_close < e200_last:
        ema_d, ema_c = -1, min(1.0, abs(last_close - e200_last) / e200_last * 50)
    else:
        ema_d, ema_c = 0, 0.0
    # Cap contribution at 1.0 — distance bonus is tiny anyway
    ema_score = _component(ema_d, weights.ema, max(0.5, ema_c))

    # ─── 3. RSI zone + direction ────────────────────────────────────────
    rsi_series = rsi(close, 14)
    rsi_now  = float(rsi_series.iloc[-1])
    rsi_prev = float(rsi_series.iloc[-2])
    # Buy zone: 40-65 rising. Sell zone: 35-60 falling. Penalise
    # overbought (>75) longs and oversold (<25) shorts.
    if rsi_now >= 75:
        rsi_d, rsi_c = -1, 0.5         # mean-revert bias / overheated
    elif rsi_now <= 25:
        rsi_d, rsi_c = +1, 0.5
    elif rsi_now > rsi_prev and 45 < rsi_now < 70:
        rsi_d, rsi_c = +1, 1.0
    elif rsi_now < rsi_prev and 30 < rsi_now < 55:
        rsi_d, rsi_c = -1, 1.0
    else:
        rsi_d, rsi_c = 0, 0.0
    rsi_score = _component(rsi_d, weights.rsi, rsi_c)

    # ─── 4. ADX (trend strength) ────────────────────────────────────────
    plus_di, minus_di, adx_series = adx(df, 14)
    adx_now = float(adx_series.iloc[-1])
    pdi_now = float(plus_di.iloc[-1])
    mdi_now = float(minus_di.iloc[-1])
    if adx_now >= 25:
        adx_c = min(1.0, adx_now / 50.0)         # cap at ADX 50 → full
        adx_d = +1 if pdi_now > mdi_now else -1 if mdi_now > pdi_now else 0
    elif adx_now >= 18:
        adx_c = 0.5
        adx_d = +1 if pdi_now > mdi_now else -1 if mdi_now > pdi_now else 0
    else:
        adx_d, adx_c = 0, 0.0                    # no trend → neutral
    adx_score = _component(adx_d, weights.adx, adx_c)

    # ─── 5. HTF alignment ───────────────────────────────────────────────
    htf_aligned: Optional[bool] = None
    htf_d, htf_c = 0, 0.0
    if htf_df is not None and len(htf_df) >= 220:
        # On HTF: are we above EMA200 AND triple-ST in same direction?
        htf_ema = ema(htf_df["close"], 200)
        if not pd.isna(htf_ema.iloc[-1]):
            htf_close = float(htf_df["close"].iloc[-1])
            _, _, _, htf_agree, _, _ = triple_supertrend_dir(htf_df)
            htf_above_ema = htf_close > float(htf_ema.iloc[-1])
            # Use the same partial-agreement threshold as base TF
            if htf_agree >= 1 and htf_above_ema:
                htf_d, htf_c = +1, abs(htf_agree) / 3.0
                htf_aligned = (st_d == +1)
            elif htf_agree <= -1 and not htf_above_ema:
                htf_d, htf_c = -1, abs(htf_agree) / 3.0
                htf_aligned = (st_d == -1)
            else:
                htf_d, htf_c = 0, 0.0
                htf_aligned = False
    htf_score = _component(htf_d, weights.htf, htf_c)

    # ─── 6. Support / resistance room ───────────────────────────────────
    atr_series = atr(df, 14)
    atr_now = float(atr_series.iloc[-1])
    if pd.isna(atr_now) or atr_now <= 0:
        return None

    zones = recent_sr_zones(df, left=8, right=8, keep=6)
    d_res, d_sup = nearest_sr_distance(last_close, zones, atr_now)
    # Long: want lots of room overhead (d_res large), little to nearest support
    # Short: opposite. Score the side that has more room.
    if d_res > d_sup:                           # more room up than down
        sr_d, sr_c = +1, min(1.0, d_res / 4.0)  # ATR>=4 → full
    elif d_sup > d_res:
        sr_d, sr_c = -1, min(1.0, d_sup / 4.0)
    else:
        sr_d, sr_c = 0, 0.0
    # Penalise being right at a wall (<0.3 ATR) on the breakout side
    if d_res < 0.3 and sr_d > 0:
        sr_c *= 0.3
    if d_sup < 0.3 and sr_d < 0:
        sr_c *= 0.3
    sr_score = _component(sr_d, weights.sr, sr_c)

    # ─── 7. Volatility regime ───────────────────────────────────────────
    atr_pct = (atr_now / last_close) * 100.0
    # Sweet spot: 0.4% – 4.0% ATR. Outside → neutral.
    if 0.4 <= atr_pct <= 4.0:
        vol_d, vol_c = 0, 0.0                    # neutral but doesn't penalise
        # Reward via small additive bonus regardless of side
        vol_bonus = weights.vol
    else:
        vol_bonus = 0
    # Vol contributes only as additive; it doesn't push direction
    vol_score = vol_bonus

    # ─── Aggregate ──────────────────────────────────────────────────────
    raw = st_score + ema_score + rsi_score + adx_score + htf_score + sr_score
    raw_directional_total = (
        weights.supertrend + weights.ema + weights.rsi + weights.adx +
        weights.htf + weights.sr
    )
    # Side = sign of raw vote sum
    if raw > 0:   side = "BUY"
    elif raw < 0: side = "SELL"
    else:         side = "NEUTRAL"

    # Score = |raw| / max_directional_total * 95   + vol_bonus  (cap 100)
    score = abs(raw) / raw_directional_total * 95.0 + vol_score
    score = max(0.0, min(100.0, score))

    grade = _grade_for(score, side)

    # SL / TP from ATR
    if side == "BUY":
        sl = last_close - sl_atr_mult * atr_now
        tp = last_close + tp_atr_mult * atr_now
    elif side == "SELL":
        sl = last_close + sl_atr_mult * atr_now
        tp = last_close - tp_atr_mult * atr_now
    else:
        sl = tp = last_close

    # ─── Daily trend (EMA200 on 1D) ──────────────────────────────────────
    daily_trend = "unknown"
    if daily_df is not None and len(daily_df) >= 200:
        d_ema200 = ema(daily_df["close"], 200)
        d_e200_last = float(d_ema200.iloc[-1])
        d_close_last = float(daily_df["close"].iloc[-1])
        if not pd.isna(d_e200_last):
            if d_close_last > d_e200_last:
                daily_trend = "bullish"
            elif d_close_last < d_e200_last:
                daily_trend = "bearish"

    return ScanResult(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=last_ts,
        side=side,
        grade=grade,
        score=round(score, 1),
        price=last_close,
        stop_loss=round(sl, 8),
        take_profit=round(tp, 8),
        atr_value=atr_now,
        atr_pct=round(atr_pct, 3),
        rsi_value=round(rsi_now, 1),
        adx_value=round(adx_now, 1),
        htf_aligned=htf_aligned,
        nearest_res=round(d_res if d_res != float("inf") else 99.0, 2),
        nearest_sup=round(d_sup if d_sup != float("inf") else 99.0, 2),
        components={
            "supertrend": st_score, "ema": ema_score, "rsi": rsi_score,
            "adx": adx_score, "htf": htf_score, "sr": sr_score,
            "vol": vol_score, "st_dir": st_dir_last, "agreement": agreement,
            "rsi_now": round(rsi_now, 1), "adx_now": round(adx_now, 1),
            "atr_pct": round(atr_pct, 3),
            "d_res_atr": round(d_res, 2) if d_res != float("inf") else 99.0,
            "d_sup_atr": round(d_sup, 2) if d_sup != float("inf") else 99.0,
        },
        reason=_explain(side, st_d, ema_d, rsi_d, adx_d, htf_d, sr_d),
        daily_trend=daily_trend,
    )


def _grade_for(score: float, side: str) -> str:
    if side == "NEUTRAL": return "REJECT"
    if score >= 90:       return "A+"
    if score >= 80:       return "A"
    if score >= 65:       return "B"
    if score >= 50:       return "C"
    return "REJECT"


def _explain(side: str, st: int, ema_: int, rsi_: int, adx_: int,
             htf_: int, sr_: int) -> str:
    bits = []
    if st  != 0: bits.append(f"ST{'+' if st  > 0 else '-'}")
    if ema_!= 0: bits.append(f"EMA{'+' if ema_> 0 else '-'}")
    if rsi_!= 0: bits.append(f"RSI{'+' if rsi_> 0 else '-'}")
    if adx_!= 0: bits.append(f"ADX{'+' if adx_> 0 else '-'}")
    if htf_!= 0: bits.append(f"HTF{'+' if htf_> 0 else '-'}")
    if sr_ != 0: bits.append(f"SR{'+' if sr_ > 0 else '-'}")
    return f"{side}: " + " ".join(bits) if bits else side
