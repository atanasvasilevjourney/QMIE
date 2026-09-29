"""Execute 09_strategy_performance_now notebook logic for CI / cloud runs."""
from __future__ import annotations

import json
from pathlib import Path

from research.strategy_performance import (
    FROZEN_BASELINE,
    GOALS,
    default_window,
    goals_check,
    journal_stats_sync,
    run_tema_backtest,
    DEFAULT_SYMBOLS,
)
from backtest.donchian_turtle import apply_split_metrics, resolve_universe, run_turtle_portfolio
from scanner.donchian_turtle import TurtleParams


def main() -> dict:
    start, end, split = default_window()
    out: dict = {"window": {"start": str(start), "end": str(end), "split": str(split)}}
    out["frozen_baseline"] = FROZEN_BASELINE
    frame, summaries = run_tema_backtest(
        DEFAULT_SYMBOLS, ["4h"], start, end, split=split,
    )
    out["tema_signals"] = len(frame)
    out["tema_oos_refresh"] = {
        k: (s.to_dict() if s else None) for k, s in summaries.items()
    }
    s4 = summaries.get("4h")
    out["four_h_goals_check"] = goals_check(s4) if s4 else {}
    out["goals"] = GOALS
    out["journal"] = journal_stats_sync()
    uni, src = resolve_universe(30)
    turtle = run_turtle_portfolio(uni, start, end, params=TurtleParams(), max_positions=10)
    apply_split_metrics(turtle, split)
    out["donchian_turtle"] = {
        "universe_source": src,
        "symbols_loaded": len(turtle.universe),
        "metrics": turtle.metrics,
        "oos_metrics": turtle.oos_metrics,
    }
    return out


if __name__ == "__main__":
    report = main()
    print(json.dumps(report, indent=2))
    art = Path("/opt/cursor/artifacts/strategy_performance_now.json")
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps(report, indent=2))
