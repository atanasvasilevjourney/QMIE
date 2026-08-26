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
  GET  /screens               combo review list (unique symbol, never orders)
  GET  /radar                 last daily Trend Radar snapshot (RGG + coils)
  POST /radar/once            admin: force an immediate daily radar pass
  GET  /agents/briefing       six specialist agents in parallel (read-only)
  GET  /agents/desk           DAG analog: start→data→strategy→risk→portfolio
  GET  /agents/checklist/{id} native Smart Checklist for one stored signal
  GET  /agents/analysis/{id}  OpenAI/template Take + ATR levels (on-demand)
  GET  /guide                 trading guide (operator module)
  GET  /paper                 paper book snapshot (never orders)
  POST /paper/sync            backfill paper fills + mark SL/TP exits
  GET  /charts/book           equity curve from closed fills (SVG JSON)
  GET  /charts/price          closed klines + entry/exit/SL/TP marks
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

from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from config import Settings, get_settings
from db import Database
from models import Grade, JournalClose, JournalCreate, TVSignal
from notifiers import DiscordNotifier, Notifier, TelegramNotifier
from scanner.allocator import AllocConfig
from scanner.dispatcher import SignalDispatcher
from scanner.exchange_clients import get_client
from scanner.radar import RadarConfig, empty_radar_snapshot
from scanner.scheduler import ScannerScheduler
from scanner.signal_engine import Weights
from scanner.symbol_universe import SymbolUniverse
from security import IdempotencyStore, verify_signature, verify_webhook_token
from improve.agents import run_briefing
from improve.analysis import analyze_signal, openai_configured
from improve.checklist import evaluate_native, flatten_signal
from improve.desk import run_desk
from journal import JournalError, close_fill, create_fill, drift_message
from paper import PaperBook
from guide import trading_guide
from screens import VIEWS, build_screens
from charts import ALLOWED_CHART_TFS, align_trades, bars_payload, equity_payload, trades_payload


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
        self.paper: PaperBook | None = None
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
        paper=None,
    )
    paper = PaperBook(
        db,
        enabled=s.paper_enabled,
        notional_usdt=s.paper_notional_usdt,
        notify_exits=s.paper_notify_exits,
    )
    dispatcher.paper = paper
    state.paper = paper
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
        radar_enabled=s.radar_enabled,
        radar_dispatch_trend_start=s.radar_dispatch_trend_start,
        radar_cfg=RadarConfig(
            adx_length=s.radar_adx_length,
            enter_adx=s.radar_enter_adx,
            exit_adx=s.radar_exit_adx,
            coil_lookback=s.radar_coil_lookback,
            coil_max_width_pct=s.radar_coil_max_width_pct,
            fresh_flip_days=s.radar_fresh_flip_days,
            late_stage_days=s.radar_late_stage_days,
            late_stage_move_pct=s.radar_late_stage_move_pct,
            kline_limit=s.radar_kline_limit,
            notify=s.radar_notify,
            min_coverage_pct=s.radar_min_coverage_pct,
        ),
    )
    await scheduler.start()
    state.scheduler = scheduler

    if paper.enabled:
        try:
            synced = await paper.sync_all(client)
            logger.info(
                "Paper book sync: opened=%s closed=%s checked=%s (never orders)",
                synced.get("opened"), synced.get("closed"), synced.get("checked"),
            )
        except Exception:
            logger.exception("paper startup sync failed (non-fatal)")

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

# Desk UI on :5173 (or a preview origin) may call :8080 directly when the
# Vite /qmie proxy is missing. Public scanner data; no cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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
        "openai_configured": openai_configured(
            state.settings.openai_api_key if state.settings else None
        ),
        "paper": {
            "enabled": bool(state.settings.paper_enabled) if state.settings else False,
            "places_orders": False,
        },
    }


@app.get("/signals")
async def get_signals(limit: int = 50) -> list[dict[str, Any]]:
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    limit = max(1, min(500, limit))
    rows = await state.db.recent_signals(limit=limit)
    return [flatten_signal(r) for r in rows]


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


@app.get("/radar")
async def get_radar() -> dict[str, Any]:
    """Last daily Trend Radar snapshot (RGG + coils + breakouts).
    Unranked daily context — does not place orders."""
    if state.scheduler is None:
        raise HTTPException(503, "scanner_not_ready")
    snap = state.scheduler.last_radar
    if snap is None:
        return empty_radar_snapshot(
            enabled=state.scheduler.radar_enabled,
            note="no_radar_yet",
        ).as_dict()
    out = snap.as_dict()
    out.setdefault("enabled", state.scheduler.radar_enabled)
    return out


