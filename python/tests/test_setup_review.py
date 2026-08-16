"""Ruled QMIE + MCP setup overlay. Does not touch scoring weights."""
from __future__ import annotations

from improve.setup_review import (
    McpSnapshot, QmieSetup, evaluate, mcp_side, snapshot_from_dict, yahoo_symbol,
)


def _qmie(**kwargs) -> QmieSetup:
    base = dict(
        symbol="BTCUSDT", timeframe="4h", side="BUY", grade="A",
        score=84.0, rsi=52.0, adx=28.0, htf_aligned=True, daily_trend="bullish",
        atr_pct=1.2,
    )
    base.update(kwargs)
    return QmieSetup(**base)


def test_yahoo_symbol():
    assert yahoo_symbol("BTCUSDT") == "BTC-USD"
    assert yahoo_symbol("1000PEPEUSDT") == "PEPE-USD"


def test_mcp_side_normalizes():
    assert mcp_side("STRONG BUY") == "BUY"
    assert mcp_side("sell") == "SELL"
    assert mcp_side("HOLD") == "HOLD"
    assert mcp_side(None) is None


def test_no_mcp_is_incomplete():
    v = evaluate(_qmie(), None)
    assert v.verdict == "INCOMPLETE"
    assert any(r.id == "mcp_present" for r in v.rules)


def test_aligned_mcp_confirms():
    mcp = McpSnapshot(recommendation="BUY", rsi=48.0, htf_bias="bullish")
    v = evaluate(_qmie(), mcp)
    assert v.verdict == "CONFIRM"
    assert not v.failed_required


def test_opposite_mcp_conflicts():
    mcp = McpSnapshot(recommendation="SELL", rsi=48.0, htf_bias="bearish")
    v = evaluate(_qmie(), mcp)
    assert v.verdict == "CONFLICT"


def test_b_grade_fails_even_if_mcp_agrees():
    mcp = McpSnapshot(recommendation="BUY", rsi=48.0, htf_bias="bullish")
    v = evaluate(_qmie(grade="B", score=70.0), mcp)
    assert v.verdict == "CONFLICT"
    assert any(r.id == "qmie_alert" and not r.passed for r in v.rules)


def test_overbought_rsi_blocks_buy():
    mcp = McpSnapshot(recommendation="BUY", rsi=81.0, htf_bias="bullish")
    v = evaluate(_qmie(), mcp)
    assert v.verdict == "CONFLICT"
    assert any(r.id == "mcp_rsi" and not r.passed for r in v.rules)


def test_missing_mcp_rsi_incomplete():
    mcp = McpSnapshot(recommendation="BUY", rsi=None, htf_bias="bullish")
    v = evaluate(_qmie(), mcp)
    assert v.verdict == "INCOMPLETE"


def test_disagreement_beats_missing_field():
    mcp = McpSnapshot(recommendation="SELL", rsi=48.0, htf_bias=None)
    v = evaluate(_qmie(), mcp)
    assert v.verdict == "CONFLICT"


def test_sentiment_never_gates():
    mcp = McpSnapshot(
        recommendation="BUY", rsi=48.0, htf_bias="bullish",
        sentiment="bearish",
    )
    v = evaluate(_qmie(), mcp)
    assert v.verdict == "CONFIRM"
    sent = next(r for r in v.rules if r.id == "mcp_sentiment")
    assert sent.required is False


def test_snapshot_from_dict():
    s = snapshot_from_dict({"recommendation": "BUY", "rsi": "51.2", "htf_bias": "bullish"})
    assert s.rsi == 51.2
    assert s.recommendation == "BUY"
