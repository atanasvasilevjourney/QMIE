from __future__ import annotations

from models import AssetClass, EventType, Grade, Side, TVSignal
from notifiers.discord import DiscordNotifier


def test_levier_embed_has_tweet_fields():
    n = DiscordNotifier(webhook_url="http://example.invalid/hook")
    sig = TVSignal(
        strategy="QMIE-LevierScan",
        event=EventType.ENTRY,
        symbol="UNIUSDT",
        asset_class=AssetClass.CRYPTO,
        timeframe="30m",
        side=Side.BUY,
        signal_price=7.6314,
        grade=Grade.B,
        adx=12.0,
        rsi=73.0,
        atr_pct=0.54,
        setup_type="levier_scan",
        reason="BULLISH_TRENDING",
        levier_rank=1,
        levier_display="$UNI [HL]",
        levier_vwap24=7.3758,
        levier_dist=0.2556,
        levier_dist_pct=3.47,
        levier_rsi_label="73 (+6)",
        levier_quote_vol=2939826.0,
        venue_tag="HL",
    )
    embed = n._build_embed(sig, None)
    assert "UNI" in embed["title"]
    assert embed["footer"]["text"].endswith("LevierScan")
    content = n._levier_tweet_content(sig)
    assert "#LevierScan" in content
    assert "30-min" in content
