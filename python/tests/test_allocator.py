"""Ranked asset allocation: which swing alerts to take, suggested size.

Does not place orders. Cluster cap is the correlated-name rule.
"""
from __future__ import annotations

import pandas as pd

from scanner.allocator import AllocConfig, allocate, cluster_of
from scanner.signal_engine import ScanResult


def _sr(symbol: str, *, side="BUY", grade="A", score=80.0) -> ScanResult:
    return ScanResult(
        symbol=symbol,
        timeframe="4h",
        timestamp=pd.Timestamp("2024-06-01 12:00:00", tz="UTC"),
        side=side,
        grade=grade,
        score=score,
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


class TestClusterOf:
    def test_known_clusters(self):
        assert cluster_of("BTCUSDT") == "BTC"
        assert cluster_of("ETHUSDT") == "ETH"
        assert cluster_of("ARBUSDT") == "ETH"
        assert cluster_of("SOLUSDT") == "SOL"

    def test_unknown_is_other(self):
        assert cluster_of("DOGEUSDT") == "OTHER"


class TestAllocate:
    def test_ranks_by_score_and_caps_top_n(self):
        results = [
            _sr("AAAUSDT", score=50),
            _sr("BTCUSDT", score=90),
            _sr("ETHUSDT", score=80),
            _sr("SOLUSDT", score=70),
            _sr("BNBUSDT", score=60),
        ]
        plan = allocate(
            results,
            AllocConfig(mode="ranked", top_long=3, top_short=3, cluster_max=0),
            timeframe="4h",
        )
        longs = [s for s in plan.slots if s.side == "BUY"]
        assert [s.result.symbol for s in longs] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        assert [s.rank for s in longs] == [1, 2, 3]
        assert longs[0].result.alloc_rank == 1
        assert longs[0].result.alloc_cluster == "BTC"

    def test_skips_below_min_grade(self):
        results = [
            _sr("BTCUSDT", grade="A", score=90),
            _sr("ETHUSDT", grade="B", score=99),
        ]
        plan = allocate(results, AllocConfig(min_grade="A", cluster_max=0))
        assert plan.skipped_grade == 1
        assert [s.result.symbol for s in plan.slots] == ["BTCUSDT"]

    def test_cluster_max_drops_correlated_names(self):
        results = [
            _sr("ETHUSDT", score=90),
            _sr("ARBUSDT", score=89),
            _sr("SOLUSDT", score=70),
        ]
        plan = allocate(
            results,
            AllocConfig(top_long=3, cluster_max=1),
        )
        symbols = [s.result.symbol for s in plan.slots]
        assert "ETHUSDT" in symbols
        assert "ARBUSDT" not in symbols
        assert "SOLUSDT" in symbols

    def test_rank_weights_sum_to_100_one_side(self):
        results = [
            _sr("BTCUSDT", score=90),
            _sr("ETHUSDT", score=80),
            _sr("SOLUSDT", score=70),
        ]
        plan = allocate(
            results,
            AllocConfig(top_long=3, top_short=3, weighting="rank", cluster_max=0),
        )
        total = sum(s.weight_pct for s in plan.slots)
        assert total == 100.0
        # 3+2+1 = 6 → 50, 33.33, 16.67
        longs = [s.weight_pct for s in plan.slots]
        assert longs[0] == 50.0
        assert longs[1] == 33.33
        assert longs[2] == 16.67

    def test_split_book_50_50_when_both_sides(self):
        results = [
            _sr("BTCUSDT", side="BUY", score=90),
            _sr("ETHUSDT", side="BUY", score=80),
            _sr("SOLUSDT", side="SELL", score=85),
        ]
        plan = allocate(
            results,
            AllocConfig(top_long=3, top_short=3, weighting="equal", cluster_max=0),
        )
        long_w = sum(s.weight_pct for s in plan.slots if s.side == "BUY")
        short_w = sum(s.weight_pct for s in plan.slots if s.side == "SELL")
        assert long_w == 50.0
        assert short_w == 50.0
        assert abs(long_w + short_w - 100.0) < 1e-9

    def test_equal_weights(self):
        results = [_sr("BTCUSDT", score=90), _sr("ETHUSDT", score=80)]
        plan = allocate(
            results,
            AllocConfig(top_long=2, weighting="equal", cluster_max=0),
        )
        assert [s.weight_pct for s in plan.slots] == [50.0, 50.0]

    def test_as_dict_shape(self):
        plan = allocate([_sr("BTCUSDT")], AllocConfig(cluster_max=0), timeframe="1h")
        d = plan.as_dict()
        assert d["timeframe"] == "1h"
        assert d["considered"] == 1
        assert d["slots"][0]["symbol"] == "BTCUSDT"
        assert d["slots"][0]["rank"] == 1
