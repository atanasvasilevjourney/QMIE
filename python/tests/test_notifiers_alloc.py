"""Notifier presentation of ranked-allocation fields. No network."""
from __future__ import annotations

from models import AssetClass, EventType, Side, TVSignal
from notifiers.discord import DiscordNotifier
from notifiers.telegram import TelegramNotifier


def _sig(**extra) -> TVSignal:
    return TVSignal(
        strategy="QMIE-Scanner",
        event=EventType.ENTRY,
        symbol="BTCUSDT",
        asset_class=AssetClass.CRYPTO,
        timeframe="4h",
        side=Side.BUY,
        signal_price=65000.0,
        score=85.0,
        **extra,
    )


def test_discord_embed_includes_ranked_slot():
    n = DiscordNotifier(webhook_url="https://example.invalid/webhook")
    embed = n._build_embed(
        _sig(alloc_rank=1, alloc_weight_pct=25.0, alloc_cluster="BTC"),
        None,
    )
    names = {f["name"] for f in embed["fields"]}
    assert "Ranked slot" in names
    slot = next(f for f in embed["fields"] if f["name"] == "Ranked slot")
    assert "#1" in slot["value"]
    assert "25.0%" in slot["value"]
    assert "BTC" in slot["value"]


def test_discord_breakout_title():
    n = DiscordNotifier(webhook_url="https://example.invalid/webhook")
    sig = TVSignal(
        strategy="QMIE-DailyBreakout",
        event=EventType.ENTRY,
        symbol="ETHUSDT",
        asset_class=AssetClass.CRYPTO,
        timeframe="1d",
        side=Side.BUY,
        signal_price=3000.0,
        reason="trend_start_long",
        setup_type="breakout",
    )
    embed = n._build_embed(sig, None)
    assert "BREAKOUT LONG" in embed["title"]
    names = {f["name"] for f in embed["fields"]}
    assert "Setup" in names


def test_telegram_includes_ranked_line():
    n = TelegramNotifier(bot_token="x", chat_id="1")
    text = n._format(
        _sig(alloc_rank=2, alloc_weight_pct=16.67, alloc_cluster="ETH"),
        None,
    )
    assert "Ranked" in text
    assert r"\#2" in text
    assert "ETH" in text