@app.get("/screens")
async def get_screens(view: str = "all") -> dict[str, Any]:
    """Combo review list: TEMA A/A+ ∪ daily breakout ∪ coils ∪ book.

    unique(symbol). Leaders view is 4h A/A+ only. Not a new score. Never orders.
    """
    if state.db is None or state.scheduler is None:
        raise HTTPException(503, "scanner_not_ready")
    v = (view or "all").strip().lower()
    if v not in VIEWS:
        raise HTTPException(400, f"view must be one of {list(VIEWS)}")
    signals = await state.db.recent_signals(limit=200)
    radar = None
    if state.scheduler.last_radar is not None:
        radar = state.scheduler.last_radar.as_dict()
    allocation = None
    if state.scheduler.last_allocation is not None:
        allocation = state.scheduler.last_allocation.as_dict()
    return build_screens(
        signals=signals, radar=radar, allocation=allocation, view=v,
    )


@app.post("/radar/once")
async def radar_once(notify: bool = False) -> dict[str, Any]:
    """Admin: force a daily Trend Radar pass (no wait for next 1D close).

    Default notify=false so forced runs cannot spam Discord. Pass
    ``?notify=true`` only when you intentionally want a digest.
    """
    if state.scheduler is None:
        raise HTTPException(503, "scanner_not_ready")
    if not state.scheduler.radar_enabled:
        raise HTTPException(400, "radar_disabled")
    result = await state.scheduler.request_radar_once(notify=notify)
    if not result.get("ok") and result.get("reason") == "radar_disabled":
        raise HTTPException(400, "radar_disabled")
    return result


@app.get("/agents/briefing")
async def agents_briefing() -> dict[str, Any]:
    """Six read-only specialist agents. Isolated failures. Never orders.
    Analysis agent here is armed/not only — it does not call OpenAI."""
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    signals = await state.db.recent_signals(limit=50)
    fills = await state.db.recent_fills(limit=50)
    radar = None
    allocation = None
    if state.scheduler is not None:
        if state.scheduler.last_radar is not None:
            radar = state.scheduler.last_radar.as_dict()
        if state.scheduler.last_allocation is not None:
            allocation = state.scheduler.last_allocation.as_dict()
    return await run_briefing(
        signals=signals,
        radar=radar,
        allocation=allocation,
        db_path=Path(state.db.path),
        fills=fills,
    )


@app.get("/agents/desk")
async def agents_desk() -> dict[str, Any]:
    """Hedge-fund DAG analog. Suggested decisions only. quantity always 0."""
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    signals = await state.db.recent_signals(limit=50)
    fills = await state.db.recent_fills(limit=50)
    radar = None
    allocation = None
    if state.scheduler is not None:
        if state.scheduler.last_radar is not None:
            radar = state.scheduler.last_radar.as_dict()
        if state.scheduler.last_allocation is not None:
            allocation = state.scheduler.last_allocation.as_dict()
    return run_desk(signals=signals, radar=radar, allocation=allocation, fills=fills)


@app.get("/agents/checklist/{signal_id}")
async def agents_checklist(signal_id: int) -> dict[str, Any]:
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    row = await state.db.get_signal(signal_id)
    if row is None:
        raise HTTPException(404, "signal_not_found")
    radar = None
    if state.scheduler is not None and state.scheduler.last_radar is not None:
        radar = state.scheduler.last_radar.as_dict()
    fills = await state.db.recent_fills(limit=50)
    return evaluate_native(row, radar=radar, fills=fills).as_dict()


@app.get("/guide")
async def get_guide() -> dict[str, Any]:
    """Operator trading guide. Not a score. Never orders."""
    return trading_guide()


@app.get("/paper")
async def get_paper() -> dict[str, Any]:
    if state.paper is None:
        raise HTTPException(503, "paper_not_ready")
    snap = await state.paper.snapshot()
    snap["places_orders"] = False
    return snap


@app.get("/charts/book")
async def get_charts_book(limit: int = 500) -> dict[str, Any]:
    """Cumulative paper/manual PnL. Starting equity 0. Never orders."""
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    limit = max(1, min(2000, limit))
    fills = await state.db.recent_fills(limit=limit)
    payload = equity_payload(fills)
    payload["limit"] = limit
    return payload


