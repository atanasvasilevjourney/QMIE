"""
QMIE — one-variable strategy review
===================================
Read journal stats + declared goals, write a markdown review, and
propose *exactly one* knob change. Never writes live `.env`.

    cd python && python -m improve.review
"""
from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOALS = REPO_ROOT / "strategy" / "goals.yaml"
DEFAULT_BASELINE = REPO_ROOT / "strategy" / "baseline.yaml"
DEFAULT_REVIEWS = REPO_ROOT / "strategy" / "reviews"


@dataclass(frozen=True)
class Knob:
    name: str
    from_value: Any
    to_value: Any
    why: str


# Scientific-method catalog. First unused knob whose `from_value` matches
# the current baseline is the only proposal for this cycle.
KNOB_CATALOG: tuple[Knob, ...] = (
    Knob(
        "scan_timeframes",
        "1h,4h",
        "4h",
        "Drop 1h alerts. Frozen TMA OOS: 4h A/A+ PF 1.61 / E[R] +0.309; "
        "1h A/A+ PF 1.14 dilutes the pooled book under PF 1.3. "
        "Do not also change ADX in the same cycle.",
    ),
    Knob(
        "sig_min_adx",
        0.0,
        20.0,
        "Enable the ADX trend-strength gate that Sprint 1 already recommends. "
        "Measure A/A+ expectancy before vs after; do not retune weights.",
    ),
    Knob(
        "alloc_top_long",
        3,
        2,
        "If rank-3 longs have expectancy ≤ 0 in the journal, drop them. "
        "Tighter book, same scoring math.",
    ),
    Knob(
        "alloc_top_short",
        3,
        2,
        "Same as alloc_top_long, short book only.",
    ),
    Knob(
        "sig_funding_rate_threshold",
        0.001,
        0.0005,
        "Tighten crowded-side suppression if winners cluster on extreme funding.",
    ),
    Knob(
        "alloc_cluster_max",
        1,
        2,
        "Allow a second name in a cluster only if the first slot's expectancy "
        "is already above the goal. Default stays 1.",
    ),
)


def _coerce(raw: str) -> Any:
    v = raw.strip()
    if v.lower() in ("null", "none", "~", ""):
        return None
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


def load_simple_yaml(path: Path) -> dict[str, Any]:
    """Nested maps + scalars. No lists. Comments stripped."""
    data: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, data)]
    text = path.read_text(encoding="utf-8")
    for raw in text.splitlines():
        if "#" in raw:
            raw = raw.split("#", 1)[0]
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, _, val = raw.strip().partition(":")
        key = key.strip()
        val = val.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if val == "":
            nested: dict[str, Any] = {}
            parent[key] = nested
            stack.append((indent, nested))
        else:
            parent[key] = _coerce(val)
    return data


