"""OpenAI analysis overlay — levels from scanner math, LLM never owns prices."""
from __future__ import annotations

import json

import pytest

from improve.analysis import (
    analyze_signal,
    openai_configured,
    scanner_levels,
    template_take,
)
from improve.checklist import flatten_signal


def _row(**kw) -> dict:
    raw = {
        "timeframe": kw.pop("timeframe", "4h"),
        "htf": kw.pop("htf", "aligned"),
        "adx": kw.pop("adx", 28.0),
        "atr": kw.pop("atr", 500.0),
        "atr_pct": kw.pop("atr_pct", 1.2),
        "rsi": kw.pop("rsi", 52.0),
        "strategy": kw.pop("strategy", "QMIE-Scanner"),
        "stop_loss": kw.pop("raw_sl", None),
        "take_profit": kw.pop("raw_tp", None),
    }
    raw = {k: v for k, v in raw.items() if v is not None}
    row = {
        "id": 7,
        "symbol": "ETHUSDT",
        "side": "BUY",
        "grade": "A",
        "score": 84.0,
        "signal_price": 50000.0,
        "stop_loss": 49000.0,
        "take_profit": 52500.0,
        "daily_trend": "bullish",
        "funding_rate": 0.0001,
        "raw": json.dumps(raw),
    }
    row.update(kw)
    return row


class _FakeResp:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    def __init__(self, responses):
        self._queue = list(responses)
        self.calls = []
        self.closed = False

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if not self._queue:
            raise RuntimeError("no more fake responses queued")
        return self._queue.pop(0)

    async def close(self):
        self.closed = True


def _openai_payload(content: dict | str, extra_levels=None) -> dict:
    if isinstance(content, dict):
        if extra_levels is not None:
            content = dict(content)
            content["levels"] = extra_levels
        blob = json.dumps(content)
    else:
        blob = content
    return {"choices": [{"message": {"content": blob}}]}


def test_buy_levels_1r_then_tp():
    lv = scanner_levels(flatten_signal(_row()))
    by_type = {x.type: x.price for x in lv}
    assert by_type["Invalidation"] == 49000.0
    assert by_type["Current"] == 50000.0
    assert by_type["Target 1"] == 51000.0
    assert by_type["Target 2"] == 52500.0


def test_sell_levels_1r_then_tp():
    lv = scanner_levels(flatten_signal(_row(
        side="SELL", daily_trend="bearish",
        signal_price=50000.0, stop_loss=51000.0, take_profit=47500.0,
    )))
    by_type = {x.type: x.price for x in lv}
    assert by_type["Invalidation"] == 51000.0
    assert by_type["Target 1"] == 49000.0
    assert by_type["Target 2"] == 47500.0


def test_t1_clamped_when_tp_tighter_than_1r_buy():
    lv = scanner_levels(flatten_signal(_row(
        signal_price=50000.0, stop_loss=49000.0, take_profit=50500.0,
    )))
    by_type = {x.type: x.price for x in lv}
    assert by_type["Target 1"] == 50250.0
    assert by_type["Target 2"] == 50500.0


def test_t1_clamped_when_tp_tighter_than_1r_sell():
    lv = scanner_levels(flatten_signal(_row(
        side="SELL", daily_trend="bearish",
        signal_price=50000.0, stop_loss=51000.0, take_profit=49500.0,
    )))
    by_type = {x.type: x.price for x in lv}
    assert by_type["Target 1"] == 49750.0


def test_template_missing_sl_does_not_print_none():
    row = _row(stop_loss=None, take_profit=None)
    flat = flatten_signal(row)
    levels = scanner_levels(flat)
    status, zone, take, _counter = template_take(flat, "WATCH", levels)
    assert status == "BULLISH"
    assert zone == "incomplete levels"
    assert "None" not in take
    assert "stop_loss" in take


def test_template_skip_is_mixed():
    row = _row(grade="B", score=70.0)
    flat = flatten_signal(row)
    levels = scanner_levels(flat)
    status, zone, take, counter = template_take(flat, "SKIP", levels)
    assert status == "MIXED"
    assert "skip" in take.lower()
    assert "checklist skip" in zone


def test_openai_configured_false_on_blank():
    assert openai_configured("") is False
    assert openai_configured("   ") is False
    assert openai_configured("sk-test") is True


@pytest.mark.asyncio
async def test_no_key_uses_template_and_does_not_post():
    sess = _FakeSession([_FakeResp(200, _openai_payload({
        "status": "BULLISH", "zone": "x", "take": "chase it", "counter": "none",
    }))])
    out = await analyze_signal(_row(), api_key=None, session=sess)
    assert out["source"] == "template"
    assert out["places_orders"] is False
    assert out["status"] == "BULLISH"
    assert sess.calls == []
    prices = {lv["type"]: lv["price"] for lv in out["levels"]}
    assert prices["Target 1"] == 51000.0


@pytest.mark.asyncio
async def test_skip_does_not_call_openai_even_with_key():
    sess = _FakeSession([_FakeResp(200, _openai_payload({
        "status": "BULLISH", "zone": "x", "take": "go now", "counter": "none",
    }))])
    out = await analyze_signal(
        _row(grade="B", score=70.0),
        api_key="sk-test",
        session=sess,
    )
    assert sess.calls == []
    assert out["status"] == "MIXED"
    assert out["source"] == "template"
    assert "skip" in out["take"].lower()


@pytest.mark.asyncio
async def test_openai_success_stamps_scanner_levels_not_llm_prices():
    sess = _FakeSession([_FakeResp(200, _openai_payload(
        {
            "status": "BULLISH",
            "zone": "above the trap door",
            "take": "Wait for a dip toward invalidation. Tight stop past SL. Manual only.",
            "counter": "RSI stretched",
        },
        extra_levels=[{"type": "Invalidation", "price": 1.0, "note": "invented"}],
    ))])
    out = await analyze_signal(_row(), api_key="sk-test", session=sess)
    assert out["source"] == "openai"
    assert out["model"] == "gpt-4.1-mini"
    assert "Wait for a dip" in out["take"]
    assert out["counter"] == "RSI stretched"
    prices = {lv["type"]: lv["price"] for lv in out["levels"]}
    assert prices["Invalidation"] == 49000.0
    assert prices["Target 2"] == 52500.0
    assert 1.0 not in prices.values()
    assert sess.calls and "Authorization" in sess.calls[0]["headers"]
    assert sess.calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert out["places_orders"] is False


@pytest.mark.asyncio
async def test_openai_http_error_falls_back_to_template():
    sess = _FakeSession([_FakeResp(401, {"error": {"message": "bad key"}})])
    out = await analyze_signal(_row(), api_key="sk-bad", session=sess)
    assert out["source"].startswith("template_fallback:")
    assert out["status"] == "BULLISH"
    assert "Manual only" in out["take"]
    prices = {lv["type"]: lv["price"] for lv in out["levels"]}
    assert prices["Current"] == 50000.0
