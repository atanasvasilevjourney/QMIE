"""
QMIE Telegram Notifier
======================
Bot API, MarkdownV2 formatting. Bot token + chat_id only — no
long-polling, no webhook on this side.

Setup:
  1. Create bot via @BotFather → get token
  2. Add bot to your channel/group
  3. Get chat_id (use @userinfobot or call getUpdates)
  4. Set env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

MarkdownV2 escaping is mandatory — Telegram rejects unescaped
specials and silently drops messages with bad formatting.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import aiohttp

from .base import Notifier, NotifierError
from .discord import _fmt_price       # reuse asset-aware price formatter
from models import AssetClass, BrokerResponse, Side, TVSignal

logger = logging.getLogger(__name__)


# Telegram MarkdownV2 reserved characters — every one of these must be
# escaped with a backslash even inside otherwise plain text.
_MD_ESCAPE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def _escape_md(text: str) -> str:
    return _MD_ESCAPE.sub(r"\\\1", str(text))


GRADE_EMOJI = {"A+": "🟢", "A": "🟩", "B": "🟨", "C": "🟧", "REJECT": "🟥"}
SIDE_EMOJI = {Side.BUY: "🟢 BUY", Side.SELL: "🔴 SELL"}


class TelegramNotifier(Notifier):
    name = "telegram"
    API = "https://api.telegram.org"

    def __init__(self, *, bot_token: str, chat_id: str, timeout: float = 5.0):
        self.bot_token = bot_token
        self.chat_id = chat_id
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

    # ─── Message construction ────────────────────────────────────────────
    def _format(self, sig: TVSignal,
                broker_resp: BrokerResponse | None) -> str:
        ac = sig.asset_class
        side_str = SIDE_EMOJI.get(sig.side, "—") if sig.side else "—"
        if sig.event.value in ("exit", "close"):
            side_str = "🟡 EXIT"

        lines: list[str] = []
        lines.append(f"*{_escape_md(side_str)} \\— {_escape_md(sig.symbol)}*")
        if sig.timeframe:
            lines.append(f"_{_escape_md(sig.timeframe)} \\· {_escape_md(sig.strategy)}_")
        lines.append("")  # blank line

        def kv(label: str, value: str) -> str:
            return f"*{_escape_md(label)}:* `{_escape_md(value)}`"

        if sig.signal_price or sig.price:
            lines.append(kv("Price", _fmt_price(sig.signal_price or sig.price, ac)))
        if sig.score is not None:
            grade = sig.grade.value if sig.grade else "—"
            emoji = GRADE_EMOJI.get(grade, "")
            lines.append(kv("Grade", f"{emoji} {grade} · {sig.score:.0f}/100"))
        if sig.trend:
            lines.append(kv("Trend", sig.trend))
        if sig.htf:
            lines.append(kv("HTF", sig.htf))
        if sig.stop_loss is not None:
            lines.append(kv("SL", _fmt_price(sig.stop_loss, ac)))
        if sig.take_profit is not None:
            lines.append(kv("TP", _fmt_price(sig.take_profit, ac)))
        if sig.adx is not None:
            lines.append(kv("ADX", f"{sig.adx:.1f}"))
        if sig.session:
            lines.append(kv("Session", sig.session))

        if broker_resp is not None:
            lines.append("")
            status = broker_resp.status.value
            fill = ""
            if broker_resp.avg_fill_price:
                fill = f" @ {_fmt_price(broker_resp.avg_fill_price, ac)}"
            lines.append(kv(f"{broker_resp.broker.title()}", f"{status}{fill}"))
            if broker_resp.error:
                lines.append(kv("Error", str(broker_resp.error)[:200]))

        # Optional TV chart deep-link (dispatcher sets this; extra="allow")
        chart_url = getattr(sig, "chart_url", None)
        if chart_url:
            lines.append("")
            lines.append(f"[Open in TradingView]({chart_url})")

        return "\n".join(lines)

    # ─── Send ────────────────────────────────────────────────────────────
    async def send_signal(self, sig: TVSignal,
                          broker_resp: BrokerResponse | None = None) -> None:
        text = self._format(sig, broker_resp)
        url = f"{self.API}/bot{self.bot_token}/sendMessage"
        body = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }
        try:
            session = await self._get_session()
            async with session.post(url, json=body) as resp:
                if resp.status >= 400:
                    body_text = await resp.text()
                    logger.error("Telegram HTTP %d: %s", resp.status,
                                 body_text[:300])
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error("Telegram send failed: %s", e)

    async def send_text(self, message: str) -> None:
        url = f"{self.API}/bot{self.bot_token}/sendMessage"
        body = {
            "chat_id": self.chat_id,
            "text": _escape_md(message)[:4000],
            "parse_mode": "MarkdownV2",
        }
        try:
            session = await self._get_session()
            async with session.post(url, json=body) as resp:
                if resp.status >= 400:
                    logger.error("Telegram text HTTP %d", resp.status)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error("Telegram text failed: %s", e)
