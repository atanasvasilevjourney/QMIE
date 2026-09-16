"""Trade chart PNG for Discord alerts."""
from __future__ import annotations

from chart_visual import expected_r, render_trade_png, slice_bars_for_signal
from price_fmt import fmt_price
from models import AssetClass


def _bars(n: int = 40, start: float = 100.0):
    out = []
    p = start
    for i in range(n):
        o = p
        c = p + (0.5 if i % 3 else -0.3)
        h = max(o, c) + 0.4
        l = min(o, c) - 0.4
        out.append({"o": o, "h": h, "l": l, "c": c, "t": i})
        p = c
    return out


def test_fmt_price_micro_cap_eight_decimals():
    s = fmt_price(0.00000253, AssetClass.CRYPTO)
    assert s == "0.00000253"


def test_slice_bars_for_signal_bar_time():
    bars = [{"t": 1000, "o": 1, "h": 1, "l": 1, "c": 1}, {"t": 2000, "o": 2, "h": 2, "l": 2, "c": 2}]
    win, idx = slice_bars_for_signal(bars, bar_time_ms=1000, limit=50)
    assert len(win) == 1
    assert idx == 0


def test_expected_r_buy():
    assert expected_r("BUY", 100.0, 95.0, 110.0) == 2.0


def test_render_trade_png_bytes():
    png = render_trade_png(
        _bars(),
        symbol="BTCUSDT",
        timeframe="4h",
        side="BUY",
        entry=102.0,
        stop_loss=98.0,
        take_profit=110.0,
        grade="A+",
        score=88.0,
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 8_000


def test_discord_embed_expected_r_field():
    from models import AssetClass, EventType, Side, TVSignal
    from notifiers.discord import DiscordNotifier

    n = DiscordNotifier(webhook_url="https://example.invalid/webhook")
    sig = TVSignal(
        strategy="QMIE-Scanner",
        event=EventType.ENTRY,
        symbol="ETHUSDT",
        asset_class=AssetClass.CRYPTO,
        timeframe="4h",
        side=Side.BUY,
        signal_price=3000.0,
        stop_loss=2900.0,
        take_profit=3200.0,
    )
    embed = n._build_embed(sig, None)
    names = {f["name"] for f in embed["fields"]}
    assert "Expected R" in names
