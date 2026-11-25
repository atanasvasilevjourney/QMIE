"""Derivatives flow — pure logic + mocked snapshot assembly."""
from __future__ import annotations

from scanner.derivatives_flow.core import (
    build_narrative,
    cvd_window,
    key_levels,
    modelled_liq_clusters,
    oi_changes,
    observed_liq_clusters,
    parse_binance_klines,
)


def _bars(n: int, start: float = 60_000.0, step: float = -50.0):
    out = []
    t = 1_700_000_000_000
    px = start
    for i in range(n):
        h = px + 200
        l = px - 200
        out.append({"t": t + i * 14_400_000, "o": px, "h": h, "l": l, "c": px + step, "v": 1.0, "qv": 1e6, "tbq": 5e5})
        px += step
    return out


def test_parse_binance_klines_shapes():
    raw = [[1_700_000_000_000, "1", "2", "0.5", "1.5", "10", 0, "100", 0, "50", "60", 0]]
    row = parse_binance_klines(raw)[0]
    assert row["t"] == 1_700_000_000_000
    assert row["qv"] == 100.0
    assert row["tbq"] == 60.0


def test_key_levels_merges_nearby_pivots():
    k4h = _bars(80, start=59_000)
    k1d = _bars(60, start=58_000, step=-100)
    lv = key_levels(k1d, k4h, price=58_500)
    assert "resistance" in lv
    assert "support" in lv
    assert len(lv["hvn_4h"]) >= 1


def test_oi_changes_percent():
    last = 7_200_000
    hist = {
        "OKX": [(last - 3_600_000, 100.0), (last, 110.0)],
        "Gate": [(last - 3_600_000, 200.0), (last, 180.0)],
    }
    ch = oi_changes(hist)
    import pytest

    assert ch["OKX"]["chg_1h_pct"] == pytest.approx(10.0)
    assert "aggregate_OKX_Gate_HTX" in ch


def test_cvd_window_sums_exchanges():
    spot = {"A": {1_000: 10.0, 2_000: -5.0}, "B": {2_000: 3.0}}
    w = cvd_window(spot, 1_500)
    assert w["by_exchange_usd"]["A"] == -5.0
    assert w["by_exchange_usd"]["B"] == 3.0
    assert w["total_usd"] == -2.0


def test_modelled_liq_clusters_positive_oi_delta():
    rows = [
        (1, 1e8, 60_000.0, 59_000.0, 61_000.0),
        (2, 1.05e8, 60_100.0, 59_100.0, 61_100.0),
    ]
    clusters = modelled_liq_clusters(rows, price=60_000)
    assert clusters
    assert clusters[0]["side"] in ("long", "short")


def test_observed_liq_clusters_bins():
    rows = [
        {"side": "long", "usd": 1_000.0, "price": 59_500},
        {"side": "long", "usd": 2_000.0, "price": 59_520},
    ]
    obs = observed_liq_clusters(rows, 60_000)
    assert obs
    assert obs[0]["usd"] >= 1_000


def test_narrative_includes_asset():
    snap = {
        "asset": "BTC",
        "price": {"spot_last": 60_000, "change_pct": -1.0, "low": 59_000, "high": 61_000, "quote_volume_usd": 1e9},
        "levels": {"resistance": [], "support": [], "hvn_4h": []},
        "cvd": {
            "spot_24h": {"total_usd": 1e6},
            "perp_24h": {"total_usd": 2e6},
            "spot_since_0000utc": {"total_usd": 0},
            "perp_since_0000utc": {"total_usd": 0},
        },
        "open_interest": {"total_usd_now": 1e10, "change_from_history": {"aggregate_OKX_Gate_HTX": {}}},
        "funding": {"oi_weighted_8h_equiv": 0.0001},
        "liquidations_24h": {"aggregate_of_complete_venues": {"total_usd": 0}},
        "long_short": {},
        "modelled_liq_clusters": {"clusters": []},
    }
    text = build_narrative(snap)
    assert "BTC" in text
    assert "financial advice" in text