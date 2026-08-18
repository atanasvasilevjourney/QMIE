"""Asset-rotation (ARS-style) ranking: lookback ROC, cash, dual, BTC-weak."""
from __future__ import annotations

import pandas as pd
import pytest

from scanner.allocator import AllocConfig, allocate
from scanner.rotation import (
    decide_rotation,
    ma_holds,
    normalized_score,
    simulate_equity,
)
from scanner.signal_engine import ScanResult


def _q(symbol: str, *, roc: float, ma_ok: bool = True, side="BUY") -> ScanResult:
    r = ScanResult(
        symbol=symbol,
        timeframe="1d",
        timestamp=pd.Timestamp("2024-06-01", tz="UTC"),
        side=side,
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
        norm_score=roc,
        ma_ok=ma_ok,
    )
    return r


def test_normalized_score_is_percent_change():
    close = pd.Series([100.0, 101.0, 110.0])
    assert normalized_score(close, 2) == pytest.approx(10.0)


def test_normalized_score_nan_if_short():
    close = pd.Series([100.0, 101.0])
    assert pd.isna(normalized_score(close, 2))


def test_ma_holds_above_sma():
    close = pd.Series([1.0, 1.0, 1.0, 1.0, 2.0])
    assert ma_holds(close, 4, "sma") is True


def test_ma_holds_below_sma():
    close = pd.Series([2.0, 2.0, 2.0, 2.0, 1.0])
    assert ma_holds(close, 4, "sma") is False


def test_leader_takes_100_when_dual_off():
    d = decide_rotation(
        [_q("ETHUSDT", roc=8.0), _q("BTCUSDT", roc=3.0), _q("SOLUSDT", roc=5.0)],
        threshold=0.0, ma_filter=False, dual=False, defensive2="off",
        cluster_max=0,
    )
    assert d.regime == "LIVE"
    assert [w.symbol for w in d.winners] == ["ETHUSDT"]


def test_dual_splits_top_two():
    quotes = [_q("ETHUSDT", roc=8.0), _q("BTCUSDT", roc=3.0), _q("SOLUSDT", roc=5.0)]
    d = decide_rotation(
        quotes, threshold=0.0, ma_filter=False, dual=True, defensive2="off",
        cluster_max=0,
    )
    assert [w.symbol for w in d.winners] == ["ETHUSDT", "SOLUSDT"]
    plan = allocate(quotes, AllocConfig(mode="rotation", dual=True, defensive2="off", cluster_max=0))
    w = {s.result.symbol: s.weight_pct for s in plan.slots}
    assert w["ETHUSDT"] == 50.0
    assert w["SOLUSDT"] == 50.0


def test_cash_when_all_below_threshold():
    d = decide_rotation(
        [_q("BTCUSDT", roc=-2.0), _q("ETHUSDT", roc=-1.0)],
        threshold=0.0, ma_filter=False, dual=False, defensive2="off",
    )
    assert d.regime == "CASH"
    assert d.defensive == "threshold"
    assert d.winners == []


def test_ma_filter_drops_leader():
    d = decide_rotation(
        [_q("ETHUSDT", roc=8.0, ma_ok=False), _q("BTCUSDT", roc=3.0, ma_ok=True)],
        threshold=0.0, ma_filter=True, dual=False, defensive2="off",
        cluster_max=0,
    )
    assert [w.symbol for w in d.winners] == ["BTCUSDT"]


def test_defensive2_cash_when_btc_weak():
    d = decide_rotation(
        [_q("ETHUSDT", roc=12.0), _q("BTCUSDT", roc=-1.0)],
        threshold=0.0, ma_filter=False, dual=False, defensive2="cash",
        cluster_max=0,
    )
    assert d.regime == "CASH"
    assert d.defensive == "btc_weak"


def test_defensive2_off_ignores_btc_weak():
    d = decide_rotation(
        [_q("ETHUSDT", roc=12.0), _q("BTCUSDT", roc=-1.0)],
        threshold=0.0, ma_filter=False, dual=False, defensive2="off",
        cluster_max=0,
    )
    assert d.regime == "LIVE"
    assert [w.symbol for w in d.winners] == ["ETHUSDT"]


def test_paxg_then_cash_uses_paxg_when_check_ok():
    d = decide_rotation(
        [
            _q("ETHUSDT", roc=12.0),
            _q("BTCUSDT", roc=-1.0),
            _q("PAXGUSDT", roc=1.0, ma_ok=True),
        ],
        threshold=0.0, ma_filter=False, dual=False,
        defensive2="paxg_then_cash", cluster_max=0,
    )
    assert d.regime == "PAXG"
    assert [w.symbol for w in d.winners] == ["PAXGUSDT"]


def test_paxg_then_cash_falls_to_cash():
    d = decide_rotation(
        [
            _q("ETHUSDT", roc=12.0),
            _q("BTCUSDT", roc=-1.0),
            _q("PAXGUSDT", roc=-3.0, ma_ok=False),
        ],
        threshold=0.0, ma_filter=False, dual=False,
        defensive2="paxg_then_cash", cluster_max=0,
    )
    assert d.regime == "CASH"
    assert d.winners == []


def test_allocate_rotation_force_dispatch_and_regime():
    plan = allocate(
        [_q("SOLUSDT", roc=4.0), _q("BTCUSDT", roc=1.0)],
        AllocConfig(mode="rotation", dual=False, defensive2="off", cluster_max=0),
        timeframe="1d",
    )
    assert plan.regime == "LIVE"
    assert plan.slots[0].result.force_dispatch is True
    assert plan.slots[0].result.alloc_regime == "LIVE"
    assert plan.as_dict()["mode"] == "rotation"


def test_simulate_equity_charges_switch_and_compounds():
    idx = pd.date_range("2024-01-01", periods=3, freq="1D")
    prices = {
        "AAA": pd.Series([100.0, 110.0, 110.0], index=idx),
        "BBB": pd.Series([50.0, 50.0, 60.0], index=idx),
    }
    holdings = pd.Series(["AAA", "AAA", "BBB"], index=idx)
    eq = simulate_equity(prices, holdings, initial=1000.0, fee_pct=0.0, slippage_pct=0.0)
    assert eq.iloc[0] == 1000.0
    assert eq.iloc[1] == 1100.0  # +10% while holding AAA
    assert eq.iloc[2] == 1320.0  # switch to BBB, +20% on BBB that bar
