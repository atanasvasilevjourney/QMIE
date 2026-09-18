"""
QMIE multi-agent briefing
=========================
Six specialist agents run concurrently (asyncio.gather, return_exceptions).
A failing radar agent must not break checklist, and vice versa.

Agents:
  scanner   — A/A+ mix, 1h vs 4h split
  radar     — GREEN/GREY/RED breadth + BTC color
  book      — ranked slots / clusters (suggested size, not orders)
  checklist — native Smart Checklist on latest A/A+ (and breakouts)
  review    — last strategy/reviews note; does not write a new one
  analysis  — OpenAI overlay armed/not (never calls OpenAI on the poll)

Never places orders. Never writes .env. Never retunes W_*.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from improve.analysis import openai_configured
from scanner.radar import breadth_bias
from improve.checklist import evaluate_native, flatten_signal
from improve.review import (
    DEFAULT_BASELINE,
    DEFAULT_GOALS,
    DEFAULT_REVIEWS,
    _towards_goal,
    journal_snapshot,
    load_simple_yaml,
)

AGENT_NAMES = ("scanner", "radar", "book", "checklist", "review", "analysis")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _agent_ok(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.setdefault("agent", name)
    out.setdefault("ok", True)
    out.setdefault("places_orders", False)
    return out


def _agent_err(name: str, err: BaseException | str) -> dict[str, Any]:
    return {
        "agent": name,
        "ok": False,
        "error": str(err),
        "places_orders": False,
    }


def scanner_agent(signals: list[dict[str, Any]]) -> dict[str, Any]:
    flats = [flatten_signal(s) for s in signals]
    grades: dict[str, int] = {"A+": 0, "A": 0, "B": 0, "C": 0, "other": 0}
    tf_counts: dict[str, int] = {}
    aa: list[dict[str, Any]] = []
    for f in flats:
        g = str(f.get("grade") or "")
        if g in grades:
            grades[g] += 1
        else:
            grades["other"] += 1
        tf = str(f.get("timeframe") or "unknown").lower()
        tf_counts[tf] = tf_counts.get(tf, 0) + 1
        if g in ("A", "A+") and str(f.get("side") or "").upper() in ("BUY", "SELL"):
            aa.append({
                "id": f.get("id"),
                "symbol": f.get("symbol"),
                "side": f.get("side"),
                "grade": g,
                "score": f.get("score"),
                "timeframe": f.get("timeframe"),
            })
    return _agent_ok("scanner", {
        "headline": f"{len(aa)} A/A+ of {len(flats)} recent alerts",
        "count": len(flats),
        "aa_count": len(aa),
        "grades": grades,
        "timeframes": tf_counts,
        "aa": aa[:12],
        "note": "1h dilutes frozen OOS; prefer 4h A/A+ when both fire.",
    })


def radar_agent(radar: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not radar:
        return _agent_ok("radar", {
            "headline": "No radar snapshot yet",
            "status": "empty",
            "green": 0, "grey": 0, "red": 0,
            "breadth_pct": {"green": 0.0, "grey": 0.0, "red": 0.0},
            "bias": "UNKNOWN",
            "btc_color": None,
            "buys_allowed": None,
            "fresh_green": 0, "fresh_red": 0,
            "breakouts": 0, "tight_coils": 0,
        })
    g = int(radar.get("green") or 0)
    y = int(radar.get("grey") or 0)
    r = int(radar.get("red") or 0)
    total = g + y + r
    def pct(n: int) -> float:
        return round(100.0 * n / total, 1) if total else 0.0
    bias = breadth_bias(g, r, grey=y)
    btc = None
    for row in radar.get("rows") or []:
        if str(row.get("symbol") or "").upper() == "BTCUSDT":
            btc = row.get("color")
            break
    btc_u = str(btc).upper() if btc is not None else None
    return _agent_ok("radar", {
        "headline": f"breadth {bias} · G{g} Y{y} R{r}",
        "status": radar.get("status") or radar.get("note"),
        "as_of": radar.get("as_of"),
        "green": g, "grey": y, "red": r,
        "breadth_pct": {"green": pct(g), "grey": pct(y), "red": pct(r)},
        "bias": bias,
        "btc_color": btc,
        "buys_allowed": None if btc_u is None else (btc_u != "RED"),
        "fresh_green": len(radar.get("fresh_green") or []),
        "fresh_red": len(radar.get("fresh_red") or []),
        "breakouts": len(radar.get("breakouts") or []),
        "tight_coils": len(radar.get("tight_coils") or []),
        "enabled": radar.get("enabled", True),
    })


def book_agent(plan: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not plan:
        return _agent_ok("book", {
            "headline": "No allocation plan yet",
            "mode": None,
            "slots": [],
            "clusters": {},
        })
    slots = list(plan.get("slots") or [])
    clusters: dict[str, int] = {}
    for s in slots:
        c = str(s.get("cluster") or "OTHER")
        clusters[c] = clusters.get(c, 0) + 1
    return _agent_ok("book", {
        "headline": f"{len(slots)} slots · mode {plan.get('mode') or '—'}",
        "mode": plan.get("mode"),
        "timeframe": plan.get("timeframe"),
        "regime": plan.get("regime"),
        "considered": plan.get("considered"),
        "slots": slots,
        "clusters": clusters,
        "note": "weight_pct is a 100-point risk budget, not an order.",
    })


def checklist_agent(
    signals: list[dict[str, Any]],
    radar: Optional[dict[str, Any]],
    *,
    limit: int = 8,
) -> dict[str, Any]:
    cards = []
    for row in signals:
        flat = flatten_signal(row)
        g = str(flat.get("grade") or "")
        strat = str(flat.get("strategy") or "")
        is_aa = g in ("A", "A+")
        is_bo = "DailyBreakout" in strat or "DailyExpansion" in strat
        if not (is_aa or is_bo):
            continue
        card = evaluate_native(row, radar=radar)
        cards.append(card.as_dict())
        if len(cards) >= limit:
            break
    mix = {"GO": 0, "WATCH": 0, "SKIP": 0}
    for c in cards:
        mix[c["verdict"]] = mix.get(c["verdict"], 0) + 1
    return _agent_ok("checklist", {
        "headline": (
            f"{mix.get('GO', 0)} GO · {mix.get('WATCH', 0)} WATCH · "
            f"{mix.get('SKIP', 0)} SKIP"
        ),
        "count": len(cards),
        "mix": mix,
        "cards": cards,
        "note": (
            "Native overlay (no MCP). No too_late / BTC-RED / cooldown skips "
            "(they cut winners on the 4h slice). MCP /qmie-setup remains optional."
        ),
    })


def review_agent(
    *,
    reviews_dir: Path = DEFAULT_REVIEWS,
    goals_path: Path = DEFAULT_GOALS,
    baseline_path: Path = DEFAULT_BASELINE,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Read-only. Does not write strategy/reviews/*.md."""
    latest: Optional[Path] = None
    proposed_knob = None
    applied = None
    if reviews_dir.exists():
        files = sorted(
            p for p in reviews_dir.glob("*.md") if p.name != ".gitkeep"
        )
        if files:
            latest = files[-1]
            for line in latest.read_text(encoding="utf-8").splitlines():
                if line.startswith("proposed_knob:"):
                    proposed_knob = line.split(":", 1)[1].strip()
                if line.startswith("applied:"):
                    applied = line.split(":", 1)[1].strip()
    stats = journal_snapshot(db_path)
    goals = load_simple_yaml(goals_path) if goals_path.exists() else {}
    baseline = load_simple_yaml(baseline_path) if baseline_path.exists() else {}
    verdict = _towards_goal(stats, goals) if goals else "unknown"
    return _agent_ok("review", {
        "headline": (
            f"knob {proposed_knob or 'none'} · applied {applied or 'n/a'} · "
            f"journal {verdict}"
        ),
        "latest_review": str(latest) if latest else None,
        "proposed_knob": proposed_knob,
        "applied": applied,
        "journal": stats,
        "goal_verdict": verdict,
        "scan_timeframes": baseline.get("scan_timeframes"),
        "sig_min_adx": baseline.get("sig_min_adx"),
        "note": "Does not write .env. Human applies one knob.",
    })


