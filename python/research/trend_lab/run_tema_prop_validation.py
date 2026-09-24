"""TEMA 4h A/A+ prop compliance on Top-3 vs Top-10 (frozen parquet book).

Usage::

    cd python
    python -m backtest.run --start 2024-01-01 --split 2025-01-01 \\
        --min-adx 20 --min-atr-pct 0.4 --max-atr-pct 4.0 --tf 4h
    python -m research.trend_lab.run_tema_prop_validation
    python -m research.trend_lab.run_tema_prop_validation --quick
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from .tema_prop_universe import (
    TOP3_SYMBOLS,
    TOP10_SYMBOLS,
    compare_universes,
    default_parquet,
    kpi_table,
)

log = logging.getLogger("tema_prop")

ART = Path(__file__).resolve().parents[1] / "artifacts"
CURSOR = Path("/opt/cursor/artifacts")


def _json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_ready(v) for v in obj]
    if isinstance(obj, float):
        return None if obj != obj else obj
    return obj


def _maybe_run_backtest(parquet: Path, *, quick: bool) -> None:
    if parquet.exists():
        return
    symbols = list(TOP3_SYMBOLS) if quick else list(TOP10_SYMBOLS)
    cmd = [
        sys.executable,
        "-m",
        "backtest.run",
        "--symbols",
        *symbols,
        "--tf",
        "4h",
        "--start",
        "2024-01-01",
        "--split",
        "2025-01-01",
        "--min-adx",
        "20",
        "--min-atr-pct",
        "0.4",
        "--max-atr-pct",
        "4.0",
    ]
    log.info("Missing %s — running backtest: %s", parquet, " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(parquet.parents[2]))


def run(*, quick: bool = False, run_backtest: bool = False) -> dict[str, Any]:
    parquet = default_parquet()
    if run_backtest or not parquet.exists():
        _maybe_run_backtest(parquet, quick=quick)
    if not parquet.exists():
        raise FileNotFoundError(
            f"{parquet} missing. Run: python -m backtest.run (see docs/backtest-baseline.md)"
        )

    payload = compare_universes(parquet)
    payload["note"] = (
        "Frozen 4h TEMA A/A+ OOS >=2025-01-01, ADX>=20, ATR% 0.4-4.0. "
        "Paper cash sim: 1% stake, max 3 slots, rank by score, isolated 1x. Not an order."
    )
    payload["quick"] = quick
    return payload


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="TEMA 4h prop KPIs Top3 vs Top10")
    p.add_argument("--quick", action="store_true", help="If backtest needed, only Top-3 symbols")
    p.add_argument(
        "--run-backtest",
        action="store_true",
        help="Run backtest.run when parquet is missing",
    )
    p.add_argument("--parquet", default=str(default_parquet()))
    args = p.parse_args(argv)

    parquet = Path(args.parquet)
    if args.run_backtest and not parquet.exists():
        _maybe_run_backtest(parquet, quick=args.quick)
    if not parquet.exists():
        print(f"Missing {parquet}. Run python -m backtest.run first (or --run-backtest).")
        return 1

    payload = compare_universes(parquet)
    payload["note"] = run.__doc__
    table = kpi_table(payload)
    print(table.to_string(index=False))
    for key, block in payload["universes"].items():
        print(f"\n=== {key} prop checks ===")
        for ck, ok in block["prop"]["checks"].items():
            print(f"  {ck}: {'PASS' if ok else 'FAIL'}")
        print(f"  prop_compliant: {block['prop']['prop_compliant']}")

    ART.mkdir(parents=True, exist_ok=True)
    out = ART / "tema_prop_top3_top10.json"
    out.write_text(json.dumps(_json_ready(payload), indent=2))
    CURSOR.mkdir(parents=True, exist_ok=True)
    (CURSOR / "tema_prop_top3_top10.json").write_text(json.dumps(_json_ready(payload), indent=2))
    print(f"\nWrote {out}")
    print("places_orders=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
