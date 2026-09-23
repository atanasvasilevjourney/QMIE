"""Run AdaptiveTrend replication (arXiv:2602.11708) on Vision 6h (from 4h).

Usage::

    python -m research.trend_lab.run_adaptivetrend_validation
    python -m research.trend_lab.run_adaptivetrend_validation --paper-window
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from .adaptivetrend import AdaptiveTrendParams, eval_adaptivetrend_universe
from .data import CORE, SATELLITES

log = logging.getLogger("adaptivetrend")
ART = Path(__file__).resolve().parents[1] / "artifacts"
CURSOR = Path("/opt/cursor/artifacts")
DEFAULT_SYMBOLS = CORE + ["SOLUSDT"]


def run(*, paper_window: bool = False, quick: bool = False) -> dict:
    syms = DEFAULT_SYMBOLS[:3] if quick else DEFAULT_SYMBOLS
    p = AdaptiveTrendParams()
    ev = eval_adaptivetrend_universe(syms, p, paper_window=paper_window)
    payload = {
        "arxiv": "2602.11708",
        "note": "Fixed-param replication; no monthly per-asset grid search.",
        "symbols": syms,
        "paper_window": paper_window,
        "is_kpis": ev["is"],
        "oos_kpis": ev["oos"],
        "oos_long": ev["oos_long"],
        "oos_short": ev["oos_short"],
        "per_symbol": ev["per_symbol"],
        "params": ev["params"],
    }
    for root in (ART, CURSOR):
        try:
            root.mkdir(parents=True, exist_ok=True)
            (root / "adaptivetrend_validation.json").write_text(json.dumps(payload, indent=2, default=str))
        except OSError as exc:
            log.warning("%s: %s", root, exc)
    return payload


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-window", action="store_true", help="OOS 2022-2024 per arXiv Table 1")
    parser.add_argument("--quick", action="store_true")
    ns = parser.parse_args()
    out = run(paper_window=ns.paper_window, quick=ns.quick)
    row = {
        "window": "paper" if out["paper_window"] else "qmie",
        "oos_sharpe": out["oos_kpis"]["sharpe"],
        "oos_max_dd": out["oos_kpis"]["max_dd"],
        "oos_cagr": out["oos_kpis"]["cagr"],
        "trades": out["oos_long"]["n"] + out["oos_short"]["n"],
    }
    print(pd.DataFrame([row]).to_string(index=False))


if __name__ == "__main__":
    main()