def analysis_agent() -> dict[str, Any]:
    """Status only — never call OpenAI on the 12s desk poll."""
    armed = openai_configured()
    return _agent_ok("analysis", {
        "headline": (
            "OpenAI overlay armed"
            if armed
            else "Template overlay (no OPENAI_API_KEY)"
        ),
        "openai_configured": armed,
        "note": (
            "GET /agents/analysis/{id} writes status + Invalidation / Current / "
            "T1 / T2 + Take. Prices are scanner ATR SL/TP. LLM never owns levels. "
            "Not a grade. Not an order."
        ),
    })


async def run_briefing(
    *,
    signals: list[dict[str, Any]],
    radar: Optional[dict[str, Any]],
    allocation: Optional[dict[str, Any]],
    db_path: Optional[Path] = None,
    reviews_dir: Path = DEFAULT_REVIEWS,
    goals_path: Path = DEFAULT_GOALS,
    baseline_path: Path = DEFAULT_BASELINE,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    raw = await asyncio.gather(
        asyncio.to_thread(scanner_agent, signals),
        asyncio.to_thread(radar_agent, radar),
        asyncio.to_thread(book_agent, allocation),
        asyncio.to_thread(checklist_agent, signals, radar),
        asyncio.to_thread(
            review_agent,
            reviews_dir=reviews_dir,
            goals_path=goals_path,
            baseline_path=baseline_path,
            db_path=db_path,
        ),
        asyncio.to_thread(analysis_agent),
        return_exceptions=True,
    )
    agents: dict[str, Any] = {}
    for name, item in zip(AGENT_NAMES, raw):
        if isinstance(item, BaseException):
            agents[name] = _agent_err(name, item)
        else:
            agents[name] = item
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    chk = agents.get("checklist") or {}
    rad = agents.get("radar") or {}
    return {
        "as_of": _now(),
        "elapsed_ms": elapsed_ms,
        "places_orders": False,
        "summary": {
            "radar_bias": rad.get("bias"),
            "checklist_headline": chk.get("headline"),
            "scanner_headline": (agents.get("scanner") or {}).get("headline"),
            "review_headline": (agents.get("review") or {}).get("headline"),
            "analysis_headline": (agents.get("analysis") or {}).get("headline"),
        },
        "agents": agents,
    }


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import json
    from improve.review import _default_db

    p = argparse.ArgumentParser(description="QMIE multi-agent briefing (read-only)")
    p.add_argument("--db", type=Path, default=None)
    args = p.parse_args(argv)

    async def _run() -> dict[str, Any]:
        db_path = args.db or _default_db()
        signals: list[dict[str, Any]] = []
        if db_path and db_path.exists():
            from db import Database
            db = Database(f"sqlite+aiosqlite:///{db_path}")
            await db.init()
            signals = await db.recent_signals(limit=40)
        return await run_briefing(
            signals=signals, radar=None, allocation=None, db_path=db_path,
        )

    print(json.dumps(asyncio.run(_run()), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
