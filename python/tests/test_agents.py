"""Native Smart Checklist + isolated multi-agent briefing."""
from __future__ import annotations

import json

import pytest

from improve.agents import book_agent, checklist_agent, radar_agent, run_briefing, scanner_agent
from improve.checklist import atr_pct_of, evaluate_native, flatten_signal, radar_color_for


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


def test_flatten_prefers_column_over_raw():
    row = _row(grade="A+")
    flat = flatten_signal(row)
    assert flat["grade"] == "A+"
    assert flat["timeframe"] == "4h"
    assert "raw" not in flat


def test_atr_pct_from_atr_and_price():
    assert atr_pct_of({"atr": 2.0, "signal_price": 200.0}) == pytest.approx(1.0)


def test_go_when_all_native_gates_pass():
    radar = {"rows": [{"symbol": "BTCUSDT", "color": "GREEN"}]}
    v = evaluate_native(_row(), radar=radar)
    assert v.verdict == "GO"
    assert v.as_dict()["places_orders"] is False


def test_skip_when_radar_red_against_buy():
    radar = {"rows": [{"symbol": "BTCUSDT", "color": "RED"}]}
    v = evaluate_native(_row(), radar=radar)
    assert v.verdict == "SKIP"
    assert any(i.id == "radar_color" and i.required and not i.passed for i in v.items)


def test_watch_when_1h_and_adx_low():
    v = evaluate_native(_row(timeframe="1h", adx=12.0, atr_pct=1.2))
    assert v.verdict == "WATCH"
    ids = {i.id for i in v.items if not i.passed}
    assert "timeframe_edge" in ids
    assert "adx_gate" in ids


def test_skip_b_grade():
    v = evaluate_native(_row(grade="B", score=70.0))
    assert v.verdict == "SKIP"


def test_daily_trend_against_is_skip():
    v = evaluate_native(_row(daily_trend="bearish", side="BUY"))
    assert v.verdict == "SKIP"


def test_radar_color_lookup():
    radar = {"rows": [{"symbol": "ethusdt", "color": "RED"}]}
    assert radar_color_for("ETHUSDT", radar) == "RED"
    assert radar_color_for("BTCUSDT", radar) is None


def test_scanner_agent_counts_aa():
    out = scanner_agent([_row(), _row(id=2, grade="C", score=55)])
    assert out["ok"] is True
    assert out["aa_count"] == 1
    assert out["grades"]["A"] == 1
    assert out["grades"]["C"] == 1


def test_radar_agent_bias_long():
    out = radar_agent({"green": 20, "grey": 5, "red": 4, "rows": [
        {"symbol": "BTCUSDT", "color": "GREEN"},
    ], "fresh_green": [1, 2], "breakouts": [], "tight_coils": []})
    assert out["bias"] == "LONG"
    assert out["btc_color"] == "GREEN"
    assert out["breadth_pct"]["green"] > 50


def test_book_agent_clusters():
    out = book_agent({"mode": "ranked", "slots": [
        {"symbol": "BTCUSDT", "cluster": "BTC"},
        {"symbol": "ETHUSDT", "cluster": "ETH"},
    ]})
    assert out["clusters"]["BTC"] == 1
    assert "not an order" in out["note"]


def test_checklist_agent_limits_and_mix():
    rows = [_row(id=i, symbol=f"S{i}USDT") for i in range(10)]
    out = checklist_agent(rows, {"rows": []}, limit=3)
    assert out["count"] == 3
    assert "WATCH" in out["mix"] or "GO" in out["mix"] or "SKIP" in out["mix"]


@pytest.mark.asyncio
async def test_briefing_isolates_agent_failure(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("radar down")

    monkeypatch.setattr("improve.agents.radar_agent", boom)
    out = await run_briefing(signals=[_row()], radar={"green": 1}, allocation=None)
    assert out["places_orders"] is False
    assert out["agents"]["radar"]["ok"] is False
    assert out["agents"]["scanner"]["ok"] is True
    assert out["agents"]["checklist"]["ok"] is True
    assert "elapsed_ms" in out
