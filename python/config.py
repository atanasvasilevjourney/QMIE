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
    # Comma-separated. Defaults to Binance USDT perps top set. Overridable.
    scan_symbols: str = (
        "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,"
        "LINKUSDT,MATICUSDT,DOTUSDT,LTCUSDT,TRXUSDT,ATOMUSDT,NEARUSDT,APTUSDT,"
        "ARBUSDT,OPUSDT,SUIUSDT,INJUSDT,FILUSDT,RNDRUSDT,TIAUSDT,SEIUSDT,"
        "ORDIUSDT,WLDUSDT,FETUSDT,PEPEUSDT,1000PEPEUSDT,BONKUSDT"
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

    # Exchange data source: "binance" | "bybit"
    scan_data_source: str = "binance"
    # Public REST. No auth needed for klines.
    scan_data_timeout_sec: float = 10.0
    scan_max_concurrency:  int = 8

    # Min grade to ALERT on. REJECT/C/B can be set if you want noisier flow.
    scan_min_alert_grade: str = "A"        # A+ | A | B | C | REJECT

    # ─── Signal engine weights (sum=100) ─────────────────────────────────
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
        if self.scan_data_source.lower() not in ("binance", "bybit"):
            warnings.append(
                f"SCAN_DATA_SOURCE={self.scan_data_source!r} not supported; "
                "expected binance or bybit."
            )
        return warnings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
