"""
QMIE — Configuration  (Scanner Edition)
=======================================
Crypto-focused, signal-only. No broker execution.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        extra="ignore", case_sensitive=False,
    )

    # ─── Server ──────────────────────────────────────────────────────────
    host:       str  = "0.0.0.0"
    port:       int  = 8080
    log_level:  str  = "INFO"
    workers:    int  = 1
    env:        str  = "production"

    # ─── Webhook security (only used by the optional inbound /webhook) ──
    webhook_secret:        str  = Field(default="dev-only-not-for-production",
                                        description="HMAC SHA-256 shared secret")
    webhook_max_age_sec:   int  = 60
    webhook_allow_ips:     str  = ""
    webhook_require_hmac:  bool = True

    # ─── Storage ─────────────────────────────────────────────────────────
    db_url:        str = "sqlite+aiosqlite:///./data/qmie.db"
    redis_url:     Optional[str] = None
    dedup_ttl_sec: int = 1800              # 30min cooldown per signal-key

    # ─── Notifiers ───────────────────────────────────────────────────────
    discord_webhook_url:    Optional[str] = None
    discord_username:       str = "QMIE"
    discord_avatar_url:     str = ""
    discord_enabled:        bool = True

    telegram_bot_token:     Optional[str] = None
    telegram_chat_id:       Optional[str] = None
    telegram_enabled:       bool = False

    # ─── Scanner ─────────────────────────────────────────────────────────
    # Comma-separated USDT perps. OKX uses POL/RENDER; Binance still has
    # MATIC/RNDR on some books. 1000PEPE and FET are omitted (no OKX SWAP).
    scan_symbols: str = (
        "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,"
        "LINKUSDT,POLUSDT,DOTUSDT,LTCUSDT,TRXUSDT,ATOMUSDT,NEARUSDT,APTUSDT,"
        "ARBUSDT,OPUSDT,SUIUSDT,INJUSDT,FILUSDT,RENDERUSDT,TIAUSDT,SEIUSDT,"
        "ORDIUSDT,WLDUSDT,PEPEUSDT,BONKUSDT"
    )
    # Auto-discover top-N by 24h quote volume in addition to the static list
    scan_auto_universe_top_n:  int = 0     # 0 = static list only
    scan_min_24h_quote_volume: float = 50_000_000.0   # $50M filter

    # Timeframes to scan. Pine alert syntax: 15m / 1h / 4h / 1d
    scan_timeframes: str = "1h,4h"
    # How often the dispatcher loop wakes up (seconds). It only ACTUALLY
    # scans a timeframe when its bar closes, so this can be tight.
    scan_loop_interval_sec: int = 30

    # Higher-timeframe used for HTF confirmation. Mapping per scan TF.
    scan_htf_map: str = "15m:1h,1h:4h,4h:1d,1d:1w"

    # Exchange data source: "binance" | "bybit" | "okx"
    scan_data_source: str = "binance"
    # Public REST. No auth needed for klines.
    scan_data_timeout_sec: float = 10.0
    scan_max_concurrency:  int = 8

    # Min grade to ALERT on. REJECT/C/B can be set if you want noisier flow.
    scan_min_alert_grade: str = "A"        # A+ | A | B | C | REJECT

    # ─── Signal engine weights (sum=100: TMA20+EMA199 15+RSI15+ADX15+HTF20+SR10+VOL5) ─
    w_supertrend: int = 20
    w_ema:        int = 15
    w_rsi:        int = 15
    w_adx:        int = 15
    w_htf:        int = 20
    w_sr:         int = 10
    w_vol:        int = 5

    # ─── TradingView deep-link config ────────────────────────────────────
    # Used in Discord/Telegram embeds: clicking opens the chart in TV.
    tv_chart_prefix: str = "BINANCE"       # BINANCE / BYBIT / etc.

    # ─── Risk filtering (signals, not orders) ────────────────────────────
    # We don't execute, but we still suppress alerts during high-volatility
    # garbage (e.g., 1-minute spikes that mean nothing).
    sig_max_signals_per_symbol_per_day: int = 4
    sig_min_atr_pct: float = 0.10          # too quiet → suppress
    sig_max_atr_pct: float = 8.0           # too volatile → suppress
    sig_min_adx: float = 0.0               # ADX trend-strength gate (0 = disabled, 20 = recommended)
    sig_funding_rate_threshold: float = 0.001  # suppress BUY when rate > +threshold, SELL when < -threshold (0.001 = 0.1%/8h)

    # ─── Journal / live-vs-OOS drift (manual fills, no execution) ────────
    # Set JOURNAL_OOS_WIN_PCT after Sprint 1 (e.g. 52.0). Until then, no drift alert.
    journal_oos_win_pct: Optional[float] = None
    journal_drift_pts:   float = 5.0
    journal_min_fills:   int = 30

    # ─── Paper book (auto journal vs alerts; never an order) ─────────────
    paper_enabled:       bool = True
    paper_notional_usdt: float = 1000.0
    paper_notify_exits:  bool = False

    # ─── Ranked asset allocation (which alerts to take, suggested size) ─
    alloc_mode:        str = "ranked"   # ranked | all | rotation
    alloc_top_long:    int = 3
    alloc_top_short:   int = 3
    alloc_min_grade:   str = "A"
    alloc_weighting:   str = "rank"     # rank | equal
    alloc_cluster_max: int = 1          # 0 = unlimited
    # ARS-style rotation (ALLOC_MODE=rotation)
    alloc_norm_length:    int = 20
    alloc_norm_threshold: float = 0.0   # ROC %; all below → cash
    alloc_ma_filter:      bool = False
    alloc_ma_type:        str = "ema"   # ema | sma | wma | rma
    alloc_ma_length:      int = 50
    alloc_dual:           bool = False  # 50/50 top-2
    alloc_defensive2:     str = "cash"  # off | cash | paxg | paxg_then_cash
    alloc_btc_symbol:     str = "BTCUSDT"
    alloc_paxg_symbol:    str = "PAXGUSDT"

    # ─── Daily Trend Radar (RGG + coil breakouts; signal-only) ───────────
    radar_enabled:            bool = True
    radar_adx_length:         int = 14
    radar_enter_adx:          float = 25.0   # leave GREY → trend
    radar_exit_adx:           float = 20.0   # trend → GREY (Signum band)
    radar_coil_lookback:      int = 20
    radar_coil_max_width_pct: float = 15.0
    radar_fresh_flip_days:    int = 3
    radar_late_stage_days:    int = 30
    radar_late_stage_move_pct: float = 50.0
    radar_kline_limit:        int = 250
    radar_notify:             bool = False   # opt-in digests; /radar still fills
    radar_min_coverage_pct:   float = 50.0
    # Persist + notify 1D GREEN/RED flip and coil-UP/DOWN as breakout setups (manual only)
    radar_dispatch_trend_start: bool = True

    # ─── OpenAI analysis overlay (optional; never scores, never orders) ─
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4.1-mini"
    openai_timeout_sec: float = 20.0
    openai_base_url: str = "https://api.openai.com/v1"

    @property
    def webhook_allowlist(self) -> list[str]:
        return [ip.strip() for ip in self.webhook_allow_ips.split(",") if ip.strip()]

    @property
    def symbols_static(self) -> list[str]:
        return [s.strip().upper() for s in self.scan_symbols.split(",") if s.strip()]

    @property
    def timeframes_list(self) -> list[str]:
        return [t.strip().lower() for t in self.scan_timeframes.split(",") if t.strip()]

    @property
    def htf_map(self) -> dict[str, str]:
        out = {}
        for pair in self.scan_htf_map.split(","):
            if ":" in pair:
                k, v = pair.split(":", 1)
                out[k.strip().lower()] = v.strip().lower()
        return out

    @property
    def weights_total(self) -> int:
        return (self.w_supertrend + self.w_ema + self.w_rsi + self.w_adx
                + self.w_htf + self.w_sr + self.w_vol)

    def validate_runtime(self) -> list[str]:
        """Return list of warnings; called once at startup."""
        warnings = []
        wt = self.weights_total
        # 100 = ST20 + EMA15 + RSI15 + ADX15 + HTF20 + SR10 + VOL5
        if not (95 <= wt <= 105):
            warnings.append(
                f"Weights sum to {wt}, expected ~100. Score scale will be off."
            )
        if self.scan_loop_interval_sec < 5:
            warnings.append(
                f"SCAN_LOOP_INTERVAL_SEC={self.scan_loop_interval_sec} is "
                "very tight; recommended >= 10s."
            )
        if self.scan_min_alert_grade not in ("A+", "A", "B", "C", "REJECT"):
            warnings.append(
                f"SCAN_MIN_ALERT_GRADE={self.scan_min_alert_grade!r} invalid; "
                "expected one of A+/A/B/C/REJECT."
            )
        if self.scan_data_source.lower() not in ("binance", "bybit", "okx"):
            warnings.append(
                f"SCAN_DATA_SOURCE={self.scan_data_source!r} not supported; "
                "expected binance, bybit, or okx."
            )
        if self.alloc_mode.lower() not in ("ranked", "all", "rotation"):
            warnings.append(
                f"ALLOC_MODE={self.alloc_mode!r} invalid; "
                "expected ranked, all, or rotation."
            )
        if self.alloc_defensive2.lower() not in (
            "off", "cash", "paxg", "paxg_then_cash",
        ):
            warnings.append(
                f"ALLOC_DEFENSIVE2={self.alloc_defensive2!r} invalid; "
                "expected off, cash, paxg, or paxg_then_cash."
            )
        if self.radar_exit_adx > self.radar_enter_adx:
            warnings.append(
                f"RADAR_EXIT_ADX={self.radar_exit_adx} > "
                f"RADAR_ENTER_ADX={self.radar_enter_adx}; hysteresis inverted."
            )
        try:
            from scanner.radar import RadarConfig as _RadarConfig
            _RadarConfig(
                adx_length=self.radar_adx_length,
                enter_adx=self.radar_enter_adx,
                exit_adx=self.radar_exit_adx,
                coil_lookback=self.radar_coil_lookback,
                coil_max_width_pct=self.radar_coil_max_width_pct,
                fresh_flip_days=self.radar_fresh_flip_days,
                late_stage_days=self.radar_late_stage_days,
                late_stage_move_pct=self.radar_late_stage_move_pct,
                kline_limit=self.radar_kline_limit,
                notify=self.radar_notify,
                min_coverage_pct=self.radar_min_coverage_pct,
            ).validate()
        except ValueError as e:
            warnings.append(f"Radar config invalid: {e}")
        return warnings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
