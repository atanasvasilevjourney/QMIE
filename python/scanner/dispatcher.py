"""
QMIE — Signal Dispatcher
========================
Bridge between scanner output and the notifier fan-out.

Responsibilities:
  1. Dedup (per-symbol-per-bar-close) so re-scans of the same closed
     candle don't double-fire.
  2. Persist every alert in SQLite for audit / replay.
  3. Translate ScanResult → TVSignal → notifiers.
  4. Build the TradingView chart deep-link URL injected in the alert.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from db import Database
from models import AssetClass, EventType, Grade, Side, TVSignal
from notifiers.base import Notifier
from security import IdempotencyStore

from .signal_engine import ScanResult

logger = logging.getLogger(__name__)


_GRADE_RANK = {Grade.A_PLUS: 4, Grade.A: 3, Grade.B: 2, Grade.C: 1, Grade.REJECT: 0}


def _to_grade(s: str) -> Grade:
    try:    return Grade(s)
    except: return Grade.REJECT


def tv_chart_url(symbol: str, timeframe: str, prefix: str = "BINANCE") -> str:
    """Build a TradingView chart deep-link.
    e.g. https://www.tradingview.com/chart/?symbol=BINANCE:BTCUSDT.P&interval=240
    """
    interval_map = {"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30",
                    "1h":"60","2h":"120","4h":"240","6h":"360","12h":"720",
                    "1d":"D","1w":"W"}
    interval = interval_map.get(timeframe.lower(), "240")
    sym = symbol.upper()
    if not sym.endswith(".P") and prefix.upper() == "BINANCE":
        sym += ".P"      # default to perp on Binance feed
    return f"https://www.tradingview.com/chart/?symbol={prefix.upper()}:{sym}&interval={interval}"


class SignalDispatcher:
    def __init__(
        self,
        *,
        db: Database,
        notifiers: list[Notifier],
        idem: IdempotencyStore,
        min_alert_grade: Grade = Grade.A,
        tv_chart_prefix: str = "BINANCE",
    ):
        self.db = db
        self.notifiers = notifiers
        self.idem = idem
        self.min_alert_grade = min_alert_grade
        self.tv_prefix = tv_chart_prefix

    async def dispatch(self, result: ScanResult) -> bool:
        """Return True if dispatched, False if filtered/duplicate."""
        grade = _to_grade(result.grade)
        if _GRADE_RANK.get(grade, 0) < _GRADE_RANK.get(self.min_alert_grade, 3):
            return False

        # Build a stable key: symbol|tf|side|bar_close_ts
        bar_ms = int(result.timestamp.value // 1_000_000)
        idem_key = f"scan|{result.symbol}|{result.timeframe}|{result.side}|{bar_ms}"

        if await self.idem.seen_or_mark(idem_key):
            return False

        # Translate to internal TVSignal model
        sig = TVSignal(
            strategy="QMIE-Scanner",
            event=EventType.ENTRY,
            symbol=result.symbol,
            asset_class=AssetClass.CRYPTO,
            timeframe=result.timeframe,
            side=Side.BUY if result.side == "BUY" else Side.SELL,
            signal_price=result.price,
            stop_loss=result.stop_loss,
            take_profit=result.take_profit,
            score=result.score,
            grade=grade,
            trend="bullish" if result.side == "BUY" else "bearish",
            htf="aligned" if result.htf_aligned else "neutral",
            adx=result.adx_value,
            atr=result.atr_value,
            timestamp=result.timestamp.isoformat(),
            bar_time=bar_ms,
            reason=result.reason,
        )

        # Persist (idempotent by idempotency_key)
        try:
            await self.db.insert_signal(sig)
        except Exception:
            logger.exception("DB insert_signal failed (non-fatal)")

        chart_url = tv_chart_url(result.symbol, result.timeframe, self.tv_prefix)
        # Stash deep link inside metadata for notifiers that want it.
        # TVSignal has extra="allow" so we can attach freely.
        sig_dict = sig.model_dump()
        sig_dict["chart_url"] = chart_url
        sig_dict["daily_trend"] = result.daily_trend

        # Fan out (fire-and-forget). Wrap in a re-built TVSignal w/ extra fields.
        notify_sig = TVSignal.model_validate(sig_dict)

        await asyncio.gather(
            *(n.send_signal(notify_sig, None) for n in self.notifiers if n.enabled),
            return_exceptions=True,
        )
        logger.info(
            "ALERT %s %s %s %s score=%.1f price=%.6f",
            result.symbol, result.timeframe, result.side, result.grade,
            result.score, result.price,
        )
        return True
