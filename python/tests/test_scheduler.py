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


class TestDailyDfRouting:
    """Verify that scan_one passes the correct daily_df to compute_signal."""

    @pytest.mark.asyncio
    async def test_4h_scan_reuses_htf_as_daily_df(self, monkeypatch):
        """For a 4H scan (HTF=1d), daily_df must equal htf_df — no extra fetch."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import pandas as pd

        captured: dict = {}

        def fake_compute(df, *, symbol, timeframe, htf_df=None, daily_df=None, **kw):
            captured["daily_df"] = daily_df
            captured["htf_df"] = htf_df
            return None  # skip full scoring

        fake_df = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            index=pd.date_range("2024-01-01", periods=300, freq="1h"),
        )
        fake_daily = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            index=pd.date_range("2024-01-01", periods=300, freq="1D"),
        )

        async def fake_fetch(sym, tf, limit=300):
            if tf == "4h":
                return fake_df
            if tf == "1d":
                return fake_daily
            return fake_df

        client = AsyncMock()
        client.fetch_klines = fake_fetch

        from scanner.dispatcher import SignalDispatcher
        from scanner.symbol_universe import SymbolUniverse
        from scanner.scheduler import ScannerScheduler

        universe = MagicMock()
        universe.get = AsyncMock(return_value=["BTCUSDT"])
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=False)

        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["4h"],
            htf_map={"4h": "1d"},
        )

        with patch("scanner.scheduler.compute_signal", side_effect=fake_compute):
            await scheduler._scan_pass("4h")

        # For 4H, htf="1d" so daily_df should be the same object as htf_df
        assert captured.get("daily_df") is captured.get("htf_df")

    @pytest.mark.asyncio
    async def test_1h_scan_fetches_daily_separately(self, monkeypatch):
        """For a 1H scan (HTF=4h), daily_df is a separate fetch of '1d'."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import pandas as pd

        captured: dict = {}
        fetched_tfs: list = []

        def fake_compute(df, *, symbol, timeframe, htf_df=None, daily_df=None, **kw):
            captured["daily_df"] = daily_df
            captured["htf_df"] = htf_df
            return None

        fake_df = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            index=pd.date_range("2024-01-01", periods=300, freq="1h"),
        )

        async def fake_fetch(sym, tf, limit=300):
            fetched_tfs.append(tf)
            # Return a distinct copy per call so identity checks work correctly
            return fake_df.copy()

        client = AsyncMock()
        client.fetch_klines = fake_fetch

        from scanner.symbol_universe import SymbolUniverse
        from scanner.scheduler import ScannerScheduler

        universe = MagicMock()
        universe.get = AsyncMock(return_value=["BTCUSDT"])
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=False)

        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["1h"],
            htf_map={"1h": "4h"},
        )

        with patch("scanner.scheduler.compute_signal", side_effect=fake_compute):
            await scheduler._scan_pass("1h")

        assert "1d" in fetched_tfs, "Expected a separate 1d fetch for 1H scan"
        assert captured.get("daily_df") is not None
        assert captured.get("daily_df") is not captured.get("htf_df")
