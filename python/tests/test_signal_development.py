"""Repeat-alert development threads + radar validity."""
from __future__ import annotations

from signal_development import assess_radar_validity, build_signal_developments


def test_assess_daily_breakout_buy_still_green():
    status, detail = assess_radar_validity(
        side="SELL",
        strategy="QMIE-DailyBreakout",
        timeframe="1d",
        radar={"color": "RED", "days_in_state": 2, "is_late_stage": False},
    )
    assert status == "FRESH"
    assert "RED" in detail

    bad, _ = assess_radar_validity(
        side="SELL",
        strategy="QMIE-DailyBreakout",
        timeframe="1d",
        radar={"color": "GREEN", "days_in_state": 5, "is_late_stage": False},
    )
    assert bad == "INVALID"


def test_build_threads_groups_repeat_alerts():
    rows = [
        {"id": 1, "event": "entry", "symbol": "TIAUSDT", "strategy": "QMIE-DailyBreakout",
         "side": "SELL", "signal_price": 0.32, "received_at": "2026-09-10T00:00:00+00:00"},
        {"id": 2, "event": "entry", "symbol": "TIAUSDT", "strategy": "QMIE-DailyBreakout",
         "side": "SELL", "signal_price": 0.31, "received_at": "2026-09-15T00:00:00+00:00"},
        {"id": 3, "event": "entry", "symbol": "BTCUSDT", "strategy": "QMIE-Scanner",
         "side": "BUY", "signal_price": 60000, "received_at": "2026-09-16T00:00:00+00:00"},
    ]
    radar = [
        {"symbol": "TIAUSDT", "color": "RED", "days_in_state": 1, "price": 0.30,
         "is_late_stage": False, "is_fresh_flip": True, "adx": 25},
    ]
    threads = build_signal_developments(rows, radar_rows=radar, min_alerts=2)
    assert len(threads) == 1
    t = threads[0]
    assert t["symbol"] == "TIAUSDT"
    assert t["alert_count"] == 2
    assert t["validity_status"] in ("FRESH", "VALID")
    assert t["pct_since_first"] is not None
    assert t["mark_price"] == 0.30
    assert len(t["timeline"]) == 2
