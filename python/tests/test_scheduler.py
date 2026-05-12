"""
Scheduler bar-close detection tests.

Critical correctness: the scheduler must scan only on bar boundaries,
exactly once per closed bar, with a small grace window. Off-by-one
here means duplicate alerts or missed signals.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from scanner.scheduler import ScannerScheduler, _last_close_ts, _tf_seconds
from scanner.signal_engine import Weights


# ════════════════════════════════════════════════════════════════════════
class TestTfSeconds:
    @pytest.mark.parametrize("tf,expected", [
        ("1m", 60), ("5m", 300), ("15m", 900),
        ("1h", 3600), ("4h", 14400), ("1d", 86400),
    ])
    def test_known_timeframes(self, tf, expected):
        assert _tf_seconds(tf) == expected

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            _tf_seconds("3y")


# ════════════════════════════════════════════════════════════════════════
class TestLastCloseTs:
    def test_4h_alignment(self):
        # 2024-01-15 13:30:00 UTC = epoch 1705325400
        # Last 4h boundary: 12:00 UTC = epoch 1705320000
        now = 1705325400
        assert _last_close_ts(now, 14400) == 1705320000

    def test_1h_alignment(self):
        # 13:30 UTC → last 1h boundary = 13:00
        now = 1705325400
        assert _last_close_ts(now, 3600) == 1705323600

    def test_exactly_on_boundary(self):
        # Right on a 4h boundary
        boundary = 1705320000     # 2024-01-15 12:00 UTC
        assert _last_close_ts(boundary, 14400) == boundary


# ════════════════════════════════════════════════════════════════════════
class TestSchedulerTick:
    @pytest.fixture
    def fake_components(self):
        client = MagicMock()
        client.fetch_klines = AsyncMock(return_value=None)
        universe = MagicMock()
        universe.get = AsyncMock(return_value=["BTCUSDT"])
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=False)
        return client, universe, dispatcher

    @pytest.fixture
    def scheduler(self, fake_components):
        client, universe, dispatcher = fake_components
        return ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["1h"],
            htf_map={"1h": "4h"},
            weights=Weights(),
            loop_interval_sec=30,
            max_concurrency=2,
        )

    async def test_no_scan_before_bar_close_grace(self, scheduler):
        """If we just crossed a bar boundary <5s ago, _tick() must NOT scan.
        This prevents racing the exchange before it has the closed bar."""
        now = int(time.time())
        # Pretend last seen is in the distant past, but current bar closed 1s ago
        boundary = (now // 3600) * 3600
        scheduler._last_seen["1h"] = boundary - 3600  # one bar ago
        # Monkey-patch time.time inside the test
        import scanner.scheduler as mod
        orig = mod.time.time
        try:
            mod.time.time = lambda: boundary + 1     # 1s past boundary
            await scheduler._tick()
            # Should NOT have called fetch_klines yet
            scheduler.client.fetch_klines.assert_not_called()
        finally:
            mod.time.time = orig

    async def test_scan_fires_after_grace(self, scheduler):
        now = int(time.time())
        boundary = (now // 3600) * 3600
        scheduler._last_seen["1h"] = boundary - 3600
        import scanner.scheduler as mod
        orig = mod.time.time
        try:
            # 6 seconds past boundary: outside the 5s grace
            mod.time.time = lambda: boundary + 6
            await scheduler._tick()
            # Should have advanced last_seen
            assert scheduler._last_seen["1h"] == boundary
        finally:
            mod.time.time = orig

    async def test_no_double_scan_same_bar(self, scheduler):
        """After a successful scan, hitting _tick() again with no new bar
        boundary must not trigger another pass."""
        now = int(time.time())
        boundary = (now // 3600) * 3600
        scheduler._last_seen["1h"] = boundary       # already scanned this bar
        import scanner.scheduler as mod
        orig = mod.time.time
        try:
            mod.time.time = lambda: boundary + 30
            await scheduler._tick()
            scheduler.client.fetch_klines.assert_not_called()
        finally:
            mod.time.time = orig
