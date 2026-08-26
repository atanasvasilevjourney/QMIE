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
        dispatcher.dispatch_inbound = AsyncMock(return_value=False)
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


class TestRadarPass:
    """Daily Trend Radar fires independently of SCAN_TIMEFRAMES."""

    @pytest.fixture
    def fake_components(self):
        client = MagicMock()
        client.fetch_klines = AsyncMock(return_value=None)
        universe = MagicMock()
        universe.get = AsyncMock(return_value=["BTCUSDT"])
        dispatcher = MagicMock()
        dispatcher.dispatch_inbound = AsyncMock(return_value=False)
        dispatcher.dispatch = AsyncMock(return_value=False)
        return client, universe, dispatcher

    @pytest.fixture
    def bull_daily(self, bull_trend_df):
        import pandas as pd
        df = bull_trend_df.copy()
        df.index = pd.date_range("2024-01-01", periods=len(df), freq="1D", tz="UTC")
        return df

    async def test_radar_pass_builds_snapshot(self, fake_components, bull_daily):
        client, universe, dispatcher = fake_components
        client.fetch_klines = AsyncMock(return_value=bull_daily)
        dispatcher.notifiers = []
        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["1h"],
            htf_map={"1h": "4h"},
            weights=Weights(),
            radar_enabled=True,
        )
        ok = await scheduler._radar_pass(notify=False)
        assert ok is True
        assert scheduler.last_radar is not None
        assert scheduler.last_radar.count >= 1
        assert scheduler.last_radar.status in ("ready", "incomplete")
        assert scheduler.stats["radar_passes"] == 1
        client.fetch_klines.assert_called()
        assert client.fetch_klines.call_args.args[1] == "1d"

    async def test_radar_tick_fires_after_daily_grace(self, fake_components, bull_daily):
        client, universe, dispatcher = fake_components
        client.fetch_klines = AsyncMock(return_value=bull_daily)
        dispatcher.notifiers = []
        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["1h"],
            htf_map={"1h": "4h"},
            weights=Weights(),
            radar_enabled=True,
        )
        now = int(time.time())
        day_boundary = (now // 86400) * 86400
        scheduler._last_radar_seen = day_boundary - 86400
        hour_boundary = (now // 3600) * 3600
        scheduler._last_seen["1h"] = hour_boundary
        import scanner.scheduler as mod
        orig = mod.time.time
        try:
            mod.time.time = lambda: day_boundary + 10
            await scheduler._tick()
        finally:
            mod.time.time = orig
        assert scheduler.stats["radar_passes"] == 1
        assert scheduler.last_radar is not None
        assert scheduler._last_radar_seen == day_boundary

    async def test_radar_total_failure_keeps_previous(self, fake_components, bull_daily):
        client, universe, dispatcher = fake_components
        client.fetch_klines = AsyncMock(return_value=bull_daily)
        dispatcher.notifiers = []
        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["1h"],
            htf_map={"1h": "4h"},
            radar_enabled=True,
        )
        assert await scheduler._radar_pass(notify=False) is True
        prev = scheduler.last_radar
        # Next pass: all fetches fail
        client.fetch_klines = AsyncMock(side_effect=RuntimeError("boom"))
        ok = await scheduler._radar_pass(notify=False)
        assert ok is False
        assert scheduler.last_radar is prev

    async def test_request_radar_once_coalesces(self, fake_components, bull_daily):
        client, universe, dispatcher = fake_components
        client.fetch_klines = AsyncMock(return_value=bull_daily)
        dispatcher.notifiers = []
        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["1h"],
            htf_map={"1h": "4h"},
            radar_enabled=True,
        )
        # Hold the lock so a concurrent request reports already_running
        await scheduler._radar_lock.acquire()
        try:
            r = await scheduler.request_radar_once(notify=False)
            assert r.get("already_running") is True
        finally:
            scheduler._radar_lock.release()

    async def test_dispatch_trend_starts_sends_long_and_short(self, fake_components):
        client, universe, dispatcher = fake_components
        dispatcher.dispatch_inbound = AsyncMock(return_value=True)
        dispatcher.paper = None
        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["1h"],
            htf_map={"1h": "4h"},
            radar_enabled=True,
            radar_dispatch_trend_start=True,
        )
        snap = MagicMock()
        snap.rows = [
            {
                "symbol": "ETHUSDT",
                "color": "GREEN",
                "days_in_state": 1,
                "state_censored": False,
                "breakout": "UP",
                "coil_low": 2900.0,
                "price": 3000.0,
                "adx": 28.0,
                "bar_time": "2026-08-16T00:00:00+00:00",
            },
            {
                "symbol": "SOLUSDT",
                "color": "RED",
                "days_in_state": 1,
                "state_censored": False,
                "breakout": "DOWN",
                "coil_high": 160.0,
                "price": 145.0,
                "adx": 30.0,
                "bar_time": "2026-08-16T00:00:00+00:00",
            },
        ]
        n = await scheduler._dispatch_trend_starts(snap)
        assert n == 2
        assert dispatcher.dispatch_inbound.await_count == 2
        sides = {c.args[0].side.value for c in dispatcher.dispatch_inbound.await_args_list}
        assert sides == {"BUY", "SELL"}
        shorts = [
            c.args[0]
            for c in dispatcher.dispatch_inbound.await_args_list
            if c.args[0].side.value == "SELL"
        ]
        assert shorts[0].stop_loss == 160.0
        assert shorts[0].strategy == "QMIE-DailyBreakout"


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
        dispatcher.dispatch_inbound = AsyncMock(return_value=False)
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
        dispatcher.dispatch_inbound = AsyncMock(return_value=False)
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


