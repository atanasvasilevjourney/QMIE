"""
QMIE desk DAG — hedge-fund shape, signal-only
=============================================
Analog of 51bitquant/ai-hedge-fund-crypto:

    start → data → strategy → risk → portfolio

Differences (load-bearing):
- No LangGraph. No MACD/RSI/Bollinger extra strategies.
- Strategy node is QMIE TMA A/A+ only (frozen OOS).
- Portfolio never emits buy/sell/short/cover quantities.
  Actions are suggest_long | suggest_short | watch | skip.
  ``quantity`` is always 0.
- LLM is not on this path (briefing/desk poll). Use /agents/analysis/{id}.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from improve.agents import book_agent, checklist_agent, radar_agent, scanner_agent
from improve.checklist import flatten_signal

NODE_NAMES = ("start", "data", "strategy", "risk", "portfolio")

# Informational analog of their 20% cash position cap. QMIE uses a 100-point
# ranked book + cluster_max instead of shares.
POSITION_LIMIT_PCT = 20.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _node(name: str, payload: dict[str, Any], *, ok: bool = True) -> dict[str, Any]:
    out = dict(payload)
    out.setdefault("node", name)
    out.setdefault("ok", ok)
    out["places_orders"] = False
    return out


def start_node() -> dict[str, Any]:
    return _node("start", {
        "headline": "Desk DAG armed",
        "note": "start → data → strategy → risk → portfolio. Never orders.",
        "source": "51bitquant/ai-hedge-fund-crypto analog (signal-only)",
    })


def data_node(
    signals: list[dict[str, Any]],
    radar: Optional[dict[str, Any]],
) -> dict[str, Any]:
    rad = radar_agent(radar)
    tfs: dict[str, int] = {}
    for row in signals:
        flat = flatten_signal(row)
        tf = str(flat.get("timeframe") or "unknown").lower()
        tfs[tf] = tfs.get(tf, 0) + 1
    return _node("data", {
        "headline": f"{len(signals)} stored alerts · radar {rad.get('bias') or '—'}",
        "timeframes": tfs,
        "radar_bias": rad.get("bias"),
        "green": rad.get("green"),
        "grey": rad.get("grey"),
        "red": rad.get("red"),
        "note": "Closed-bar 1h/4h + 1D radar. No 5m/15m/30m data nodes.",
    })


def strategy_node(signals: list[dict[str, Any]]) -> dict[str, Any]:
    scan = scanner_agent(signals)
    return _node("strategy", {
        "headline": scan.get("headline"),
        "aa_count": scan.get("aa_count"),
        "grades": scan.get("grades"),
        "aa": scan.get("aa") or [],
        "note": "QMIE TMA 9/90/199 only. Not MACD/RSI/Bollinger ensemble.",
    })


def risk_node(
    signals: list[dict[str, Any]],
    radar: Optional[dict[str, Any]],
    allocation: Optional[dict[str, Any]],
) -> dict[str, Any]:
    book = book_agent(allocation)
    chk = checklist_agent(signals, radar, limit=12)
    slots = list(book.get("slots") or [])
    by_sym: dict[str, dict[str, Any]] = {}
    for s in slots:
        sym = str(s.get("symbol") or "").upper()
        if not sym:
            continue
        by_sym[sym] = {
            "weight_pct": s.get("weight_pct"),
            "cluster": s.get("cluster"),
            "rank": s.get("rank"),
            "side": s.get("side"),
            "position_limit_pct": POSITION_LIMIT_PCT,
            "note": "Ranked weight_pct + cluster_max. Not cash shares.",
        }
    return _node("risk", {
        "headline": f"{chk.get('headline')} · {book.get('headline')}",
        "mix": chk.get("mix"),
        "cards": chk.get("cards") or [],
        "slots": slots,
        "limits": by_sym,
        "cluster_max": 1,
        "position_limit_pct": POSITION_LIMIT_PCT,
        "note": "20% analog is one cluster slot + suggested weight, not an order.",
    })


def _decision_for(
    card: dict[str, Any],
    limits: dict[str, dict[str, Any]],
    *,
    score: Any = None,
) -> dict[str, Any]:
    symbol = str(card.get("symbol") or "").upper()
    side = str(card.get("side") or "").upper()
    verdict = str(card.get("verdict") or "")
    tf = str(card.get("timeframe") or "").lower()
    if score is None:
        score = card.get("score")
    try:
        conf = float(score) if score is not None else 0.0
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(100.0, conf))
    slot = limits.get(symbol) or {}
    weight = slot.get("weight_pct")
    if verdict == "SKIP":
        action = "skip"
        reason = card.get("action") or "Checklist SKIP."
        conf = 0.0
        weight = 0.0
    elif verdict == "WATCH" or not slot:
        action = "watch"
        reason = card.get("action") or "Watch — not a ranked slot or optional gate failed."
        if tf in ("1h", "60"):
            reason += " Prefer 4h (frozen OOS)."
    elif side == "SELL":
        action = "suggest_short"
        reason = (
            f"QMIE {side} {card.get('grade')} in ranked book "
            f"(weight {weight}%, cluster {slot.get('cluster')}). "
            "Confirm on quant_visualizer.pine. Not an order."
        )
    else:
        action = "suggest_long"
        reason = (
            f"QMIE {side} {card.get('grade')} in ranked book "
            f"(weight {weight}%, cluster {slot.get('cluster')}). "
            "Confirm on quant_visualizer.pine. Not an order."
        )
    return {
        "action": action,
        "quantity": 0,
        "suggested_weight_pct": weight or 0.0,
        "confidence": conf,
        "reasoning": reason,
        "symbol": symbol,
        "side": side,
        "grade": card.get("grade"),
        "timeframe": card.get("timeframe"),
        "signal_id": card.get("signal_id"),
        "checklist_verdict": verdict,
        "places_orders": False,
    }


def portfolio_node(
    risk: dict[str, Any],
    strategy: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    limits = risk.get("limits") or {}
    cards = risk.get("cards") or []
    aa_by_id = {
        row.get("id"): row
        for row in (strategy or {}).get("aa") or []
        if row.get("id") is not None
    }
    aa_by_sym = {
        str(row.get("symbol") or "").upper(): row
        for row in (strategy or {}).get("aa") or []
    }
    decisions: dict[str, Any] = {}
    for card in cards:
        sym = str(card.get("symbol") or "").upper()
        if not sym:
            continue
        meta = aa_by_id.get(card.get("signal_id")) or aa_by_sym.get(sym) or {}
        decisions[sym] = _decision_for(card, limits, score=meta.get("score"))
    mix = {"suggest_long": 0, "suggest_short": 0, "watch": 0, "skip": 0}
    for d in decisions.values():
        a = d.get("action") or "watch"
        mix[a] = mix.get(a, 0) + 1
    return _node("portfolio", {
        "headline": (
            f"{mix.get('suggest_long', 0)} long · {mix.get('suggest_short', 0)} short · "
            f"{mix.get('watch', 0)} watch · {mix.get('skip', 0)} skip"
        ),
        "decisions": decisions,
        "mix": mix,
        "note": "quantity is always 0. suggest_* is not buy/sell. Not an order.",
    })


def run_desk(
    *,
    signals: list[dict[str, Any]],
    radar: Optional[dict[str, Any]],
    allocation: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Sequential DAG. A failing node is recorded; later nodes still run."""
    t0 = time.perf_counter()
    nodes: dict[str, Any] = {}

    try:
        nodes["start"] = start_node()
    except Exception as e:
        nodes["start"] = _node("start", {"error": str(e)}, ok=False)

    try:
        nodes["data"] = data_node(signals, radar)
    except Exception as e:
        nodes["data"] = _node("data", {"error": str(e)}, ok=False)

    try:
        nodes["strategy"] = strategy_node(signals)
    except Exception as e:
        nodes["strategy"] = _node("strategy", {"error": str(e)}, ok=False)

    try:
        nodes["risk"] = risk_node(signals, radar, allocation)
    except Exception as e:
        nodes["risk"] = _node("risk", {"error": str(e), "cards": [], "limits": {}}, ok=False)

    try:
        nodes["portfolio"] = portfolio_node(
            nodes.get("risk") or {},
            nodes.get("strategy") or {},
        )
    except Exception as e:
        nodes["portfolio"] = _node("portfolio", {"error": str(e), "decisions": {}}, ok=False)

    port = nodes.get("portfolio") or {}
    return {
        "as_of": _now(),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 1),
        "places_orders": False,
        "graph": {
            "nodes": list(NODE_NAMES),
            "edges": [
                ["start", "data"],
                ["data", "strategy"],
                ["strategy", "risk"],
                ["risk", "portfolio"],
            ],
            "mermaid": (
                "flowchart LR\n"
                "  start --> data\n"
                "  data --> strategy\n"
                "  strategy --> risk\n"
                "  risk --> portfolio"
            ),
        },
        "summary": {
            "strategy_headline": (nodes.get("strategy") or {}).get("headline"),
            "risk_headline": (nodes.get("risk") or {}).get("headline"),
            "portfolio_headline": port.get("headline"),
        },
        "nodes": nodes,
        "decisions": port.get("decisions") or {},
        "note": (
            "Analog of ai-hedge-fund-crypto without LangGraph, without MACD "
            "ensemble, without orders. Confirm on quant_visualizer.pine."
        ),
    }
