#!/usr/bin/env python3
"""Execute long-vol event study and write PNGs (notebook companion)."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.data_loader import load_klines  # noqa: E402
from long_vol.backtest.event_study import bucket_summary, run_event_study  # noqa: E402
from long_vol.config import load_config  # noqa: E402
from long_vol.viz import (  # noqa: E402
    save_bucket_bars,
    save_equity_curve,
    save_feature_scatter,
    save_gate_funnel,
    save_horizon_means,
    save_return_hist,
)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT", "DOGEUSDT", "BNBUSDT"]
LOOKBACK_DAYS = 365
OUT = Path(__file__).resolve().parent / "output" / "long_vol"
ART = Path("/opt/cursor/artifacts")


def main() -> None:
    cfg = load_config(ROOT / "configs" / "long_vol_v1.yaml")
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=LOOKBACK_DAYS)
    panels: dict = {}
    for sym in SYMBOLS:
        df = load_klines(sym, "15m", start, end)
        if len(df) > 500:
            panels[sym] = df
    if not panels:
        raise SystemExit("no 15m data loaded")

    # Spec compression+don (strict); fallback chart layer uses don-only if sparse
    result = run_event_study(panels, cfg, require_compression=True)
    if result.events.empty:
        result = run_event_study(panels, cfg, require_compression=False)
    ev = result.events
    print(f"symbols={list(panels)} raw_triggers={len(ev)} all_gates={int(ev['all_gates'].sum()) if 'all_gates' in ev.columns else 0}")

    OUT.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)

    save_horizon_means(ev, OUT / "horizon_means.png", title=f"Long-vol triggers ({start} → {end})")
    save_return_hist(ev, OUT / "ret_24h_hist.png")
    save_gate_funnel(result.attribution, OUT / "gate_funnel.png")
    save_feature_scatter(ev, OUT / "scatter_dist_atr.png")
    buckets = bucket_summary(ev, "dist_atr")
    save_bucket_bars(buckets, OUT / "bucket_dist_atr.png")
    save_equity_curve(ev, OUT / "equity_nonoverlap_24h.png")

    for name in [
        "horizon_means.png",
        "ret_24h_hist.png",
        "gate_funnel.png",
        "scatter_dist_atr.png",
        "bucket_dist_atr.png",
        "equity_nonoverlap_24h.png",
    ]:
        src = OUT / name
        if src.exists():
            (ART / f"long_vol_{name}").write_bytes(src.read_bytes())

    ev.to_csv(OUT / "events.csv", index=False)
    result.attribution.to_csv(OUT / "attribution.csv", index=False)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
