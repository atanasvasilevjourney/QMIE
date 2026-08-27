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
from collections import defaultdict
from datetime import timezone

import pandas as pd

from db import Database
from models import AssetClass, EventType, Grade, Side, TVSignal
from notifiers.base import Notifier
from security import IdempotencyStore

from .signal_engine import ScanResult

logger = logging.getLogger(__name__)


_GRADE_RANK = {Grade.A_PLUS: 4, Grade.A: 3, Grade.B: 2, Grade.C: 1, Grade.REJECT: 0}


def _is_radar_spot(sig: TVSignal) -> bool:
    """1D radar expansions / color-flips are the spot book; TEMA is leveraged."""
    setup = getattr(sig, "setup_type", None)
    if setup in ("expansion", "breakout"):
        return True
    strat = (sig.strategy or "").lower()
    return "dailyexpansion" in strat or "dailybreakout" in strat


def _to_grade(s: str) -> Grade:
    try:    return Grade(s)
    except: return Grade.REJECT


def trend_start_to_tvsignal(item: dict) -> TVSignal:
    """Map a radar trend-start row (long or short) to the inbound TVSignal shape."""
    bar_time = item.get("bar_time")
    bar_ms = None
    if bar_time is not None:
        ts = pd.Timestamp(bar_time)
        if not pd.isna(ts):
            bar_ms = int(ts.value // 1_000_000)
    side_s = str(item.get("side") or "").upper()
    if side_s == "SELL" or item.get("breakout") == "DOWN":
        side = Side.SELL
    else:
        side = Side.BUY
    if side is Side.BUY and item.get("breakout") == "UP":
        sl = item.get("coil_low")
    elif side is Side.SELL and item.get("breakout") == "DOWN":
        sl = item.get("coil_high")
    else:
        sl = None
    if sl is not None:
        try:
            sl = float(sl)
        except (TypeError, ValueError):
            sl = None
    short = side is Side.SELL
    reason = str(item.get("reason") or ("trend_start_short" if short else "trend_start_long"))
    is_expansion = "coil_breakout" in reason or item.get("breakout") in ("UP", "DOWN")
    return TVSignal(
        strategy="QMIE-DailyExpansion" if is_expansion else "QMIE-DailyBreakout",
        event=EventType.ENTRY,
        symbol=str(item.get("symbol") or ""),
        asset_class=AssetClass.CRYPTO,
        timeframe="1d",
        side=side,
        signal_price=item.get("price"),
        stop_loss=sl,
        adx=item.get("adx"),
        timestamp=str(bar_time) if bar_time else None,
        bar_time=bar_ms,
        reason=reason,
        trend="bearish" if short else "bullish",
        daily_trend="bearish" if short else "bullish",
        setup_type="expansion" if is_expansion else "breakout",
        action="sell" if short else "buy",
    )


def tv_chart_url(symbol: str, timeframe: str, prefix: str = "BINANCE", *, perp: bool = True) -> str:
    """Build a TradingView chart deep-link.

    TEMA (leveraged) uses the Binance perp feed (``.P``).
    Trend Radar / DailyExpansion is the spot book — no ``.P``.
    e.g. https://www.tradingview.com/chart/?symbol=BINANCE:BTCUSDT.P&interval=240
    """
    interval_map = {"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30",
                    "1h":"60","2h":"120","4h":"240","6h":"360","12h":"720",
                    "1d":"D","d":"D","1w":"W","w":"W"}
    interval = interval_map.get(timeframe.lower(), "240")
    sym = symbol.upper()
    if perp and not sym.endswith(".P") and prefix.upper() == "BINANCE":
        sym += ".P"
    elif not perp:
        if sym.endswith(".P"):
            sym = sym[:-2]
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
        max_signals_per_symbol_per_day: int = 4,
        paper: object | None = None,
    ):
        self.db = db
        self.notifiers = notifiers
        self.idem = idem
        self.min_alert_grade = min_alert_grade
        self.tv_prefix = tv_chart_prefix
        self.max_per_day = max_signals_per_symbol_per_day
        self.paper = paper
        # (utc_date_iso, symbol) → count of alerts already dispatched that day
        self._day_counts: dict[tuple[str, str], int] = defaultdict(int)

    async def dispatch(self, result: ScanResult) -> bool:
        """Return True if dispatched, False if filtered/duplicate."""
        grade = _to_grade(result.grade)
        if not result.force_dispatch:
            if _GRADE_RANK.get(grade, 0) < _GRADE_RANK.get(self.min_alert_grade, 3):
                return False

        if self.max_per_day > 0:
            ts = result.timestamp
            if getattr(ts, "tzinfo", None) is None:
                day = ts.date().isoformat() if hasattr(ts, "date") else str(ts)[:10]
            else:
                day = ts.tz_convert(timezone.utc).date().isoformat()
            key = (day, result.symbol.upper())
            if self._day_counts[key] >= self.max_per_day:
                logger.info(
                    "Daily cap suppressed %s %s (%d/%d on %s)",
                    result.symbol, result.side, self._day_counts[key],
                    self.max_per_day, day,
                )
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
            rsi=result.rsi_value,
            atr_pct=result.atr_pct,
            timestamp=result.timestamp.isoformat(),
            bar_time=bar_ms,
            reason=result.reason,
            daily_trend=result.daily_trend,
            funding_rate=result.funding_rate,
            alloc_rank=result.alloc_rank,
            alloc_weight_pct=result.alloc_weight_pct,
            alloc_cluster=result.alloc_cluster,
            alloc_regime=result.alloc_regime,
            norm_score=result.norm_score,
        )

        # Persist (idempotent by idempotency_key)
        sig_id = 0
        try:
            sig_id = await self.db.insert_signal(sig)
        except Exception:
            logger.exception("DB insert_signal failed (non-fatal)")
        await self._maybe_paper(sig, sig_id)

        chart_url = tv_chart_url(result.symbol, result.timeframe, self.tv_prefix)
        # Stash deep link inside metadata for notifiers that want it.
        # TVSignal has extra="allow" so we can attach freely.
        sig_dict = sig.model_dump()
        sig_dict["chart_url"] = chart_url
        sig_dict["daily_trend"] = result.daily_trend
        sig_dict["funding_rate"] = result.funding_rate
        sig_dict["alloc_rank"] = result.alloc_rank
        sig_dict["alloc_weight_pct"] = result.alloc_weight_pct
        sig_dict["alloc_cluster"] = result.alloc_cluster
        sig_dict["alloc_regime"] = result.alloc_regime
        sig_dict["norm_score"] = result.norm_score

        # Fan out (fire-and-forget). Wrap in a re-built TVSignal w/ extra fields.
        notify_sig = TVSignal.model_validate(sig_dict)

        await asyncio.gather(
            *(n.send_signal(notify_sig, None) for n in self.notifiers if n.enabled),
            return_exceptions=True,
        )
        if self.max_per_day > 0:
            self._day_counts[key] += 1
        logger.info(
            "ALERT %s %s %s %s score=%.1f price=%.6f",
            result.symbol, result.timeframe, result.side, result.grade,
            result.score, result.price,
        )
        return True

    async def dispatch_inbound(self, sig: TVSignal) -> bool:
        """Persist + fan-out an already-built TVSignal (Pine webhook or daily breakout).

        Bypasses A/A+ min-grade — caller decides what is actionable.
        Still idempotent and still never places orders.
        """
        if await self.idem.seen_or_mark(sig.idempotency_key):
            return False
        sig_id = 0
        try:
            sig_id = await self.db.insert_signal(sig)
        except Exception:
            logger.exception("DB insert_signal failed (non-fatal)")
        await self._maybe_paper(sig, sig_id)

        tf = sig.timeframe or "1d"
        chart_url = tv_chart_url(sig.symbol, tf, self.tv_prefix, perp=not _is_radar_spot(sig))
        sig_dict = sig.model_dump()
        sig_dict["chart_url"] = chart_url
        notify_sig = TVSignal.model_validate(sig_dict)
        await asyncio.gather(
            *(n.send_signal(notify_sig, None) for n in self.notifiers if n.enabled),
            return_exceptions=True,
        )
        logger.info(
            "INBOUND %s %s %s %s reason=%s",
            sig.symbol, tf, sig.side.value if sig.side else "-",
            sig.strategy, sig.reason,
        )
        return True

    async def _maybe_paper(self, sig: TVSignal, signal_id: int) -> None:
        paper = self.paper
        if paper is None or not signal_id:
            return
        if sig.event in (EventType.EXIT, EventType.CLOSE):
            return
        try:
            await paper.open_entry(signal_id)  # type: ignore[attr-defined]
        except Exception:
            logger.exception("paper open failed (non-fatal)")
