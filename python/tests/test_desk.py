"""Signal-only hedge-fund DAG (start→data→strategy→risk→portfolio)."""
from __future__ import annotations

import json

from improve.desk import run_desk


def _row(**kw) -> dict:
    raw = {
        "timeframe": kw.pop("timeframe", "4h"),
        "htf": kw.pop("htf", "aligned"),
        "adx": kw.pop("adx", 28.0),
        "atr": kw.pop("atr", 500.0),
        "atr_pct": kw.pop("atr_pct", 1.2),
        "rsi": kw.pop("rsi", 52.0),
        "strategy": kw.pop("strategy", "QMIE-Scanner"),
    }
    row = {
        "id": 1,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "grade": "A",
        "score": 84.0,
        "signal_price": 50000.0,
        "daily_trend": "bullish",
        "funding_rate": 0.0001,
        "raw": json.dumps(raw),
    }
    row.update(kw)
    return row


def test_go_ranked_slot_is_suggest_long_quantity_zero():
    radar = {"rows": [{"symbol": "BTCUSDT", "color": "GREEN"}], "green": 1, "grey": 0, "red": 0}
    alloc = {"mode": "ranked", "slots": [
        {"symbol": "BTCUSDT", "side": "BUY", "cluster": "BTC", "rank": 1, "weight_pct": 50.0},
    ]}
    out = run_desk(signals=[_row()], radar=radar, allocation=alloc)
    assert out["places_orders"] is False
    assert out["graph"]["nodes"] == ["start", "data", "strategy", "risk", "portfolio"]
    d = out["decisions"]["BTCUSDT"]
    assert d["action"] == "suggest_long"
    assert d["quantity"] == 0
    assert d["suggested_weight_pct"] == 50.0
    assert d["places_orders"] is False
    assert d["confidence"] == 84.0


def test_skip_radar_red_is_skip_not_buy():
    radar = {"rows": [{"symbol": "BTCUSDT", "color": "RED"}], "green": 0, "grey": 0, "red": 1}
    out = run_desk(signals=[_row()], radar=radar, allocation={"slots": [
        {"symbol": "BTCUSDT", "side": "BUY", "cluster": "BTC", "rank": 1, "weight_pct": 50.0},
    ]})
    d = out["decisions"]["BTCUSDT"]
    assert d["action"] == "skip"
    assert d["quantity"] == 0


def test_sell_go_is_suggest_short():
    radar = {"rows": [{"symbol": "ETHUSDT", "color": "RED"}], "green": 0, "grey": 0, "red": 1}
    row = _row(id=2, symbol="ETHUSDT", side="SELL", daily_trend="bearish")
    out = run_desk(signals=[row], radar=radar, allocation={"slots": [
        {"symbol": "ETHUSDT", "side": "SELL", "cluster": "ETH", "rank": 1, "weight_pct": 40.0},
    ]})
    d = out["decisions"]["ETHUSDT"]
    assert d["action"] == "suggest_short"
    assert d["quantity"] == 0
    assert "buy" not in d["action"]


def test_go_without_slot_is_watch():
    radar = {"rows": [{"symbol": "BTCUSDT", "color": "GREEN"}], "green": 1, "grey": 0, "red": 0}
    out = run_desk(signals=[_row()], radar=radar, allocation={"slots": []})
    assert out["decisions"]["BTCUSDT"]["action"] == "watch"
    assert out["decisions"]["BTCUSDT"]["quantity"] == 0


def test_risk_failure_does_not_raise(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("risk down")

    monkeypatch.setattr("improve.desk.risk_node", boom)
    out = run_desk(signals=[_row()], radar=None, allocation=None)
    assert out["places_orders"] is False
    assert out["nodes"]["risk"]["ok"] is False
    assert out["nodes"]["portfolio"]["ok"] is True
    assert "decisions" in out


ALLOWED_ACTIONS = {"suggest_long", "suggest_short", "watch", "skip"}
FORBIDDEN_ACTIONS = {"buy", "sell", "short", "cover"}


def test_actions_never_orders_and_quantity_always_zero():
    radar = {"rows": [{"symbol": "BTCUSDT", "color": "GREEN"}], "green": 1, "grey": 0, "red": 0}
    out = run_desk(signals=[_row()], radar=radar, allocation={"slots": [
        {"symbol": "BTCUSDT", "side": "BUY", "cluster": "BTC", "rank": 1, "weight_pct": 50.0},
    ]})
    assert out["graph"]["mermaid"].count("-->") == 4
    for d in out["decisions"].values():
        assert d["quantity"] == 0
        assert d["action"] in ALLOWED_ACTIONS
        assert d["action"] not in FORBIDDEN_ACTIONS
        assert d["places_orders"] is False


def test_watch_1h_mentions_prefer_4h():
    radar = {"rows": [{"symbol": "BTCUSDT", "color": "GREEN"}], "green": 1, "grey": 0, "red": 0}
    out = run_desk(signals=[_row(timeframe="1h")], radar=radar, allocation={"slots": []})
    d = out["decisions"]["BTCUSDT"]
    assert d["action"] == "watch"
    assert d["quantity"] == 0
    assert "4h" in d["reasoning"].lower()


def test_strategy_failure_isolated(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("strategy down")

    monkeypatch.setattr("improve.desk.strategy_node", boom)
    out = run_desk(signals=[_row()], radar=None, allocation=None)
    assert out["nodes"]["strategy"]["ok"] is False
    assert out["nodes"]["portfolio"]["ok"] is True
    assert out["places_orders"] is False
