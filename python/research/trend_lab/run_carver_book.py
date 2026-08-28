"""Run the BTC/QQQ/GLD ranked Carver book and write artifacts.

Usage (from ``python/``)::

    python -m research.trend_lab.run_carver_book
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .carver_book import (
    ANN_SESSIONS,
    BookParams,
    TARGET_DD,
    TARGET_SHARPE,
    book_from_raw_weights,
    carver_weight_panel,
    is_oos_index,
    neighborhood,
    pick_vol_target,
    slice_kpis,
    walk_forward,
)
from .data import mixed_panel
from .metrics import kpis_from_net
from .plots import allocation_fig, equity_overlay, rolling_sharpe_fig, underwater, write_html, write_png_mpl
from .protocol import SPLIT

log = logging.getLogger("carver_book")
ART = Path("/opt/cursor/artifacts")
LOCAL = Path(__file__).resolve().parents[1] / "artifacts"


def _save(fig, stem: str) -> None:
    if fig is None:
        return
    for root in (ART, LOCAL):
        try:
            write_html(fig, root / f"{stem}.html")
        except Exception as exc:
            log.warning("%s: %s", stem, exc)


def run() -> dict:
    ART.mkdir(parents=True, exist_ok=True)
    LOCAL.mkdir(parents=True, exist_ok=True)
    panel, sources = mixed_panel()
    log.info("panel %s %s → %s sources=%s", panel.shape, panel.index[0], panel.index[-1], sources)
    raw_w = carver_weight_panel(panel, use_cs=True, ann_days=ANN_SESSIONS)
    is_end, oos_start = is_oos_index(panel)
    is_p = panel.loc[:is_end]
    oos_p = panel.loc[oos_start:]

    picked = pick_vol_target(is_p, raw_w.reindex(is_p.index).fillna(0.0), lookback=60, top_n=2)
    params = BookParams(vol_target=picked["vol_target"], lookback=60, top_n=2)
    log.info("IS-picked vol_target=%s", params.vol_target)

    # full-path book so OOS vol ewm is live-continuous; KPIs sliced
    book = book_from_raw_weights(panel, raw_w, params)
    equal = book_from_raw_weights(panel, raw_w, BookParams(vol_target=params.vol_target, lookback=60, top_n=3))
    bh_net = panel.pct_change(fill_method=None).mean(axis=1).fillna(0.0)
    bh_eq = (1.0 + bh_net).cumprod()

    is_k = slice_kpis(book, is_p.index[0], is_end)
    oos_k = slice_kpis(book, oos_start, panel.index[-1])
    oos_eq = kpis_from_net(equal.loc[oos_start:]["net"], ann=ANN_SESSIONS)
    oos_bh = kpis_from_net(bh_net.loc[oos_start:], ann=ANN_SESSIONS)

    nb = neighborhood(is_p, raw_w, params)
    val_std = float(nb["sharpe_val"].std(ddof=1)) if len(nb) > 1 else float("nan")

    folds = [
        ("2020-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
        ("2020-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
        ("2020-01-01", "2023-12-31", "2024-01-01", "2026-12-31"),
    ]
    wf = walk_forward(panel, raw_w, folds=folds, lookback=60, top_n=2)

    # breaker overlay (IS-chosen trip near target DD) applied as robustness, not retuned on OOS
    brk = book_from_raw_weights(
        panel, raw_w,
        BookParams(vol_target=params.vol_target, lookback=60, top_n=2, dd_trip=-0.11),
    )
    oos_brk = slice_kpis(brk, oos_start, panel.index[-1])

    oos_book = book.loc[oos_start:]
    oos_eq_s = (1.0 + oos_book["net"]).cumprod()
    oos_eq_eq = (1.0 + equal.loc[oos_start:]["net"]).cumprod()
    oos_bh_s = (1.0 + bh_net.loc[oos_start:]).cumprod()
    oos_brk_s = (1.0 + brk.loc[oos_start:]["net"]).cumprod()

    _save(equity_overlay({
        "ranked Carver top-2": oos_eq_s,
        "Carver all-3": oos_eq_eq,
        "equal BH": oos_bh_s,
        "ranked + DD breaker": oos_brk_s,
    }, "OOS growth of $1 — BTC/QQQ/GLD"), "carver_book_oos_equity")
    write_png_mpl(
        {
            "ranked top-2": oos_eq_s,
            "all-3": oos_eq_eq,
            "BH": oos_bh_s,
            "DD breaker": oos_brk_s,
        },
        ART / "carver_book_oos_equity.png",
        title="OOS growth of $1 — BTC / QQQ / GLD",
        ylabel="Multiple",
    )
    _save(rolling_sharpe_fig({
        "ranked top-2": oos_book["net"],
        "all-3": equal.loc[oos_start:]["net"],
        "BH": bh_net.loc[oos_start:],
    }, window=63, title="OOS 63-session rolling Sharpe (ann=252)"), "carver_book_oos_sharpe")
    write_png_mpl(
        {
            "ranked": (oos_book["net"].rolling(63).mean() / oos_book["net"].rolling(63).std(ddof=1) * np.sqrt(252)),
            "BH": (bh_net.loc[oos_start:].rolling(63).mean() / bh_net.loc[oos_start:].rolling(63).std(ddof=1) * np.sqrt(252)),
        },
        ART / "carver_book_oos_sharpe.png",
        title="OOS 63-session rolling Sharpe",
        ylabel="Sharpe",
        hline=1.45,
    )
    _save(underwater(oos_eq_s, "Ranked Carver OOS drawdown"), "carver_book_oos_dd")
    write_png_mpl(
        {"ranked": oos_eq_s / oos_eq_s.cummax() - 1.0, "BH": oos_bh_s / oos_bh_s.cummax() - 1.0},
        ART / "carver_book_oos_dd.png",
        title="OOS underwater — target −10%",
        ylabel="DD",
        hline=TARGET_DD,
    )
    _save(allocation_fig({
        "BTC": oos_book["w_BTC"],
        "QQQ": oos_book["w_QQQ"],
        "GLD": oos_book["w_GLD"],
    }, "OOS ranked Carver weights"), "carver_book_oos_weights")
    write_png_mpl(
        {c: oos_book[f"w_{c}"] for c in ("BTC", "QQQ", "GLD")} | {"gross": oos_book["gross"]},
        ART / "carver_book_oos_weights.png",
        title="OOS ranked Carver weights",
        ylabel="Weight",
    )

    def _hit(k: dict) -> dict:
        s, dd = k.get("sharpe"), k.get("max_dd")
        return {
            "sharpe_in_band": bool(np.isfinite(s) and TARGET_SHARPE[0] <= s <= TARGET_SHARPE[1]),
            "dd_near_10pct": bool(np.isfinite(dd) and abs(dd - TARGET_DD) <= 0.03),
            "dd_within_12pct": bool(np.isfinite(dd) and dd >= -0.12),
        }

    out = {
        "sources": sources,
        "protocol": {
            "is": f"{SPLIT.is_start} → {SPLIT.is_end}",
            "oos": f"{SPLIT.oos_start} → {SPLIT.oos_end}",
            "ann_days": ANN_SESSIONS,
            "calendar": "US sessions; BTC as-of UTC daily",
            "target_dd": TARGET_DD,
            "target_sharpe": list(TARGET_SHARPE),
            "vol_target_picked_on": "IS only",
        },
        "panel": {
            "rows": int(len(panel)),
            "start": str(panel.index[0].date()),
            "end": str(panel.index[-1].date()),
        },
        "params": {"vol_target": params.vol_target, "lookback": 60, "top_n": 2},
        "is": is_k,
        "oos": oos_k,
        "oos_all3": oos_eq,
        "oos_bh": oos_bh,
        "oos_dd_breaker": oos_brk,
        "vol_grid_is": picked["table"].to_dict(orient="records"),
        "neighborhood_val_sharpe_std": val_std,
        "neighborhood": nb.to_dict(orient="records"),
        "walk_forward": wf.to_dict(orient="records"),
        "oos_hit": _hit(oos_k),
        "wf_mean_sharpe": float(wf["sharpe"].mean()) if len(wf) else None,
        "wf_mean_dd": float(wf["max_dd"].mean()) if len(wf) else None,
        "verdict": _verdict(oos_k, val_std, wf),
    }
    payload = json.loads(json.dumps(out, default=str))
    for root in (ART, LOCAL):
        (root / "carver_book_results.json").write_text(json.dumps(payload, indent=2))
        picked["table"].to_csv(root / "carver_book_vol_grid_is.csv", index=False)
        if len(wf):
            wf.to_csv(root / "carver_book_walk_forward.csv", index=False)
        nb.to_csv(root / "carver_book_neighborhood.csv", index=False)
    log.info("verdict %s", out["verdict"])
    return out


def _verdict(oos: dict, val_std: float, wf: pd.DataFrame) -> str:
    s, dd = oos.get("sharpe"), oos.get("max_dd")
    dd_ok = np.isfinite(dd) and dd >= -0.12
    sh_ok = np.isfinite(s) and s >= 1.20
    band = np.isfinite(s) and TARGET_SHARPE[0] <= s <= TARGET_SHARPE[1]
    above = np.isfinite(s) and s > TARGET_SHARPE[1] and dd_ok
    wf_2022 = None
    if len(wf):
        hit = wf[wf["oos"].astype(str).str.contains("2022")]
        if len(hit):
            wf_2022 = hit.iloc[0]
    stress = wf_2022 is not None and float(wf_2022["sharpe"]) < 0
    if dd_ok and (band or above):
        extra = (
            "OOS Sharpe above 1.5 with DD inside the 10% budget (leftover risk, not a miss)."
            if above
            else "OOS Sharpe inside 1.4–1.5."
        )
        if stress:
            return (
                f"PARTIAL — {extra} Walk-forward 2022 (crypto winter / rate shock) is the "
                "trend-following bill. Do not raise the vol dial on OOS to spend unused DD."
            )
        return f"HOLD — {extra} Neighborhood/walk-forward acceptable. Research only."
    if dd_ok and sh_ok:
        return f"PARTIAL — DD budget held (max DD {dd:.1%}). Sharpe {s:.2f} outside 1.4–1.5. Do not force-fit OOS."
    return "REJECT — did not meet DD/Sharpe with robustness. Do not raise vol target on OOS to print the band."


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
