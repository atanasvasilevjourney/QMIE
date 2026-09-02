"""Combo screens: unique(symbol) OR of existing views. Never orders."""
from __future__ import annotations

import json

import pytest

from screens import VIEWS, build_screens


def _sig(**kw) -> dict:
    raw = {
        "timeframe": kw.pop("timeframe", "4h"),
        "atr_pct": kw.pop("atr_pct", 1.2),
        "adx": kw.pop("adx", 28.0),
        "strategy": kw.pop("strategy", "QMIE-Scanner"),
    }
    row = {
        "id": kw.pop("id", 1),
        "symbol": kw.pop("symbol", "BTCUSDT"),
        "side": kw.pop("side", "BUY"),
        "grade": kw.pop("grade", "A"),
        "score": kw.pop("score", 84.0),
        "signal_price": kw.pop("signal_price", 50000.0),
        "raw": json.dumps(raw),
    }
    row.update(kw)
    return row


def test_places_orders_false_and_quantity_zero():
    out = build_screens(signals=[_sig()], radar=None, allocation=None)
    assert out["places_orders"] is False
    assert out["quantity"] == 0
    assert out["rows"][0]["quantity"] == 0
    assert out["rows"][0]["places_orders"] is False
    assert out["view"] == "all"
    assert out["views"] == list(VIEWS)


def test_unique_symbol_prefers_4h_over_1h():
    rows = [
        _sig(id=1, timeframe="1h", score=80.0, symbol="ETHUSDT"),
        _sig(id=2, timeframe="4h", score=90.0, symbol="ETHUSDT"),
    ]
    out = build_screens(signals=rows)
    assert out["count"] == 1
    row = out["rows"][0]
    assert row["symbol"] == "ETHUSDT"
    assert row["timeframe"] == "4h"
    assert row["score"] == 90.0
    assert row["signal_id"] == 2
    assert row["cluster"] == "ETH"


def test_leaders_view_is_4h_only():
    rows = [
        _sig(id=1, timeframe="1h", symbol="SOLUSDT", score=88.0),
        _sig(id=2, timeframe="4h", symbol="BTCUSDT", score=91.0),
    ]
    all_v = build_screens(signals=rows, view="all")
    assert {r["symbol"] for r in all_v["rows"]} == {"SOLUSDT", "BTCUSDT"}
    lead = build_screens(signals=rows, view="leaders")
    assert [r["symbol"] for r in lead["rows"]] == ["BTCUSDT"]
    assert all(r["timeframe"] == "4h" for r in lead["rows"])


def test_combo_or_dedupes_breakout_and_tema():
    rows = [
        _sig(id=1, symbol="BTCUSDT", timeframe="4h"),
        _sig(
            id=2,
            symbol="BTCUSDT",
            strategy="QMIE-DailyBreakout",
            grade="",
            side="BUY",
            timeframe="1d",
            reason="trend_start_long",
        ),
    ]
    out = build_screens(signals=rows, view="all")
    assert out["count"] == 1
    assert set(out["rows"][0]["sources"]) == {"breakouts", "leaders"}


def test_radar_down_breakout_is_short():
    radar = {
        "rows": [{"symbol": "SOLUSDT", "color": "RED", "adx": 32.0, "breakout": "DOWN"}],
        "tight_coils": [],
        "breakouts": [
            {"symbol": "SOLUSDT", "price": 145.0, "adx": 32.0, "breakout": "DOWN"}
        ],
    }
    out = build_screens(signals=[], radar=radar, view="breakouts")
    assert out["count"] == 1
    row = out["rows"][0]
    assert row["symbol"] == "SOLUSDT"
    assert row["side"] == "SELL"
    assert row["breakout"] == "DOWN"
    assert "breakouts" in row["sources"]
    assert row["quantity"] == 0


def test_coil_only_symbol_included():
    radar = {
        "rows": [{"symbol": "ADAUSDT", "color": "GREY", "adx": 18.0, "is_tight_coil": True, "coil_width_pct": 2.4}],
        "tight_coils": [
            {
                "symbol": "ADAUSDT",
                "price": 0.4,
                "adx": 18.0,
                "coil_width_pct": 2.4,
                "is_tight_coil": True,
                "is_early_long": True,
            }
        ],
        "breakouts": [],
    }
    out = build_screens(signals=[], radar=radar, view="coils")
    assert out["count"] == 1
    row = out["rows"][0]
    assert row["symbol"] == "ADAUSDT"
    assert row["is_tight_coil"] is True
    assert row["is_early_long"] is True
    assert row["coil_width_pct"] == 2.4
    assert "coils" in row["sources"]
    assert row["grade"] is None


def test_book_view_and_modal_cluster():
    alloc = {
        "timeframe": "4h",
        "slots": [
            {"symbol": "ETHUSDT", "side": "BUY", "cluster": "ETH", "rank": 1, "weight_pct": 50.0, "grade": "A", "score": 80},
            {"symbol": "ARBUSDT", "side": "BUY", "cluster": "ETH", "rank": 2, "weight_pct": 30.0, "grade": "A", "score": 78},
        ],
    }
    out = build_screens(signals=[], allocation=alloc, view="book")
    assert out["count"] == 2
    assert out["modal_cluster"] == "ETH"
    assert out["rows"][0]["weight_pct"] == 50.0
    assert all(r["quantity"] == 0 for r in out["rows"])


def test_rejects_and_exits_skipped():
    rows = [
        _sig(grade="C", symbol="DOGEUSDT"),
        _sig(strategy="QMIE-Paper", event="exit", symbol="XRPUSDT", grade="A"),
    ]
    out = build_screens(signals=rows)
    assert out["count"] == 0


def test_book_weight_survives_leaders_merge():
    signals = [_sig(symbol="ETHUSDT", timeframe="4h", score=90.0)]
    alloc = {
        "slots": [
            {"symbol": "ETHUSDT", "weight_pct": 33.3, "rank": 1, "cluster": "ETH", "score": 70.0}
        ]
    }
    out = build_screens(signals=signals, allocation=alloc)
    row = out["rows"][0]
    assert row["score"] == 90.0
    assert row["timeframe"] == "4h"
    assert row["weight_pct"] == 33.3
    assert set(row["sources"]) == {"book", "leaders"}


def test_unknown_view_raises():
    with pytest.raises(ValueError, match="view"):
        build_screens(signals=[], view="canslim")
