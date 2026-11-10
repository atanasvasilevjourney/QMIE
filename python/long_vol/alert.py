"""Map long-vol candidates to TVSignal for dispatcher + notifiers."""
from __future__ import annotations

from models import AssetClass, EventType, Grade, Side, TVSignal

from long_vol.live_scan import LongVolCandidate


def candidate_to_tvsignal(cand: LongVolCandidate) -> TVSignal:
    f = cand.features
    bar_ms = int(cand.timestamp.value // 1_000_000)
    return TVSignal(
        strategy="QMIE-LongVol",
        event=EventType.ENTRY,
        symbol=cand.symbol,
        asset_class=AssetClass.CRYPTO,
        timeframe="15m",
        side=Side.BUY,
        signal_price=cand.price,
        stop_loss=cand.stop_loss,
        take_profit=None,
        score=100.0 if cand.alert else 0.0,
        grade=Grade.A if cand.alert else Grade.REJECT,
        trend="bullish",
        adx=f.get("adx"),
        rsi=f.get("rsi_1h"),
        timestamp=cand.timestamp.isoformat(),
        bar_time=bar_ms,
        reason=cand.reason or "long_vol_breakout",
        setup_type="long_vol",
        action="buy",
        dist_atr=f.get("dist_atr"),
        rvol=f.get("rvol"),
        width_pct=f.get("width_pct"),
    )
