"""Run Lamberti SIGN TSMOM on top-10 crypto daily panel. Research only.

Usage (from ``python/``)::

    python -m research.trend_lab.run_tsmom_crypto
    python -m research.trend_lab.run_tsmom_crypto --quick
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from .data import load_panel
from .metrics import kpi_table, kpis_from_net
from .protocol import SPLIT
from .tsmom import (
    TOP10_CRYPTO,
    backtest_single,
    buy_hold_portfolio,
    equal_weight_portfolio,
    sign_weights_daily,
    sign_weights_monthly_lamberti,
)

log = logging.getLogger("tsmom_crypto")
ARTIFACTS = Path("/opt/cursor/artifacts")
LOCAL = Path(__file__).resolve().parents[1] / "artifacts"


def _ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_ready(v) for v in obj]
    if isinstance(obj, float):
        return None if obj != obj else obj  # NaN
    return obj


def _slice_oos(net: pd.Series) -> pd.Series:
    start = pd.Timestamp(SPLIT.oos_start, tz="UTC")
    return net.loc[start:].dropna()


def run(*, quick: bool = False) -> dict[str, Any]:
    symbols = TOP10_CRYPTO[:5] if quick else TOP10_CRYPTO
    panel, sources = load_panel(symbols, tf="1d")
    panel = panel.dropna(how="all").ffill().dropna(how="any")
    if panel.empty or len(panel.columns) < 2:
        raise RuntimeError(f"insufficient daily panel for {symbols}")

    is_end = pd.Timestamp(SPLIT.is_end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    oos_start = pd.Timestamp(SPLIT.oos_start, tz="UTC")

    variants = {
        "sign_monthly_l/s": ("monthly", False),
        "sign_monthly_long": ("monthly", True),
        "sign_daily_l/s": ("daily", False),
        "sign_daily_long": ("daily", True),
    }
    per_asset: dict[str, dict[str, dict[str, float]]] = {}
    weight_panels: dict[str, pd.DataFrame] = {}

    for label, (mode, long_only) in variants.items():
        cols = {}
        for sym in panel.columns:
            close = panel[sym]
            if mode == "monthly":
                w = sign_weights_monthly_lamberti(close, long_only=long_only)
            else:
                w = sign_weights_daily(close, long_only=long_only)
            bt = backtest_single(close, w)
            per_asset.setdefault(sym, {})[label] = {
                "full": kpis_from_net(bt["net"]),
                "oos": kpis_from_net(_slice_oos(bt["net"])),
                "is": kpis_from_net(bt["net"].loc[:is_end]),
            }
            cols[sym] = w
        weight_panels[label] = pd.DataFrame(cols, index=panel.index)

    book_rows: dict[str, dict[str, dict[str, float]]] = {}
    for label, wpanel in weight_panels.items():
        book = equal_weight_portfolio(panel, wpanel)
        bh = buy_hold_portfolio(panel)
        book_rows[label] = {
            "book_full": kpis_from_net(book["net"]),
            "book_oos": kpis_from_net(_slice_oos(book["net"])),
            "book_is": kpis_from_net(book["net"].loc[:is_end]),
            "bh_oos": kpis_from_net(_slice_oos(bh)),
        }

    summary = {
        "protocol": {
            "is": f"{SPLIT.is_start} → {SPLIT.is_end}",
            "oos": f"{SPLIT.oos_start} → {SPLIT.oos_end}",
            "note": SPLIT.requested_note,
        },
        "universe": list(panel.columns),
        "sources": sources,
        "bars": int(len(panel)),
        "reference": "https://github.com/maxlamberti/time-series-momentum (SIGN baseline)",
        "trading_rules": {
            "signal": "sign(rolling compound return over 365d) × SIGMA_TARGET / EWMσ(60)",
            "rebalance": "monthly (Lamberti) or daily",
            "execution": "weight held with 1-day lag; 3.25 bps turnover cost",
            "portfolio": "equal 1/n capital per name in top-10",
            "long_short": "default L/S; long-only variant clips negative weights to 0",
            "risk_caps": "per-name |w|<=1; portfolio gross<=1 after equal 1/n split",
        },
        "per_asset_oos_sharpe": {
            sym: {k: v["oos"]["sharpe"] for k, v in per_asset[sym].items()}
            for sym in panel.columns
        },
        "books": book_rows,
    }

    out_dir = ARTIFACTS if ARTIFACTS.is_dir() else LOCAL
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "tsmom_top10_crypto.json"
    path.write_text(json.dumps(_ready(summary), indent=2), encoding="utf-8")
    log.info("wrote %s", path)

    tbl = kpi_table({k: v["book_oos"] for k, v in book_rows.items()})
    tbl_path = out_dir / "tsmom_top10_oos_kpis.csv"
    tbl.to_csv(tbl_path)
    log.info("OOS KPIs:\n%s", tbl.to_string())

    eq_path = out_dir / "tsmom_top10_equity.csv"
    eq_cols = {}
    for label, wpanel in weight_panels.items():
        if label != "sign_monthly_l/s":
            continue
        book = equal_weight_portfolio(panel, wpanel)
        eq_cols[label] = book["equity"]
    eq_cols["buy_hold"] = (1.0 + buy_hold_portfolio(panel)).cumprod()
    pd.DataFrame(eq_cols).to_csv(eq_path)

    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--quick", action="store_true", help="5 symbols only")
    args = p.parse_args()
    run(quick=args.quick)


if __name__ == "__main__":
    main()