def journal_snapshot(db_path: Optional[Path]) -> dict[str, Any]:
    empty = {
        "fills": 0,
        "closed": 0,
        "wins": 0,
        "losses": 0,
        "win_pct": 0.0,
        "avg_realized_r": None,
        "db": None if db_path is None else str(db_path),
        "available": False,
    }
    if db_path is None or not db_path.exists():
        return empty
    try:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT f.outcome, f.realized_r, s.grade
            FROM fills f
            JOIN signals s ON s.id = f.signal_id
            WHERE s.grade IN ('A+', 'A')
            """
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return empty
    closed = [r for r in rows if r["outcome"] not in (None, "OPEN")]
    wins = [r for r in closed if r["outcome"] == "WIN"]
    r_vals = [float(r["realized_r"]) for r in closed if r["realized_r"] is not None]
    return {
        "fills": len(rows),
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(closed) - len(wins),
        "win_pct": round(100.0 * len(wins) / len(closed), 1) if closed else 0.0,
        "avg_realized_r": round(sum(r_vals) / len(r_vals), 3) if r_vals else None,
        "db": str(db_path),
        "available": True,
    }


def _towards_goal(stats: dict[str, Any], goals: dict[str, Any]) -> str:
    success = goals.get("success") or {}
    failure = goals.get("failure") or {}
    min_fills = int((goals.get("review") or {}).get("min_closed_fills") or 30)
    closed = int(stats.get("closed") or 0)
    if closed < min_fills:
        return "insufficient_sample"
    win = float(stats.get("win_pct") or 0)
    exp = stats.get("avg_realized_r")
    min_win = success.get("min_win_pct")
    min_exp = success.get("min_expectancy_r")
    fail_win = failure.get("win_pct_below")
    fail_exp = failure.get("expectancy_r_below")
    if fail_win is not None and win < float(fail_win):
        return "failure"
    if fail_exp is not None and exp is not None and exp < float(fail_exp):
        return "failure"
    ok_win = min_win is None or win >= float(min_win)
    ok_exp = min_exp is None or (exp is not None and exp >= float(min_exp))
    if ok_win and ok_exp:
        return "success"
    return "short_of_goal"


def already_proposed(reviews_dir: Path) -> set[str]:
    found: set[str] = set()
    if not reviews_dir.exists():
        return found
    for p in reviews_dir.glob("*.md"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("proposed_knob:"):
                found.add(line.split(":", 1)[1].strip())
    return found


def pick_knob(baseline: dict[str, Any], used: set[str]) -> Optional[Knob]:
    for knob in KNOB_CATALOG:
        if knob.name in used:
            continue
        current = baseline.get(knob.name)
        if current is None:
            continue
        if current == knob.from_value or (
            isinstance(current, (int, float))
            and isinstance(knob.from_value, (int, float))
            and float(current) == float(knob.from_value)
        ):
            return knob
    return None


def render_review(
    *,
    when: date,
    stats: dict[str, Any],
    goals: dict[str, Any],
    baseline: dict[str, Any],
    verdict: str,
    knob: Optional[Knob],
) -> str:
    success = goals.get("success") or {}
    lines = [
        f"# QMIE review — {when.isoformat()}",
        "",
        f"verdict: {verdict}",
        f"proposed_knob: {knob.name if knob else 'none'}",
        f"proposed_from: {knob.from_value if knob else ''}",
        f"proposed_to: {knob.to_value if knob else ''}",
        "applied: false",
        "",
        "This file is a proposal. Do **not** auto-write `.env`. "
        "Change one live knob only after a human applies it.",
        "",
        "## Goal",
        "",
        f"- Success: win% ≥ {success.get('min_win_pct')} · "
        f"expectancy R ≥ {success.get('min_expectancy_r')} · "
        f"Sharpe ≥ {success.get('min_sharpe')} (backtest) · "
        f"max DD ≤ {success.get('max_drawdown_pct')}%",
        f"- Failure: win% < {(goals.get('failure') or {}).get('win_pct_below')} "
        f"or expectancy R < {(goals.get('failure') or {}).get('expectancy_r_below')} "
        f"after {(goals.get('review') or {}).get('min_closed_fills')} closed A/A+ fills",
        "",
        "## Journal (A/A+ fills)",
        "",
        f"- db: `{stats.get('db')}`",
        f"- closed: {stats.get('closed')}  wins: {stats.get('wins')}  "
        f"losses: {stats.get('losses')}  win%: {stats.get('win_pct')}",
        f"- avg realized R: {stats.get('avg_realized_r')}",
        "",
        "## Baseline knobs",
        "",
    ]
    for k, v in baseline.items():
        if isinstance(v, dict):
            continue
        lines.append(f"- `{k}`: {v}")
    lines += [
        "",
        "## Hypothesis",
        "",
    ]
    if verdict == "insufficient_sample":
        lines.append(
            "Not enough closed fills. Do not change anything. Keep journaling "
            "manual entries against `GET /signals` ids."
        )
    elif knob is None:
        lines.append(
            "No unused catalog knob matches the current baseline. "
            "Re-run the frozen OOS backtest (`docs/backtest-baseline.md`) "
            "before inventing a new variable."
        )
    else:
        lines.append(
            f"Change **only** `{knob.name}` from `{knob.from_value}` to "
            f"`{knob.to_value}`."
        )
        lines.append("")
        lines.append(knob.why)
        lines.append("")
        lines.append(
            "If the next cycle moves toward the goal, this value is the new "
            "baseline. If it moves toward failure, revert and pick the next knob."
        )
    lines += [
        "",
        "## Out of scope",
        "",
        "- No broker execution, Hermes, Signum, HyperLiquid, or Railway.",
        "- No TradingView MCP. Charts = `pine/quant_visualizer.pine` + deep links.",
        "- Do not retune scoring weights on the reporting sample.",
        "",
    ]
    return "\n".join(lines)


def run_review(
    *,
    goals_path: Path = DEFAULT_GOALS,
    baseline_path: Path = DEFAULT_BASELINE,
    reviews_dir: Path = DEFAULT_REVIEWS,
    db_path: Optional[Path] = None,
    today: Optional[date] = None,
) -> Path:
    goals = load_simple_yaml(goals_path)
    baseline = load_simple_yaml(baseline_path)
    stats = journal_snapshot(db_path)
    verdict = _towards_goal(stats, goals)
    knob = None
    if verdict != "insufficient_sample":
        knob = pick_knob(baseline, already_proposed(reviews_dir))
    when = today or datetime.now(timezone.utc).date()
    body = render_review(
        when=when, stats=stats, goals=goals, baseline=baseline,
        verdict=verdict, knob=knob,
    )
    reviews_dir.mkdir(parents=True, exist_ok=True)
    out = reviews_dir / f"{when.isoformat()}.md"
    if out.exists():
        out = reviews_dir / f"{when.isoformat()}-{datetime.now(timezone.utc).strftime('%H%M%S')}.md"
    out.write_text(body, encoding="utf-8")
    return out


def _default_db() -> Optional[Path]:
    candidate = Path("data/qmie.db")
    if candidate.exists():
        return candidate
    alt = REPO_ROOT / "python" / "data" / "qmie.db"
    return alt if alt.exists() else None


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="QMIE one-variable strategy review")
    p.add_argument("--goals", type=Path, default=DEFAULT_GOALS)
    p.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    p.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    p.add_argument("--db", type=Path, default=None)
    args = p.parse_args(argv)
    out = run_review(
        goals_path=args.goals,
        baseline_path=args.baseline,
        reviews_dir=args.reviews,
        db_path=args.db or _default_db(),
    )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
