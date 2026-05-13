"""
QMIE — Scanner Scheduler
========================
Bar-close-aware loop. Per timeframe, fires a scan pass exactly once
per *closed* bar. Avoids the two classic pitfalls:

  1. Re-scanning the same closed bar repeatedly (handled by dispatcher
     dedup, but pointless work).
  2. Scanning mid-bar and getting drift between server and Pine.

Schedule rule:
   For TF with bar size T, the closed-bar boundary is `floor(now / T) * T`.
   We track `last_seen_close[tf]` and only run when it advances.

Concurrency:
   Per pass, we scan all symbols with a Semaphore-bounded asyncio.gather.
   Errors on individual symbols are isolated — one bad ticker does not
   kill the pass.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from .dispatcher import SignalDispatcher
from .exchange_clients import ExchangeClient
from .signal_engine import Weights, compute_signal
from .symbol_universe import SymbolUniverse

logger = logging.getLogger(__name__)


# Timeframe → seconds
_TF_SECONDS = {
    "1m":60, "3m":180, "5m":300, "15m":900, "30m":1800,
    "1h":3600, "2h":7200, "4h":14400, "6h":21600, "12h":43200,
    "1d":86400, "1w":604800,
}


def _tf_seconds(tf: str) -> int:
    s = _TF_SECONDS.get(tf.lower())
    if s is None:
        raise ValueError(f"Unsupported timeframe {tf}")
    return s


def _last_close_ts(now: float, tf_sec: int) -> int:
    """The unix-second timestamp of the most recent bar boundary at-or-before `now`."""
    return int(now // tf_sec) * tf_sec


# ═══════════════════════════════════════════════════════════════════════
class ScannerScheduler:
    def __init__(
        self,
        *,
        client: ExchangeClient,
        universe: SymbolUniverse,
        dispatcher: SignalDispatcher,
        timeframes: list[str],
        htf_map: dict[str, str],
        weights: Weights = Weights(),
        loop_interval_sec: int = 30,
        max_concurrency: int = 8,
        sig_min_atr_pct: float = 0.10,
        sig_max_atr_pct: float = 8.0,
    ):
        self.client = client
        self.universe = universe
        self.dispatcher = dispatcher
        self.timeframes = [t.lower() for t in timeframes]
        self.htf_map = {k.lower(): v.lower() for k, v in htf_map.items()}
        self.weights = weights
        self.loop_interval = loop_interval_sec
        self.sem = asyncio.Semaphore(max_concurrency)
        self.sig_min_atr_pct = sig_min_atr_pct
        self.sig_max_atr_pct = sig_max_atr_pct

        # tf → unix-sec of the most recent bar we've already scanned
        self._last_seen: dict[str, int] = {}
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        # Stats exposed via /health
        self.stats = {
            "passes": 0,
            "alerts_dispatched": 0,
            "errors": 0,
            "last_pass_at": None,
        }

    # ─── Lifecycle ───────────────────────────────────────────────────────
    async def start(self) -> None:
        self._stop.clear()
        # Seed last_seen so the very first launch doesn't replay all of
        # the current bar's history. Wait for the NEXT bar close.
        now = time.time()
        for tf in self.timeframes:
            self._last_seen[tf] = _last_close_ts(now, _tf_seconds(tf))
        self._task = asyncio.create_task(self._run())
        logger.info("Scanner scheduler started: TFs=%s symbols=universe", self.timeframes)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    # ─── Main loop ───────────────────────────────────────────────────────
    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("Scheduler tick crashed (continuing)")
                self.stats["errors"] += 1
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.loop_interval)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        now = time.time()
        # Find which TFs have a NEW closed bar since we last scanned
        due: list[str] = []
        for tf in self.timeframes:
            tf_sec = _tf_seconds(tf)
            current_close = _last_close_ts(now, tf_sec)
            # We want a small grace window so the exchange has the close ready
            if (current_close > self._last_seen.get(tf, 0)) and \
               (now - current_close >= 5):     # 5s grace
                due.append(tf)
                self._last_seen[tf] = current_close

        if not due:
            return

        for tf in due:
            try:
                await self._scan_pass(tf)
            except Exception:
                logger.exception("Scan pass failed for tf=%s", tf)
                self.stats["errors"] += 1

    # ─── One scan pass at one timeframe ──────────────────────────────────
    async def _scan_pass(self, tf: str) -> None:
        symbols = await self.universe.get()
        if not symbols:
            logger.warning("Universe empty — nothing to scan")
            return

        htf = self.htf_map.get(tf)
        logger.info("Scan pass: tf=%s htf=%s symbols=%d", tf, htf, len(symbols))
        t0 = time.time()

        async def scan_one(sym: str) -> None:
            async with self.sem:
                try:
                    df = await self.client.fetch_klines(sym, tf, limit=300)
                    if df is None or len(df) < 220:
                        return
                    htf_df = None
                    if htf:
                        try:
                            htf_df = await self.client.fetch_klines(sym, htf, limit=300)
                        except Exception:
                            htf_df = None
                    # Daily trend filter: supply 1D klines to compute_signal.
                    # If HTF is already "1d" (4H scans), reuse htf_df — no extra call.
                    # Otherwise fetch "1d" separately (e.g. for 1H scans where HTF=4H).
                    daily_df = None
                    if htf == "1d":
                        daily_df = htf_df
                    elif htf is not None:
                        try:
                            daily_df = await self.client.fetch_klines(sym, "1d", limit=250)
                        except Exception:
                            daily_df = None
                    res = compute_signal(
                        df, symbol=sym, timeframe=tf,
                        htf_df=htf_df, daily_df=daily_df, weights=self.weights,
                    )
                    if res is None:
                        return
                    # Volatility regime gate
                    if not (self.sig_min_atr_pct <= res.atr_pct <= self.sig_max_atr_pct):
                        return
                    if await self.dispatcher.dispatch(res):
                        self.stats["alerts_dispatched"] += 1
                except Exception as e:
                    logger.warning("scan %s/%s failed: %s", sym, tf, e)

        await asyncio.gather(*(scan_one(s) for s in symbols),
                             return_exceptions=True)

        elapsed = time.time() - t0
        self.stats["passes"] += 1
        self.stats["last_pass_at"] = int(time.time())
        logger.info("Scan pass tf=%s completed in %.2fs (symbols=%d)",
                    tf, elapsed, len(symbols))
