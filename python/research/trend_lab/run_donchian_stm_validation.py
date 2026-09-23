"""Validate Donchian + SUPER_TRADEMAN-style enhancements on Vision 1d data.

Usage (from ``python/``)::

    python -m research.trend_lab.run_donchian_stm_validation
    python -m research.trend_lab.run_donchian_stm_validation --quick
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .data import load_symbol
from .donchian_stm import DonchianStmParams, eval_donchian_stm, trail_sweep
from .evaluate import _bh
from .protocol import SPLIT, WARMUP_BARS, split_frame

log = logging.getLogger("donchian_stm")

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"
CURSOR_ART = Path("/opt/cursor/artifacts")

STM_UNIVERSE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]


def _warmup(lookback: int) -> int:
    return max(WARMUP_BARS, lookback + 20)


def _json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_ready(v) for v in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return _json_ready(asdict(obj))
    if isinstance(obj, float):
        return None if obj != obj else obj
    return obj


def run(*, quick: bool = False) -> dict[str, Any]:
    symbols = STM_UNIVERSE[:2] if quick else STM_UNIVERSE
    configs = [
        ("turtle_55", DonchianStmParams(entry_lookback=55, mode="turtle")),
        ("turtle_20", DonchianStmParams(entry_lookback=20, mode="turtle")),
        ("qmie_coil_20", DonchianStmParams(entry_lookback=20, mode="qmie_coil", coil_max_width_pct=15.0)),
    ]
    if quick:
        configs = configs[:2]

    payload: dict[str, Any] = {
        "protocol": asdict(SPLIT),
        "note": "Research only. Long/short attribution + trail sweep (STM-style). Not live W_*.",
        "symbols": {},
    }

    for sym in symbols:
        df, src = load_symbol(sym, "1d")
        if df.empty:
            log.warning("skip empty %s", sym)
            continue
        sym_out: dict[str, Any] = {"source": src, "bars": len(df)}
        parts = split_frame(df, warmup=_warmup(55))
        sym_out["bh_oos"] = _bh(parts["oos"])
        for name, params in configs:
            w = _warmup(params.entry_lookback)
            ev = eval_donchian_stm(df, params, warmup=w)
            sym_out[name] = {
                "oos_kpis": ev["oos"],
                "oos_attribution": ev["oos_attribution"],
                "is_attribution": ev["is_attribution"],
            }
            if name == "turtle_55" and not quick:
                sym_out["trail_sweep_55"] = trail_sweep(
                    df, base=params, warmup=w
                ).to_dict(orient="records")
        payload["symbols"][sym] = sym_out
        log.info("%s OOS turtle_55 trades=%s", sym, sym_out.get("turtle_55", {}).get("oos_attribution", {}).get("n"))

    for root in (ARTIFACTS, CURSOR_ART):
        try:
            root.mkdir(parents=True, exist_ok=True)
            path = root / "donchian_stm_validation.json"
            path.write_text(json.dumps(_json_ready(payload), indent=2, default=str))
            log.info("wrote %s", path)
        except OSError as exc:
            log.warning("artifact write %s: %s", root, exc)

    return payload


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Donchian STM validation")
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    out = run(quick=args.quick)
    # console summary
    rows = []
    for sym, data in out.get("symbols", {}).items():
        for cfg in ("turtle_55", "turtle_20", "qmie_coil_20"):
            block = data.get(cfg)
            if not block:
                continue
            att = block["oos_attribution"]
            rows.append(
                {
                    "symbol": sym,
                    "config": cfg,
                    "oos_sharpe": block["oos_kpis"]["sharpe"],
                    "oos_max_dd": block["oos_kpis"]["max_dd"],
                    "trades": att.get("n", 0),
                    "long_total_r": att.get("long", {}).get("total_r"),
                    "short_total_r": att.get("short", {}).get("total_r"),
                }
            )
    if rows:
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
