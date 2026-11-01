"""Load frozen long-vol YAML configs into typed Pydantic models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


class DataConfig(BaseModel):
    exchange: str = "binance_um"
    source: str = "vision"
    base_tf: str = "15m"
    signal_tf: str = "1h"
    cache_dir: str = "backtest/data/cache"
    btc_symbol: str = "BTCUSDT"


class UniverseConfig(BaseModel):
    top_n: int = 100
    rebalance: str = "monthly"
    min_24h_quote_volume_usdt: float = 5_000_000.0
    max_spread_proxy_median: float = 0.0025
    exclude_patterns: list[str] = Field(default_factory=list)


class FeaturesConfig(BaseModel):
    vwap_bars: int = 96
    donchian_entry: int = 20
    donchian_exit: int = 10
    width_pct_lookback_1h_bars: int = 2160
    rvol_tod_days: int = 20
    compression_lookback_1h: int = 12
    compression_width_pct_max: float = 25.0


class EntryConfig(BaseModel):
    dist_atr_min: float = 0.5
    dist_atr_max: float = 2.5
    rvol_min: float = 2.0
    adx_min: float = 18.0
    adx_max: float = 35.0
    rsi_max: float = 72.0
    no_chase_rsi: float = 75.0
    no_chase_dist_atr: float = 3.0
    cooldown_bars: int = 24


class ExitConfig(BaseModel):
    stop_atr_mult: float = 2.0
    vwap_exit_bars: int = 2
    time_stop_bars: int = 24


class RiskConfig(BaseModel):
    risk_pct: float = 0.0025
    max_participation: float = 0.03
    max_gross_leverage: float = 1.0
    max_positions: int = 3
    max_correlated: int = 2
    correlation_lookback_days: int = 7
    correlation_threshold: float = 0.7


class CostsConfig(BaseModel):
    taker_fee: float = 0.00055
    slippage_k: float = 0.1
    cost_mult_default: float = 1.0


class BacktestConfig(BaseModel):
    initial_equity: float = 100_000.0
    lockbox_frac: float = 0.2
    dev_end: Optional[str] = None


class WalkforwardConfig(BaseModel):
    train_months: int = 6
    test_months: int = 2


class MonteCarloConfig(BaseModel):
    seed: int = 42
    draws: int = 1000


class RandomBaselineConfig(BaseModel):
    seed: int = 42
    draws: int = 200


class LongVolConfig(BaseModel):
    version: int = 1
    name: str = "long_vol_breakout_v1"
    data: DataConfig = Field(default_factory=DataConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    entry: EntryConfig = Field(default_factory=EntryConfig)
    exit: ExitConfig = Field(default_factory=ExitConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    costs: CostsConfig = Field(default_factory=CostsConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    walkforward: WalkforwardConfig = Field(default_factory=WalkforwardConfig)
    monte_carlo: MonteCarloConfig = Field(default_factory=MonteCarloConfig)
    random_baseline: RandomBaselineConfig = Field(default_factory=RandomBaselineConfig)


_V1_PATH = Path(__file__).resolve().parent.parent / "configs" / "long_vol_v1.yaml"
_V1_SHA256: Optional[str] = None


def _v1_expected_hash() -> str:
    global _V1_SHA256
    if _V1_SHA256 is None:
        _V1_SHA256 = hashlib.sha256(_V1_PATH.read_bytes()).hexdigest()
    return _V1_SHA256


def load_config(path: Path | str, *, allow_v1_override: bool = False) -> LongVolConfig:
    """Load YAML config. Frozen v1 file must match baked SHA256 unless override env/test flag."""
    p = Path(path)
    raw = yaml.safe_load(p.read_text())
    if p.name == "long_vol_v1.yaml" and not allow_v1_override:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest != _v1_expected_hash():
            raise ValueError(
                "long_vol_v1.yaml was modified; create long_vol_v2.yaml instead "
                f"(expected sha256 {_v1_expected_hash()[:12]}…, got {digest[:12]}…)"
            )
    return LongVolConfig.model_validate(raw)


def config_hash(cfg: LongVolConfig) -> str:
    """Stable hash of config for caching and run_id."""
    payload = cfg.model_dump(mode="json")
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
