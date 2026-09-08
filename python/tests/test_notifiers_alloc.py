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


def test_discord_expansion_title():
    n = DiscordNotifier(webhook_url="https://example.invalid/webhook")
    sig = TVSignal(
        strategy="QMIE-DailyExpansion",
        event=EventType.ENTRY,
        symbol="SOLUSDT",
        asset_class=AssetClass.CRYPTO,
        timeframe="1d",
        side=Side.BUY,
        signal_price=107.0,
        stop_loss=98.0,
        reason="coil_breakout_up",
        setup_type="expansion",
    )
    embed = n._build_embed(sig, None)
    assert "EXPANSION LONG — SPOT COIL-UP" in embed["title"]
    assert "BREAKOUT LONG" not in embed["title"]


def test_discord_expansion_short_title():
    n = DiscordNotifier(webhook_url="https://example.invalid/webhook")
    sig = TVSignal(
        strategy="QMIE-DailyExpansion",
        event=EventType.ENTRY,
        symbol="ETHUSDT",
        asset_class=AssetClass.CRYPTO,
        timeframe="1d",
        side=Side.SELL,
        signal_price=3000.0,
        stop_loss=3120.0,
        reason="coil_breakout_down",
        setup_type="expansion",
    )
    embed = n._build_embed(sig, None)
    assert "EXPANSION SHORT — SPOT COIL-DOWN" in embed["title"]
    assert "BREAKOUT SHORT" not in embed["title"]


def test_discord_breakout_short_title():
    n = DiscordNotifier(webhook_url="https://example.invalid/webhook")
    sig = TVSignal(
        strategy="QMIE-DailyBreakout",
        event=EventType.ENTRY,
        symbol="ETHUSDT",
        asset_class=AssetClass.CRYPTO,
        timeframe="1d",
        side=Side.SELL,
        signal_price=3000.0,
        reason="trend_start_short",
        setup_type="breakout",
    )
    embed = n._build_embed(sig, None)
    assert "BREAKOUT SHORT" in embed["title"]
    assert "BREAKOUT LONG" not in embed["title"]


def test_telegram_includes_ranked_line():
    n = TelegramNotifier(bot_token="x", chat_id="1")
    text = n._format(
        _sig(alloc_rank=2, alloc_weight_pct=16.67, alloc_cluster="ETH"),
        None,
    )
    assert "Ranked" in text
    assert r"\#2" in text
    assert "ETH" in text


def _slack_field_map(blocks: list) -> dict[str, str]:
    out: dict[str, str] = {}
    for b in blocks:
        for f in b.get("fields") or []:
            raw = f["text"]
            label, _, value = raw.partition("\n")
            out[label.strip("*")] = value
    return out


def test_slack_blocks_include_ranked_slot():
    from notifiers.slack import SlackNotifier

    n = SlackNotifier(webhook_url="https://hooks.slack.com/services/x/y/z")
    blocks = n._build_blocks(
        _sig(alloc_rank=1, alloc_weight_pct=25.0, alloc_cluster="BTC"),
        None,
    )
    fields = _slack_field_map(blocks)
    assert "Ranked slot" in fields
    assert "#1" in fields["Ranked slot"]
    assert "25.0%" in fields["Ranked slot"]
    assert "BTC" in fields["Ranked slot"]


def test_slack_breakout_title():
    from notifiers.slack import _signal_title

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
    assert "BREAKOUT LONG" in _signal_title(sig)


def test_slack_expansion_title():
    from notifiers.slack import _signal_title

    sig = TVSignal(
        strategy="QMIE-DailyExpansion",
        event=EventType.ENTRY,
        symbol="SOLUSDT",
        asset_class=AssetClass.CRYPTO,
        timeframe="1d",
        side=Side.BUY,
        signal_price=107.0,
        stop_loss=98.0,
        reason="coil_breakout_up",
        setup_type="expansion",
    )
    title = _signal_title(sig)
    assert "EXPANSION LONG — SPOT COIL-UP" in title
    assert "BREAKOUT LONG" not in title


def test_slack_tv_button_when_chart_url():
    from notifiers.slack import SlackNotifier

    n = SlackNotifier(webhook_url="https://hooks.slack.com/services/x/y/z")
    sig = _sig()
    sig.chart_url = "https://www.tradingview.com/chart/?symbol=BINANCE:BTCUSDT.P"
    blocks = n._build_blocks(sig, None)
    actions = [b for b in blocks if b.get("type") == "actions"]
    assert actions
    btn = actions[0]["elements"][0]
    assert btn["url"].startswith("https://www.tradingview.com")
    assert "TradingView" in btn["text"]["text"]
