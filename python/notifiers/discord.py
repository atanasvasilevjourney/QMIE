"""
QMIE Discord Notifier
=====================
Rich, asset-class-themed embeds. Webhook-only (no bot token, no
gateway connection — keeps deploy footprint tiny).

Colour scheme (institutional, not retail emoji vomit):
    crypto    #F7931A   bitcoin orange
    metal     #FFD700   gold
    future    #4A90E2   institutional blue
    forex     #1ABC9C   teal
    equity    #9B59B6   purple
    sell side overlay → #E74C3C
    buy  side overlay → #2ECC71

Price formatting precision is *asset-aware*. Showing BTC to 2dp
loses meaningful info; showing EURUSD to 2dp is wrong.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp

from .base import Notifier, NotifierError
from models import AssetClass, BrokerResponse, Side, TVSignal

logger = logging.getLogger(__name__)


# ─── Theming ─────────────────────────────────────────────────────────────
ASSET_COLOURS: dict[AssetClass, int] = {
    AssetClass.CRYPTO:  0xF7931A,
    AssetClass.METAL:   0xFFD700,
    AssetClass.FUTURE:  0x4A90E2,
    AssetClass.FOREX:   0x1ABC9C,
    AssetClass.EQUITY:  0x9B59B6,
    AssetClass.OTHER:   0x95A5A6,
}
SIDE_OVERLAY = {Side.BUY: 0x2ECC71, Side.SELL: 0xE74C3C}

GRADE_EMOJI = {
    "A+": "🟢", "A": "🟩", "B": "🟨", "C": "🟧", "REJECT": "🟥",
}


def _price_precision(asset_class: AssetClass, price: float) -> int:
    """Pick decimals based on instrument scale."""
    if asset_class is AssetClass.FOREX:
        # JPY pairs use 3dp, everything else 5dp
        return 3 if price > 10 else 5
    if asset_class is AssetClass.METAL:
        return 2
    if asset_class is AssetClass.FUTURE:
        return 2
    if asset_class is AssetClass.EQUITY:
        return 2
    # Crypto: scale-aware
    if price >= 100:    return 2
    if price >= 1:      return 4
    return 6


def _fmt_price(price: Optional[float], asset_class: AssetClass) -> str:
    if price is None:
        return "—"
    p = _price_precision(asset_class, price)
    return f"{price:,.{p}f}"


# ─── Notifier ────────────────────────────────────────────────────────────
class DiscordNotifier(Notifier):
    name = "discord"

    def __init__(self, *, webhook_url: str, username: str = "QMIE",
                 avatar_url: str = "", timeout: float = 5.0):
        self.webhook_url = webhook_url
        self.username = username
        self.avatar_url = avatar_url
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ─── Embed construction ──────────────────────────────────────────────
    def _build_embed(self, sig: TVSignal,
                     broker_resp: BrokerResponse | None) -> dict[str, Any]:
        side = sig.side or Side.BUY
        # base colour by asset, modulated by side
        base = ASSET_COLOURS.get(sig.asset_class, 0x95A5A6)
        colour = SIDE_OVERLAY.get(side, base) if sig.event.value == "entry" else base

        title_action = "BUY SIGNAL" if side is Side.BUY else "SELL SIGNAL"
        if sig.event.value in ("exit", "close"):
            title_action = "EXIT"
        title = f"{title_action} — {sig.symbol}"
        if sig.timeframe:
            title += f" · {sig.timeframe}"

        ac = sig.asset_class
        fields: list[dict[str, Any]] = []

        # Price block
        fields.append({
            "name": "Price",
            "value": _fmt_price(sig.signal_price or sig.price, ac),
            "inline": True,
        })

        # Trend / regime
        if sig.trend:
            fields.append({"name": "Trend", "value": sig.trend.title(), "inline": True})

        # HTF
        if sig.htf:
            fields.append({"name": "HTF", "value": sig.htf.title(), "inline": True})

        # Score + grade
        if sig.score is not None:
            grade_str = sig.grade.value if sig.grade else "—"
            emoji = GRADE_EMOJI.get(grade_str, "")
            fields.append({
                "name": "Confidence",
                "value": f"{emoji} {grade_str} · {sig.score:.0f}/100",
                "inline": True,
            })

        # SL / TP
        if sig.stop_loss is not None:
            fields.append({"name": "Stop",   "value": _fmt_price(sig.stop_loss, ac), "inline": True})
        if sig.take_profit is not None:
            fields.append({"name": "Target", "value": _fmt_price(sig.take_profit, ac), "inline": True})

        # ADX / ATR
        if sig.adx is not None:
            fields.append({"name": "ADX", "value": f"{sig.adx:.1f}", "inline": True})
        if sig.atr is not None:
            fields.append({"name": "ATR", "value": _fmt_price(sig.atr, ac), "inline": True})

        # Session
        if sig.session:
            fields.append({"name": "Session", "value": sig.session, "inline": True})

        # Broker execution status
        if broker_resp is not None:
            status = broker_resp.status.value
            extra = ""
            if broker_resp.avg_fill_price:
                extra = f" @ {_fmt_price(broker_resp.avg_fill_price, ac)}"
            fields.append({
                "name": f"Execution ({broker_resp.broker})",
                "value": f"{status}{extra}",
                "inline": False,
            })
            if broker_resp.error:
                fields.append({
                    "name": "⚠️ Error",
                    "value": str(broker_resp.error)[:1000],
                    "inline": False,
                })

        embed: dict[str, Any] = {
            "title": title,
            "color": colour,
            "fields": fields,
            "footer": {"text": f"QMIE · {sig.strategy}"},
        }
        # TV chart deep-link (set by dispatcher; pydantic extra="allow")
        chart_url = getattr(sig, "chart_url", None)
        if chart_url:
            embed["url"] = chart_url
            fields.append({
                "name": "Chart",
                "value": f"[Open in TradingView]({chart_url})",
                "inline": False,
            })
        if sig.timestamp:
            embed["timestamp"] = sig.timestamp
        return embed

    # ─── Send ────────────────────────────────────────────────────────────
    async def send_signal(self, sig: TVSignal,
                          broker_resp: BrokerResponse | None = None) -> None:
        embed = self._build_embed(sig, broker_resp)
        body: dict[str, Any] = {
            "username": self.username,
            "embeds": [embed],
        }
        if self.avatar_url:
            body["avatar_url"] = self.avatar_url

        try:
            session = await self._get_session()
            async with session.post(self.webhook_url, json=body) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise NotifierError(
                        f"Discord HTTP {resp.status}: {text[:300]}"
                    )
                # 204 No Content is the success case for webhooks
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            # We never raise — notifier failures are non-fatal.
            logger.error("Discord send failed: %s", e)
        except NotifierError as e:
            logger.error("%s", e)

    async def send_text(self, message: str) -> None:
        """Plain admin message (heartbeat, halt notice, etc)."""
        try:
            session = await self._get_session()
            async with session.post(
                self.webhook_url,
                json={"username": self.username, "content": message[:1900]},
            ) as resp:
                if resp.status >= 400:
                    logger.error("Discord text HTTP %d", resp.status)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error("Discord text failed: %s", e)