@app.get("/charts/price")
async def get_charts_price(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 180,
) -> dict[str, Any]:
    """Closed-bar OHLC + trade marks for one symbol. SVG JSON. Never orders."""
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    sym = (symbol or "").upper().replace("-", "").replace(".P", "")
    if not sym.endswith("USDT") or not sym[:-4].isalnum() or len(sym) < 7:
        raise HTTPException(400, "symbol_must_be_usdt_perp")
    tf = (timeframe or "1h").lower()
    if tf not in ALLOWED_CHART_TFS:
        raise HTTPException(400, "bad_timeframe")
    lim = max(20, min(300, limit))
    fills = await state.db.fills_for_symbol(sym, limit=200)
    payload: dict[str, Any] = {
        "symbol": sym,
        "timeframe": tf,
        "places_orders": False,
        "bars": [],
        "trades": trades_payload(fills),
        "fills": len(fills),
        "note": None,
    }
    if state.client is None:
        payload["note"] = "client_not_ready"
        return payload
    try:
        df = await state.client.fetch_klines(sym, tf, limit=lim)
    except Exception as e:
        logger.warning("charts klines failed %s %s: %s", sym, tf, e)
        payload["note"] = "klines_unavailable"
        return payload
    if df is None or getattr(df, "empty", True):
        payload["note"] = "no_klines"
        return payload
    payload["bars"] = bars_payload(df)
    payload["trades"] = align_trades(payload["bars"], payload["trades"], chart_tf=tf)
    return payload


@app.post("/paper/sync")
async def post_paper_sync() -> dict[str, Any]:
    """Backfill paper fills for stored entries and mark SL/TP exits.

    Never places orders. Uses closed klines only.
    """
    if state.paper is None:
        raise HTTPException(503, "paper_not_ready")
    if not state.paper.enabled:
        raise HTTPException(400, "paper_disabled")
    result = await state.paper.sync_all(state.client)
    result["places_orders"] = False
    return result


@app.get("/agents/analysis/{signal_id}")
async def agents_analysis(signal_id: int) -> dict[str, Any]:
    """On-demand overlay: status + Invalidation / Current / T1 / T2 + Take.

    Prices are stamped from scanner ATR SL/TP after any LLM response.
    Empty OPENAI_API_KEY uses the deterministic template. Not a grade.
    """
    if state.db is None:
        raise HTTPException(503, "db_not_ready")
    row = await state.db.get_signal(signal_id)
    if row is None:
        raise HTTPException(404, "signal_not_found")
    radar = None
    if state.scheduler is not None and state.scheduler.last_radar is not None:
        radar = state.scheduler.last_radar.as_dict()
    fills = await state.db.recent_fills(limit=50)
    s = state.settings
    return await analyze_signal(
        row,
        api_key=s.openai_api_key if s else None,
        model=s.openai_model if s else "gpt-4.1-mini",
        timeout_sec=s.openai_timeout_sec if s else 20.0,
        base_url=s.openai_base_url if s else "https://api.openai.com/v1",
        radar=radar,
        fills=fills,
    )


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
    token: str | None = None,
    x_qmie_signature: str | None = Header(default=None, alias="X-QMIE-Signature"),
    x_qmie_timestamp: str | None = Header(default=None, alias="X-QMIE-Timestamp"),
) -> dict[str, Any]:
    """Optional ingress for Pine-side alerts (e.g. from the visualizer
    indicator). Re-broadcasts to the same notifier fan-out.

    TradingView cannot send HMAC headers. Put ``?token=WEBHOOK_SECRET``
    on the webhook URL, or send ``X-QMIE-Signature``.
    """
    s = state.settings
    if s is None or state.dispatcher is None:
        raise HTTPException(503, "service_starting")

    body = await request.body()
    if not body:
        raise HTTPException(400, "empty_body")

    if s.webhook_require_hmac:
        token_ok = verify_webhook_token(s.webhook_secret, token)
        if not token_ok and not verify_signature(s.webhook_secret, body, x_qmie_signature):
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

    dispatched = await state.dispatcher.dispatch_inbound(sig)
    return {"ok": True, "duplicate": not dispatched, "broadcast": dispatched}


# ─── Entry point ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    s = get_settings()
    uvicorn.run("main:app", host=s.host, port=s.port,
                log_level=s.log_level.lower(), workers=s.workers)
