"""BTC + QQQ + GLD — ranked Carver book, equal-weight, Donchian, FTI gate.

US session calendar (``mixed_panel``). Research only.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from research.trend_lab.allocation import blend_weights
from research.trend_lab.carver_book import (
    ANN_SESSIONS,
    BookParams,
    book_from_raw_weights,
    carver_weight_panel,
    pick_vol_target,
    slice_kpis,
)
from research.trend_lab.data import mixed_panel
from research.trend_lab.donchian_combo import equal_weight_portfolio
from research.trend_lab.donchian_nb08 import Donchian08Params, donchian_nb08_weight_panel
from research.trend_lab.fti_khalsa import fti_panel
from research.trend_lab.metrics import kpis_from_net
from research.trend_lab.protocol import SPLIT

log = logging.getLogger("btc_qqq_gld")
COST_BPS = 2.0


def _close_ohlcv(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """ETFs lack Vision OHLCV; use close for H/L (research approximation)."""
    out = {}
    for c in panel.columns:
        cl = panel[c].astype(float)
        out[c] = pd.DataFrame(
            {"open": cl, "high": cl, "low": cl, "close": cl, "volume": 1.0},
            index=panel.index,
        )
    return out


def main() -> None:
    panel, sources = mixed_panel()
    if panel.empty:
        raise RuntimeError("empty mixed panel")
    is_end = pd.Timestamp(SPLIT.is_end, tz="UTC")
    oos_start = pd.Timestamp(SPLIT.oos_start, tz="UTC")
    is_p = panel.loc[:is_end]
    oos_p = panel.loc[oos_start:]

    raw_w = carver_weight_panel(panel, use_cs=True, ann_days=ANN_SESSIONS)
    picked = pick_vol_target(is_p, raw_w.reindex(is_p.index).fillna(0.0), lookback=60, top_n=2)
    params = BookParams(vol_target=picked["vol_target"], lookback=60, top_n=2, cost_bps=COST_BPS)

    book_rank = book_from_raw_weights(panel, raw_w, params)
    book_all3 = book_from_raw_weights(
        panel, raw_w, BookParams(vol_target=params.vol_target, lookback=60, top_n=3, cost_bps=COST_BPS),
    )
    bh = panel.pct_change(fill_method=None).mean(axis=1).fillna(0.0)

    ohlcv = _close_ohlcv(panel)
    w_don = donchian_nb08_weight_panel(ohlcv, Donchian08Params(target_vol_ann=0.17))
    w_blend = pd.DataFrame(
        {c: blend_weights(raw_w[c], w_don[c], mix=0.5) for c in panel.columns},
        index=panel.index,
    )
    fti = fti_panel(panel)
    gate = (fti.shift(1) > 0).astype(float)
    w_car_g = raw_w.mul(gate).fillna(0.0)
    w_blend_g = w_blend.mul(gate).fillna(0.0)

    def eq_net(w: pd.DataFrame) -> pd.Series:
        return equal_weight_portfolio(w, panel, cost_bps=COST_BPS)

    rows = [
        ("ranked_carver_top2", book_rank["net"]),
        ("carver_all3_ranked", book_all3["net"]),
        ("equal_weight_carver", eq_net(raw_w)),
        ("equal_weight_blend", eq_net(w_blend)),
        ("carver_fti_gate", eq_net(w_car_g)),
        ("blend_fti_gate", eq_net(w_blend_g)),
        ("equal_weight_donchian", eq_net(w_don)),
        ("equal_bh", bh),
    ]
    results = []
    for name, net in rows:
        oos = net.loc[oos_start:].fillna(0.0)
        k = kpis_from_net(oos, ann=ANN_SESSIONS)
        results.append({"book": name, **k, "oos_pnl_100k": float(100_000 * ((1 + oos).prod() - 1))})

    payload = {
        "universe": list(panel.columns),
        "sources": sources,
        "calendar": "US sessions; BTC as-of last UTC daily on ETF dates",
        "ann_days": ANN_SESSIONS,
        "ranked_params": {"vol_target": params.vol_target, "top_n": 2, "lookback": 60},
        "is_vol_grid_top": picked["table"].head(5).to_dict(orient="records"),
        "panel_start": str(panel.index[0].date()),
        "panel_end": str(panel.index[-1].date()),
        "oos_start": str(oos_start.date()),
        "results_oos": results,
        "note_donchian": "QQQ/GLD use close-only OHLCV proxy for nb08 Donchian",
    }
    out = Path("/opt/cursor/artifacts/btc_qqq_gld_suite.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float))
    log.info("wrote %s", out)
    tbl = pd.DataFrame(results).sort_values("sharpe", ascending=False)
    print(tbl.to_string(index=False, float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
