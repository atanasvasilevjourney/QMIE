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
from typing import Any, Optional

from models import Side

from .allocator import AllocConfig, AllocationPlan, allocate
from .dispatcher import SignalDispatcher, trend_start_to_tvsignal
from .exchange_clients import ExchangeClient
from .radar import (
    RadarConfig,
    RadarSnapshot,
    RadarRow,
    build_snapshot,
    classify_with_recent_setups,
    empty_radar_snapshot,
    format_radar_digest,
    iter_trend_starts,
    unique_trend_starts,
)
from .signal_engine import ScanResult, Weights, compute_signal
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
        sig_min_adx: float = 0.0,
        sig_funding_rate_threshold: float = 0.001,
        alloc_cfg: Optional[AllocConfig] = None,
        radar_cfg: Optional[RadarConfig] = None,
        radar_enabled: bool = True,
        radar_dispatch_trend_start: bool = True,
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
        self.sig_min_adx = sig_min_adx
        self.sig_funding_rate_threshold = sig_funding_rate_threshold
        self.alloc_cfg = alloc_cfg or AllocConfig(mode="all")
        self.last_allocation: Optional[AllocationPlan] = None
        self._last_rotation_key: Optional[tuple] = None

        # Daily Trend Radar (independent of SCAN_TIMEFRAMES)
        self.radar_enabled = radar_enabled
        self.radar_dispatch_trend_start = radar_dispatch_trend_start
        self.radar_cfg = radar_cfg or RadarConfig()
        try:
            self.radar_cfg.validate()
        except ValueError as e:
            logger.warning("RadarConfig invalid at init (%s); disabling radar", e)
            self.radar_enabled = False
        self.last_radar: Optional[RadarSnapshot] = empty_radar_snapshot(
            enabled=self.radar_enabled, note="no_radar_yet",
        )
        # Seed to "today's" boundary so unit tests that tick without start()
        # do not fire a radar pass. start() runs a silent warm-up.
        self._last_radar_seen: int = _last_close_ts(time.time(), _tf_seconds("1d"))
        self._radar_lock = asyncio.Lock()
        self._radar_task: Optional[asyncio.Task] = None
        self._radar_warmup_done = False

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
            "radar_passes": 0,
            "last_radar_at": None,
            "radar_errors": 0,
        }

    # ─── Lifecycle ───────────────────────────────────────────────────────
    async def start(self) -> None:
        self._stop.clear()
        # Seed last_seen so the very first launch doesn't replay all of
        # the current bar's history. Wait for the NEXT bar close.
        now = time.time()
        for tf in self.timeframes:
            self._last_seen[tf] = _last_close_ts(now, _tf_seconds(tf))
        self._last_radar_seen = _last_close_ts(now, _tf_seconds("1d"))
        self._task = asyncio.create_task(self._run())
        logger.info(
            "Scanner scheduler started: TFs=%s radar=%s symbols=universe",
            self.timeframes, self.radar_enabled,
        )
        # Silent warm-up so GET /radar is useful before the next UTC midnight.
        if self.radar_enabled and not self._radar_warmup_done:
            self._radar_warmup_done = True
            try:
                await self._radar_pass(notify=False, mark_seen=True)
            except Exception:
                logger.exception("Trend Radar warm-up failed (will retry on next close)")
                self.stats["radar_errors"] += 1

    async def stop(self) -> None:
        self._stop.set()
        if self._radar_task and not self._radar_task.done():
            self._radar_task.cancel()
            try:
                await self._radar_task
            except (asyncio.CancelledError, Exception):
                pass
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

        # Time-sensitive 1H/4H scans first; radar is latency-insensitive.
        for tf in due:
            try:
                await self._scan_pass(tf)
            except Exception:
                logger.exception("Scan pass failed for tf=%s", tf)
                self.stats["errors"] += 1

        # Daily Trend Radar — once per closed 1D bar. Advance _last_radar_seen
        # only after a successful publish so transient failures retry.
        if self.radar_enabled:
            day_sec = _tf_seconds("1d")
            current_day = _last_close_ts(now, day_sec)
            if (current_day > self._last_radar_seen) and (now - current_day >= 5):
                try:
                    ok = await self._radar_pass(notify=None, mark_seen=False)
                    if ok:
                        self._last_radar_seen = current_day
                except Exception:
                    logger.exception("Trend Radar pass failed")
                    self.stats["radar_errors"] += 1
                    self.stats["errors"] += 1

    async def request_radar_once(self, *, notify: bool = False) -> dict[str, Any]:
        """Coalesced manual/admin radar pass. Returns status for the HTTP layer."""
        if not self.radar_enabled:
            return {"ok": False, "queued": False, "reason": "radar_disabled"}
        if self._radar_lock.locked() or (
            self._radar_task is not None and not self._radar_task.done()
        ):
            return {"ok": True, "queued": False, "already_running": True}
        self._radar_task = asyncio.create_task(
            self._radar_pass(notify=notify, mark_seen=False)
        )
        return {"ok": True, "queued": True, "notify": notify}
    # ─── One scan pass at one timeframe ──────────────────────────────────
    async def _scan_pass(self, tf: str) -> None:
        symbols = await self.universe.get()
        if not symbols:
            logger.warning("Universe empty — nothing to scan")
            return

        htf = self.htf_map.get(tf)
        logger.info("Scan pass: tf=%s htf=%s symbols=%d", tf, htf, len(symbols))
        t0 = time.time()

        async def scan_one(sym: str) -> Optional[ScanResult]:
            async with self.sem:
                try:
                    is_rotation = (self.alloc_cfg.mode or "").lower() == "rotation"
                    min_bars = 220
                    if is_rotation:
                        min_bars = max(
                            self.alloc_cfg.norm_length + 2,
                            self.alloc_cfg.ma_length,
                            2,
                        )
                    df = await self.client.fetch_klines(sym, tf, limit=300)
                    if df is None or len(df) < min_bars:
                        return None
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
                    res = None
                    if len(df) >= 220:
                        res = compute_signal(
                            df, symbol=sym, timeframe=tf,
                            htf_df=htf_df, daily_df=daily_df, weights=self.weights,
                        )
                    gated = False
                    if res is None:
                        gated = True
                    else:
                        if not (self.sig_min_atr_pct <= res.atr_pct <= self.sig_max_atr_pct):
                            gated = True
                        if self.sig_min_adx > 0 and res.adx_value < self.sig_min_adx:
                            logger.debug(
                                "ADX gate suppressed %s %s (adx=%.1f < %.1f)",
                                sym, res.side, res.adx_value, self.sig_min_adx,
                            )
                            gated = True
                    try:
                        premium = await self.client.fetch_premium_index(sym)
                        fr = float(premium.get("lastFundingRate", 0) or 0)
                        if res is not None:
                            res.funding_rate = fr
                        threshold = self.sig_funding_rate_threshold
                        if res is not None:
                            if res.side == "BUY" and fr > threshold:
                                logger.info(
                                    "Funding filter suppressed BUY %s (rate=%.4f%%)",
                                    sym, fr * 100,
                                )
                                gated = True
                            if res.side == "SELL" and fr < -threshold:
                                logger.info(
                                    "Funding filter suppressed SELL %s (rate=%.4f%%)",
                                    sym, fr * 100,
                                )
                                gated = True
                    except Exception as exc:
                        logger.warning("Could not fetch funding rate for %s: %s", sym, exc)
                    if is_rotation:
                        from .rotation import attach_rotation_metrics, stub_scan
                        if res is None:
                            res = stub_scan(sym, tf, df)
                        attach_rotation_metrics(
                            res, df["close"],
                            norm_length=self.alloc_cfg.norm_length,
                            ma_length=self.alloc_cfg.ma_length,
                            ma_type=self.alloc_cfg.ma_type,
                        )
                        return res
                    if gated or res is None:
                        return None
                    return res
                except Exception as e:
                    logger.warning("scan %s/%s failed: %s", sym, tf, e)
                    return None

        gathered = await asyncio.gather(*(scan_one(s) for s in symbols),
                                        return_exceptions=True)
        results: list[ScanResult] = []
        for item in gathered:
            if isinstance(item, ScanResult):
                results.append(item)
            elif isinstance(item, Exception):
                logger.warning("scan gather error: %s", item)
                self.stats["errors"] += 1

        to_dispatch: list[ScanResult]
        mode = (self.alloc_cfg.mode or "all").lower()
        if mode == "ranked":
            plan = allocate(results, self.alloc_cfg, timeframe=tf)
            self.last_allocation = plan
            to_dispatch = [s.result for s in plan.slots]
            logger.info(
                "Allocation tf=%s slots=%d considered=%d",
                tf, len(plan.slots), plan.considered,
            )
        elif mode == "rotation":
            plan = allocate(results, self.alloc_cfg, timeframe=tf)
            self.last_allocation = plan
            key = (plan.regime, tuple(
                (s.result.symbol, round(s.weight_pct, 2)) for s in plan.slots
            ))
            if key == self._last_rotation_key:
                to_dispatch = []
                logger.info(
                    "ARS tf=%s regime=%s unchanged (no alert)",
                    tf, plan.regime,
                )
            else:
                self._last_rotation_key = key
                to_dispatch = [s.result for s in plan.slots]
                logger.info(
                    "ARS tf=%s regime=%s defensive=%s slots=%d",
                    tf, plan.regime, plan.defensive, len(plan.slots),
                )
                if plan.regime in ("CASH", "PAXG") and not plan.slots:
                    await self._notify_rotation_text(plan)
        else:
            to_dispatch = results
            self.last_allocation = allocate(
                results,
                AllocConfig(
                    mode="all",
                    top_long=999,
                    top_short=999,
                    min_grade="C",
                    weighting="equal",
                    cluster_max=0,
                ),
                timeframe=tf,
            )

        for res in to_dispatch:
            try:
                if await self.dispatcher.dispatch(res):
                    self.stats["alerts_dispatched"] += 1
            except Exception as e:
                logger.warning("dispatch %s/%s failed: %s", res.symbol, tf, e)

        paper = getattr(self.dispatcher, "paper", None)
        if paper is not None and getattr(paper, "enabled", False):
            try:
                await paper.mark_with_client(self.client)
            except Exception:
                logger.exception("paper mark after scan failed (non-fatal)")

        elapsed = time.time() - t0
        self.stats["passes"] += 1
        self.stats["last_pass_at"] = int(time.time())
        logger.info("Scan pass tf=%s completed in %.2fs (symbols=%d)",
                    tf, elapsed, len(symbols))

    async def _radar_pass(
        self,
        *,
        notify: Optional[bool] = None,
        mark_seen: bool = False,
    ) -> bool:
        """Daily RGG + coil radar. Returns True if a snapshot was published.

        notify=None → use RadarConfig.notify
        mark_seen → advance _last_radar_seen to today's boundary on success
        """
        async with self._radar_lock:
            symbols = await self.universe.get()
            if not symbols:
                logger.warning("Trend Radar: universe empty")
                return False

            cfg = self.radar_cfg
            do_notify = cfg.notify if notify is None else notify
            logger.info(
                "Trend Radar pass: symbols=%d limit=%d notify=%s",
                len(symbols), cfg.kline_limit, do_notify,
            )
            t0 = time.time()

            async def one(sym: str) -> tuple[str, Optional[RadarRow], list[dict[str, Any]], Optional[str]]:
                async with self.sem:
                    try:
                        df = await self.client.fetch_klines(
                            sym, "1d", limit=cfg.kline_limit,
                        )
                        row, setups = classify_with_recent_setups(df, sym, cfg=cfg)
                        if row is None:
                            return sym, None, [], "too_short_or_empty"
                        return sym, row, setups, None
                    except Exception as e:
                        return sym, None, [], str(e)

            gathered = await asyncio.gather(
                *(one(s) for s in symbols), return_exceptions=True,
            )
            rows: list[RadarRow] = []
            replay: list[dict[str, Any]] = []
            failed: list[str] = []
            for item in gathered:
                if isinstance(item, Exception):
                    logger.warning("radar gather error: %s", item)
                    self.stats["radar_errors"] += 1
                    self.stats["errors"] += 1
                    continue
                sym, row, setups, err = item
                if row is not None:
                    rows.append(row)
                    replay.extend(setups)
                else:
                    failed.append(sym)
                    self.stats["radar_errors"] += 1
                    if err and err != "too_short_or_empty":
                        logger.warning("radar %s failed: %s", sym, err)

            # Total failure: keep previous snapshot (do not publish empty).
            if not rows:
                logger.warning(
                    "Trend Radar: 0/%d classified — retaining previous snapshot",
                    len(symbols),
                )
                self.stats["radar_errors"] += 1
                return False

            snap = build_snapshot(
                rows,
                timeframe="1d",
                requested=len(symbols),
                failed_symbols=failed,
                enabled=True,
            )
            self.last_radar = snap
            self.stats["radar_passes"] += 1
            self.stats["last_radar_at"] = int(time.time())
            if mark_seen:
                self._last_radar_seen = _last_close_ts(time.time(), _tf_seconds("1d"))

            logger.info(
                "Trend Radar done in %.2fs: n=%d/%d G=%d Gy=%d R=%d "
                "flips_g=%d coils=%d brk=%d status=%s",
                time.time() - t0, snap.succeeded, snap.requested,
                snap.green, snap.grey, snap.red,
                len(snap.fresh_green), len(snap.tight_coils),
                len(snap.breakouts), snap.status,
            )

            if self.radar_dispatch_trend_start:
                await self._dispatch_trend_starts(snap, replay=replay)

            coverage = (
                100.0 * snap.succeeded / snap.requested if snap.requested else 0.0
            )
            if (
                do_notify
                and snap.has_actionable
                and coverage >= cfg.min_coverage_pct
            ):
                msg = format_radar_digest(snap)
                notifiers = getattr(self.dispatcher, "notifiers", []) or []
                await asyncio.gather(
                    *(
                        n.send_text(msg)
                        for n in notifiers
                        if getattr(n, "enabled", True)
                    ),
                    return_exceptions=True,
                )
            elif do_notify and not snap.has_actionable:
                logger.info("Trend Radar: no actionable buckets — digest skipped")
            elif do_notify and coverage < cfg.min_coverage_pct:
                logger.info(
                    "Trend Radar: coverage %.0f%% < %.0f%% — digest skipped",
                    coverage, cfg.min_coverage_pct,
                )
            return True

    async def _dispatch_trend_starts(
        self,
        snap: RadarSnapshot,
        *,
        replay: Optional[list[dict[str, Any]]] = None,
    ) -> int:
        """Fan out closed-1D GREY→GREEN/RED and coil UP/DOWN as inbound signals.

        `replay` is trend-starts from the last N closed 1D bars (missed coil-UP).
        Dedup is by symbol+side+bar_time here and again in the dispatcher.
        """
        items = unique_trend_starts(iter_trend_starts(snap.rows) + list(replay or []))
        n = 0
        n_long = 0
        n_short = 0
        for item in items:
            try:
                sig = trend_start_to_tvsignal(item)
                ok = await self.dispatcher.dispatch_inbound(sig)
                if ok:
                    n += 1
                    if sig.side is Side.SELL:
                        n_short += 1
                    else:
                        n_long += 1
            except Exception:
                logger.exception("daily breakout dispatch failed for %s", item.get("symbol"))
        if n:
            logger.info(
                "Trend Radar dispatched %d daily breakout setup(s) (long=%d short=%d)",
                n, n_long, n_short,
            )
        paper = getattr(self.dispatcher, "paper", None)
        if paper is not None and getattr(paper, "enabled", False):
            try:
                await paper.mark_with_client(self.client)
            except Exception:
                logger.exception("paper mark after radar failed (non-fatal)")
        return n

    async def _notify_rotation_text(self, plan: AllocationPlan) -> None:
        scores = ", ".join(
            f"{r['symbol']}={r['norm_score']}"
            for r in (plan.rotation_scores or [])[:8]
        )
        why = f" ({plan.defensive})" if plan.defensive else ""
        msg = (
            f"ARS rotation → {plan.regime}{why} · {plan.timeframe}"
            + (f" · {scores}" if scores else "")
        )
        notifiers = getattr(self.dispatcher, "notifiers", []) or []
        await asyncio.gather(
            *(n.send_text(msg) for n in notifiers if getattr(n, "enabled", True)),
            return_exceptions=True,
        )
