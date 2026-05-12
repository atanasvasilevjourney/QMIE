"""
Dispatcher tests.

Verifies:
  * Sub-grade signals are filtered out
  * Duplicate bar-closes don't double-fire
  * TV chart deep-link is injected into the TVSignal
  * Notifier failures are isolated (gather return_exceptions)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from models import Grade
from scanner.dispatcher import SignalDispatcher, tv_chart_url
from scanner.signal_engine import ScanResult


def _make_result(grade="A", side="BUY") -> ScanResult:
    return ScanResult(
        symbol="BTCUSDT",
        timeframe="4h",
        timestamp=pd.Timestamp("2024-06-01 12:00:00", tz="UTC"),
        side=side,
        grade=grade,
        score=85.0,
        price=50000.0,
        stop_loss=49000.0,
        take_profit=52000.0,
        atr_value=500.0,
        atr_pct=1.0,
        rsi_value=60.0,
        adx_value=30.0,
        htf_aligned=True,
        nearest_res=2.5,
        nearest_sup=1.8,
        components={"st_dir": 1, "agreement": 3},
        reason="BUY: ST+ EMA+",
    )


class _InMemIdem:
    def __init__(self):
        self.seen = set()

    async def seen_or_mark(self, key: str) -> bool:
        if key in self.seen:
            return True
        self.seen.add(key)
        return False


class _DummyDB:
    def __init__(self):
        self.inserts = 0

    async def insert_signal(self, sig):
        self.inserts += 1


class _MockNotifier:
    def __init__(self, name="mock", fail=False):
        self.name = name
        self.enabled = True
        self.fail = fail
        self.sent: list = []

    async def send_signal(self, sig, broker_resp):
        if self.fail:
            raise RuntimeError("notifier down")
        self.sent.append(sig)

    async def send_text(self, msg): pass
    async def close(self): pass


# ════════════════════════════════════════════════════════════════════════
class TestTVChartUrl:
    def test_basic_4h(self):
        url = tv_chart_url("BTCUSDT", "4h", "BINANCE")
        assert "BINANCE:BTCUSDT.P" in url
        assert "interval=240" in url

    def test_1d_uses_D(self):
        url = tv_chart_url("BTCUSDT", "1d", "BINANCE")
        assert "interval=D" in url

    def test_bybit_prefix_no_perp_suffix(self):
        url = tv_chart_url("BTCUSDT", "4h", "BYBIT")
        # Bybit doesn't get the .P auto-append (different convention)
        assert "BYBIT:BTCUSDT" in url
        assert ".P" not in url.split("symbol=")[1].split("&")[0]

    def test_already_has_perp_suffix(self):
        url = tv_chart_url("BTCUSDT.P", "4h", "BINANCE")
        # Should not double up to .P.P
        assert ".P.P" not in url


# ════════════════════════════════════════════════════════════════════════
class TestDispatch:
    @pytest.fixture
    def setup(self):
        idem = _InMemIdem()
        db = _DummyDB()
        n = _MockNotifier()
        d = SignalDispatcher(
            db=db, notifiers=[n], idem=idem,
            min_alert_grade=Grade.A, tv_chart_prefix="BINANCE",
        )
        return d, n, db, idem

    async def test_dispatches_grade_a(self, setup):
        d, n, db, _ = setup
        ok = await d.dispatch(_make_result(grade="A"))
        assert ok is True
        assert len(n.sent) == 1
        assert db.inserts == 1

    async def test_filters_grade_b(self, setup):
        d, n, _, _ = setup
        ok = await d.dispatch(_make_result(grade="B"))
        assert ok is False
        assert len(n.sent) == 0

    async def test_dedup_same_bar(self, setup):
        d, n, _, _ = setup
        r = _make_result()
        first = await d.dispatch(r)
        second = await d.dispatch(r)
        assert first is True
        assert second is False
        assert len(n.sent) == 1     # only one notification

    async def test_chart_url_injected(self, setup):
        d, n, _, _ = setup
        await d.dispatch(_make_result())
        sig = n.sent[0]
        assert hasattr(sig, "chart_url")
        url = getattr(sig, "chart_url")
        assert "BINANCE:BTCUSDT.P" in url
        assert "interval=240" in url

    async def test_notifier_failure_isolated(self):
        """A failing notifier must NOT prevent dispatch of others."""
        idem = _InMemIdem()
        n_bad = _MockNotifier(name="bad", fail=True)
        n_good = _MockNotifier(name="good")
        d = SignalDispatcher(
            db=_DummyDB(), notifiers=[n_bad, n_good], idem=idem,
            min_alert_grade=Grade.A, tv_chart_prefix="BINANCE",
        )
        ok = await d.dispatch(_make_result())
        assert ok is True
        assert len(n_good.sent) == 1            # good one received it

    async def test_grade_a_plus_passes_min_a(self, setup):
        d, n, _, _ = setup
        ok = await d.dispatch(_make_result(grade="A+"))
        assert ok is True

    async def test_min_grade_a_plus_excludes_a(self):
        idem = _InMemIdem()
        n = _MockNotifier()
        d = SignalDispatcher(
            db=_DummyDB(), notifiers=[n], idem=idem,
            min_alert_grade=Grade.A_PLUS, tv_chart_prefix="BINANCE",
        )
        ok = await d.dispatch(_make_result(grade="A"))
        assert ok is False
