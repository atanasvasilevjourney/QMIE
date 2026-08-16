"""
Configuration tests.

Pin the contract on env-var → Settings parsing and the runtime
validators. These tests set environment variables, instantiate
Settings directly (NOT via the cached get_settings()), and assert.
"""
from __future__ import annotations

import importlib

import pytest

from config import Settings


class TestProperties:
    def test_symbols_static_strips_and_uppercases(self):
        s = Settings(scan_symbols=" btcusdt ,ETHUSDT,, solusdt ",
                     webhook_secret="x")
        assert s.symbols_static == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def test_timeframes_list_lowercases(self):
        s = Settings(scan_timeframes="1H,4H,1D", webhook_secret="x")
        assert s.timeframes_list == ["1h", "4h", "1d"]

    def test_htf_map_parses(self):
        s = Settings(scan_htf_map="1h:4h, 4h:1d , 1d:1w",
                     webhook_secret="x")
        assert s.htf_map == {"1h": "4h", "4h": "1d", "1d": "1w"}

    def test_webhook_allowlist(self):
        s = Settings(webhook_allow_ips="1.2.3.4, 5.6.7.8",
                     webhook_secret="x")
        assert s.webhook_allowlist == ["1.2.3.4", "5.6.7.8"]


class TestValidateRuntime:
    def test_default_weights_no_warning(self):
        s = Settings(webhook_secret="x")
        warnings = s.validate_runtime()
        # Default weights sum to 100 → no weight warning
        assert not any("Weights sum" in w for w in warnings)

    def test_lopsided_weights_warns(self):
        s = Settings(webhook_secret="x",
                     w_supertrend=50, w_ema=50, w_rsi=50,
                     w_adx=50, w_htf=50, w_sr=50, w_vol=50)
        warnings = s.validate_runtime()
        assert any("Weights sum" in w for w in warnings)

    def test_busy_loop_warns(self):
        s = Settings(webhook_secret="x", scan_loop_interval_sec=1)
        warnings = s.validate_runtime()
        assert any("LOOP_INTERVAL" in w for w in warnings)

    def test_invalid_grade_warns(self):
        s = Settings(webhook_secret="x", scan_min_alert_grade="ZZ")
        warnings = s.validate_runtime()
        assert any("ALERT_GRADE" in w for w in warnings)

    def test_invalid_data_source_warns(self):
        s = Settings(webhook_secret="x", scan_data_source="kraken")
        warnings = s.validate_runtime()
        assert any("DATA_SOURCE" in w for w in warnings)

    def test_weights_total_property(self):
        s = Settings(webhook_secret="x")
        assert s.weights_total == 100