class TestRankedDispatch:
    """Ranked mode dispatches only allocated slots, not the full scan."""

    @pytest.mark.asyncio
    async def test_ranked_mode_dispatches_top_n_only(self):
        from unittest.mock import patch

        import pandas as pd

        from scanner.allocator import AllocConfig
        from scanner.signal_engine import ScanResult

        scores = {
            "BTCUSDT": 90.0,
            "ETHUSDT": 80.0,
            "SOLUSDT": 70.0,
            "BNBUSDT": 60.0,
            "DOGEUSDT": 50.0,
        }

        def fake_compute(df, *, symbol, timeframe, **kw):
            return ScanResult(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=pd.Timestamp("2024-06-01 12:00:00", tz="UTC"),
                side="BUY",
                grade="A",
                score=scores[symbol],
                price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                atr_value=1.0,
                atr_pct=1.0,
                rsi_value=55.0,
                adx_value=30.0,
                htf_aligned=True,
                nearest_res=1.0,
                nearest_sup=1.0,
            )

        fake_df = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            index=pd.date_range("2024-01-01", periods=300, freq="1h"),
        )

        client = AsyncMock()
        client.fetch_klines = AsyncMock(return_value=fake_df)
        client.fetch_premium_index = AsyncMock(return_value={"lastFundingRate": 0.0})

        dispatched: list[str] = []
        dispatcher = MagicMock()
        dispatcher.dispatch_inbound = AsyncMock(return_value=False)

        async def capture(res):
            dispatched.append(res.symbol)
            return True

        dispatcher.dispatch = capture

        universe = MagicMock()
        universe.get = AsyncMock(return_value=list(scores))

        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["1h"],
            htf_map={"1h": "4h"},
            alloc_cfg=AllocConfig(
                mode="ranked",
                top_long=2,
                top_short=2,
                cluster_max=0,
            ),
        )

        with patch("scanner.scheduler.compute_signal", side_effect=fake_compute):
            await scheduler._scan_pass("1h")

        assert dispatched == ["BTCUSDT", "ETHUSDT"]
        assert scheduler.last_allocation is not None
        assert len(scheduler.last_allocation.slots) == 2
        assert scheduler.stats["alerts_dispatched"] == 2

    @pytest.mark.asyncio
    async def test_all_mode_dispatches_every_result(self):
        from unittest.mock import patch

        import pandas as pd

        from scanner.allocator import AllocConfig
        from scanner.signal_engine import ScanResult

        def fake_compute(df, *, symbol, timeframe, **kw):
            return ScanResult(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=pd.Timestamp("2024-06-01 12:00:00", tz="UTC"),
                side="BUY",
                grade="A",
                score=80.0,
                price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                atr_value=1.0,
                atr_pct=1.0,
                rsi_value=55.0,
                adx_value=30.0,
                htf_aligned=True,
                nearest_res=1.0,
                nearest_sup=1.0,
            )

        fake_df = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            index=pd.date_range("2024-01-01", periods=300, freq="1h"),
        )
        client = AsyncMock()
        client.fetch_klines = AsyncMock(return_value=fake_df)
        client.fetch_premium_index = AsyncMock(return_value={"lastFundingRate": 0.0})

        dispatched: list[str] = []
        dispatcher = MagicMock()
        dispatcher.dispatch_inbound = AsyncMock(return_value=False)

        async def capture(res):
            dispatched.append(res.symbol)
            return True

        dispatcher.dispatch = capture
        universe = MagicMock()
        universe.get = AsyncMock(return_value=["BTCUSDT", "ETHUSDT", "SOLUSDT"])

        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["1h"],
            htf_map={"1h": "4h"},
            alloc_cfg=AllocConfig(mode="all"),
        )
        with patch("scanner.scheduler.compute_signal", side_effect=fake_compute):
            await scheduler._scan_pass("1h")

        assert set(dispatched) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}


class TestRotationDispatch:
    @pytest.mark.asyncio
    async def test_rotation_alerts_only_on_switch(self):
        import pandas as pd

        from scanner.allocator import AllocConfig

        lasts = {"ETHUSDT": 120.0, "SOLUSDT": 110.0, "BTCUSDT": 101.0}

        async def fake_fetch(sym, tf, limit=300):
            n = 80
            last = lasts[sym]
            idx = pd.date_range("2024-01-01", periods=n, freq="1D")
            close = pd.Series([100.0] * (n - 1) + [last], index=idx)
            return pd.DataFrame(
                {"open": close, "high": close, "low": close, "close": close, "volume": 1.0},
                index=idx,
            )

        client = MagicMock()
        client.fetch_klines = fake_fetch
        client.fetch_premium_index = AsyncMock(return_value={"lastFundingRate": 0.0})

        dispatched: list[str] = []
        dispatcher = MagicMock()
        dispatcher.dispatch_inbound = AsyncMock(return_value=False)
        dispatcher.notifiers = []

        async def capture(res):
            dispatched.append(res.symbol)
            return True

        dispatcher.dispatch = capture
        universe = MagicMock()
        universe.get = AsyncMock(return_value=["BTCUSDT", "ETHUSDT", "SOLUSDT"])

        scheduler = ScannerScheduler(
            client=client,
            universe=universe,
            dispatcher=dispatcher,
            timeframes=["1d"],
            htf_map={"1d": "1w"},
            alloc_cfg=AllocConfig(
                mode="rotation",
                dual=False,
                defensive2="off",
                cluster_max=0,
                norm_length=20,
                ma_length=10,
            ),
        )
        await scheduler._scan_pass("1d")
        first = list(dispatched)
        await scheduler._scan_pass("1d")

        assert first == ["ETHUSDT"]
        assert dispatched == ["ETHUSDT"]
        assert scheduler.last_allocation.regime == "LIVE"

