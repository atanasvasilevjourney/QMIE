"""
QMIE — FastAPI App  (Scanner Edition)
=====================================
This server runs a *crypto-only* multi-symbol scanner in the background
and dispatches A/A+ signals to Discord and/or Telegram. It does NOT
execute trades.

Endpoints:
  GET  /                      version
  GET  /health                operational status (DB, scanner, notifiers)
  GET  /signals               last N dispatched alerts
  GET  /universe              the symbol set the next pass will scan
  POST /scan/once             admin: force an immediate scan pass on a TF
  GET  /allocation            last ranked-allocation plan (suggested size, not orders)
  POST /journal               log a manual fill against a signal id
  GET  /journal               recent fills
  PATCH /journal/{id}         set exit price on a fill
  GET  /journal/stats         win rate / R from fills (optional grade filter)
  POST /webhook               OPTIONAL: receive Pine alerts (HMAC) and
                              re-broadcast through the same notifiers.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from config import Settings, get_settings
from db import Database
from models import Grade, JournalClose, JournalCreate, TVSignal
from notifiers import DiscordNotifier, Notifier, TelegramNotifier
from scanner.allocator import AllocConfig
from scanner.dispatcher import SignalDispatcher, tv_chart_url
from scanner.exchange_clients import get_client
from scanner.scheduler import ScannerScheduler
from scanner.signal_engine import Weights
from scanner.symbol_universe import SymbolUniverse
from security import IdempotencyStore, verify_signature
from journal import JournalError, close_fill, create_fill, drift_message


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


logger = logging.getLogger("qmie.main")


class AppState:
    def __init__(self):
        self.settings: Settings | None = None
        self.db: Database | None = None
        self.idem: IdempotencyStore | None = None
        self.notifiers: list[Notifier] = []
        self.dispatcher: SignalDispatcher | None = None
        self.scheduler: ScannerScheduler | None = None
        self.client = None
        self.start_time: float = 0.0


state = AppState()


# ─── Lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    _setup_logging(s.log_level)
    state.settings = s
    state.start_time = time.time()
    logger.info("QMIE Scanner starting (env=%s, source=%s)", s.env, s.scan_data_source)
    for w in s.validate_runtime():
        logger.warning("Config: %s", w)

    # DB
    db = Database(s.db_url)
    await db.init()
    state.db = db

    # Idempotency
    redis_client = None
    if s.redis_url:
        try:
            import redis.asyncio as aioredis
            redis_client = aioredis.from_url(s.redis_url)
            await redis_client.ping()
            logger.info("Redis connected")
        except Exception as e:
            logger.warning("Redis unavailable: %s", e)
    state.idem = IdempotencyStore(ttl_sec=s.dedup_ttl_sec, redis=redis_client)

    # Notifiers
    notifiers: list[Notifier] = []
    if s.discord_enabled and s.discord_webhook_url:
        notifiers.append(DiscordNotifier(
            webhook_url=s.discord_webhook_url,
            username=s.discord_username,
            avatar_url=s.discord_avatar_url or "",
        ))
        logger.info("Discord notifier armed")
    if s.telegram_enabled and s.telegram_bot_token and s.telegram_chat_id:
        notifiers.append(TelegramNotifier(
            bot_token=s.telegram_bot_token,
            chat_id=s.telegram_chat_id,
        ))
        logger.info("Telegram notifier armed")
    state.notifiers = notifiers

    # Exchange data client
    client = get_client(s.scan_data_source, timeout=s.scan_data_timeout_sec)
    state.client = client

    # Universe
    universe = SymbolUniverse(
        client,
        static_symbols=s.symbols_static,
        auto_top_n=s.scan_auto_universe_top_n,
        min_quote_volume=s.scan_min_24h_quote_volume,
    )

    # Dispatcher
    try:
        min_grade = Grade(s.scan_min_alert_grade)
    except ValueError:
        logger.warning("Invalid SCAN_MIN_ALERT_GRADE=%s; defaulting to A",
                       s.scan_min_alert_grade)
        min_grade = Grade.A
    dispatcher = SignalDispatcher(
        db=db,
        notifiers=notifiers,
        idem=state.idem,
        min_alert_grade=min_grade,
        tv_chart_prefix=s.tv_chart_prefix,
        max_signals_per_symbol_per_day=s.sig_max_signals_per_symbol_per_day,
    )
    state.dispatcher = dispatcher

    # Scheduler
    scheduler = ScannerScheduler(
        client=client,
        universe=universe,
        dispatcher=dispatcher,
        timeframes=s.timeframes_list,
        htf_map=s.htf_map,
        weights=Weights(
            supertrend=s.w_supertrend, ema=s.w_ema, rsi=s.w_rsi,
            adx=s.w_adx, htf=s.w_htf, sr=s.w_sr, vol=s.w_vol,
            ribbon=s.w_ribbon, structure=s.w_structure, sweep=s.w_sweep,
        ),
        loop_interval_sec=s.scan_loop_interval_sec,
        max_concurrency=s.scan_max_concurrency,
        sig_min_atr_pct=s.sig_min_atr_pct,
        sig_max_atr_pct=s.sig_max_atr_pct,
        sig_min_adx=s.sig_min_adx,
        sig_funding_rate_threshold=s.sig_funding_rate_threshold,
        alloc_cfg=AllocConfig(
            mode=s.alloc_mode,
            top_long=s.alloc_top_long,
            top_short=s.alloc_top_short,
            min_grade=s.alloc_min_grade,
            weighting=s.alloc_weighting,
            cluster_max=s.alloc_cluster_max,
            norm_length=s.alloc_norm_length,
            norm_threshold=s.alloc_norm_threshold,
            ma_filter=s.alloc_ma_filter,
            ma_type=s.alloc_ma_type,
            ma_length=s.alloc_ma_length,
            dual=s.alloc_dual,
            defensive2=s.alloc_defensive2,
            btc_symbol=s.alloc_btc_symbol,
            paxg_symbol=s.alloc_paxg_symbol,
        ),
    )
    await scheduler.start()
    state.scheduler = scheduler

    logger.info("QMIE Scanner ready — TFs=%s min_grade=%s notifiers=%s",
                s.timeframes_list, min_grade.value,
                [n.name for n in notifiers])

    try:
        yield
    finally:
        logger.info("QMIE shutting down")
        if state.scheduler:
            await state.scheduler.stop()
        if state.client:
            try: await state.client.close()
            except Exception: logger.exception("client close failed")
        for n in state.notifiers:
            try: await n.close()
            except Exception: logger.exception("notifier close failed")


# ─── App ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="QMIE — Quant Multi-Asset Intelligence Engine (Scanner Edition)",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)


@app.middleware("http")
async def ip_allowlist(request: Request, call_next):
    if request.url.path == "/webhook" and state.settings and state.settings.webhook_allowlist:
        client = request.client.host if request.client else ""
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            client = xff.split(",")[0].strip()
        if client not in state.settings.webhook_allowlist:
            logger.warning("Webhook rejected from %s", client)
            return JSONResponse({"error": "ip_not_allowed"},
                                status_code=status.HTTP_403_FORBIDDEN)
    return await call_next(request)


# ─── Endpoints ───────────────────────────────────────────────────────────
@app.get("/")
async def root() -> dict[str, Any]:
    return {"name": "QMIE Scanner", "version": "2.0.0", "ok": True}


@app.get("/health")
async def health() -> dict[str, Any]:
    db_ok = await state.db.health_check() if state.db else False
    sched_stats = state.scheduler.stats if state.scheduler else {}
    return {
        "status": "ok" if db_ok else "degraded",
        "uptime_sec": round(time.time() - state.start_time, 1),
        "db_ok": db_ok,
        "notifiers": {n.name: "ok" for n in state.notifiers},
        "scanner": sched_stats,
        "data_source": state.settings.scan_data_source if state.settings else None,
    }


@app.get("/signals")
async def get_signals(limit: int = 50) -> list[dict[str, Any]]:
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    limit = max(1, min(500, limit))
    return await state.db.recent_signals(limit=limit)


@app.get("/universe")
async def get_universe() -> dict[str, Any]:
    if state.scheduler is None:
        raise HTTPException(503, "scanner_not_ready")
    syms = await state.scheduler.universe.get()
    return {
        "count": len(syms),
        "timeframes": state.scheduler.timeframes,
        "symbols": syms,
    }


@app.post("/scan/once")
async def scan_once(timeframe: str = "1h") -> dict[str, Any]:
    """Admin: force a one-off scan pass (without waiting for bar close).
    Useful for warmup / sanity checks."""
    if state.scheduler is None:
        raise HTTPException(503, "scanner_not_ready")
    tf = timeframe.lower()
    if tf not in state.scheduler.timeframes:
        raise HTTPException(400, f"timeframe {tf} not in scanner config")
    asyncio.create_task(state.scheduler._scan_pass(tf))
    return {"ok": True, "queued": tf}


@app.get("/allocation")
async def get_allocation() -> dict[str, Any]:
    """Last ranked-allocation plan: which alerts to take and suggested size.
    Does not place orders."""
    if state.scheduler is None:
        raise HTTPException(503, "scanner_not_ready")
    plan = state.scheduler.last_allocation
    if plan is None:
        return {
            "timeframe": None,
            "considered": 0,
            "skipped_grade": 0,
            "slots": [],
            "note": "no_scan_yet",
        }
    return plan.as_dict()


async def _maybe_notify_journal_drift() -> None:
    s = state.settings
    if s is None or s.journal_oos_win_pct is None or state.db is None:
        return
    stats = await state.db.journal_stats(grades=("A+", "A"))
    msg = drift_message(
        live_win_pct=float(stats["win_pct"]),
        baseline=s.journal_oos_win_pct,
        closed=int(stats["closed"]),
        min_fills=s.journal_min_fills,
        pts=s.journal_drift_pts,
    )
    if not msg:
        return
    logger.warning("%s", msg)
    await asyncio.gather(
        *(n.send_text(msg) for n in state.notifiers if n.enabled),
        return_exceptions=True,
    )


@app.post("/journal")
async def post_journal(body: JournalCreate) -> dict[str, Any]:
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    try:
        row = await create_fill(state.db, body)
    except JournalError as e:
        raise HTTPException(e.status, e.detail)
    await _maybe_notify_journal_drift()
    return row


@app.get("/journal")
async def get_journal(limit: int = 50) -> list[dict[str, Any]]:
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    limit = max(1, min(500, limit))
    return await state.db.recent_fills(limit=limit)


@app.get("/journal/stats")
async def get_journal_stats(grades: str = "A+,A") -> dict[str, Any]:
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    parsed = tuple(g.strip() for g in grades.split(",") if g.strip()) or None
    return await state.db.journal_stats(grades=parsed)


@app.patch("/journal/{fill_id}")
async def patch_journal(fill_id: int, body: JournalClose) -> dict[str, Any]:
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    try:
        row = await close_fill(state.db, fill_id, body)
    except JournalError as e:
        raise HTTPException(e.status, e.detail)
    await _maybe_notify_journal_drift()
    return row


@app.post("/webhook")
async def webhook(
    request: Request,
    x_qmie_signature: str | None = Header(default=None, alias="X-QMIE-Signature"),
    x_qmie_timestamp: str | None = Header(default=None, alias="X-QMIE-Timestamp"),
) -> dict[str, Any]:
    """Optional ingress for Pine-side alerts (e.g. from the visualizer
    indicator). Re-broadcasts to the same notifier fan-out."""
    s = state.settings
    if s is None or state.idem is None:
        raise HTTPException(503, "service_starting")

    body = await request.body()
    if not body:
        raise HTTPException(400, "empty_body")

    if s.webhook_require_hmac:
        if not verify_signature(s.webhook_secret, body, x_qmie_signature):
            raise HTTPException(401, "bad_signature")
    if x_qmie_timestamp:
        try:
            ts = float(x_qmie_timestamp)
            if abs(time.time() - ts) > s.webhook_max_age_sec:
                raise HTTPException(401, "stale_request")
        except (TypeError, ValueError):
            raise HTTPException(400, "bad_timestamp")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "bad_json")
    try:
        sig = TVSignal.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(422, e.errors())

    if await state.idem.seen_or_mark(sig.idempotency_key):
        return {"ok": True, "duplicate": True}

    if state.db:
        try: await state.db.insert_signal(sig)
        except Exception: logger.exception("DB insert failed")

    # Inject TV deep link for fan-out
    sig_dict = sig.model_dump()
    sig_dict["chart_url"] = tv_chart_url(
        sig.symbol, sig.timeframe or "4h", s.tv_chart_prefix,
    )
    notify_sig = TVSignal.model_validate(sig_dict)

    await asyncio.gather(
        *(n.send_signal(notify_sig, None) for n in state.notifiers if n.enabled),
        return_exceptions=True,
    )
    return {"ok": True, "queued": False, "broadcast": True}


# ─── Entry point ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    s = get_settings()
    uvicorn.run("main:app", host=s.host, port=s.port,
                log_level=s.log_level.lower(), workers=s.workers)
