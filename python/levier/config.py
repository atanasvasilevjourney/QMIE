from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ScanConfig(BaseModel):
    timeframe: str = "30m"
    vwap_bars: int = 48
    atr_length: int = 14
    rsi_length: int = 14
    adx_length: int = 14
    min_bars: int = 60


class UniverseConfig(BaseModel):
    min_24h_quote_volume_usdt: float = 200_000.0
    top_n_leaderboard: int = 10
    min_atr_pct: float = 0.15
    max_atr_pct: float = 8.0


class GainersConfig(BaseModel):
    lookback_days: int = 1
    top_n_yesterday: int = 20
    continuation_min_dist_pct: float = 1.0


class AlertsConfig(BaseModel):
    notify_top_n: int = 3
    notify_new_leader_only: bool = True
    min_dist_pct_for_alert: float = 2.0


class LevierConfig(BaseModel):
    version: int = 1
    name: str = "levier_scan_v1"
    scan: ScanConfig = Field(default_factory=ScanConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    gainers: GainersConfig = Field(default_factory=GainersConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)


def load_levier_config(path: Path | str) -> LevierConfig:
    p = Path(path)
    raw = yaml.safe_load(p.read_text())
    return LevierConfig.model_validate(raw)
