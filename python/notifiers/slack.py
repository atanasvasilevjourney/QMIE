"""
QMIE Slack Notifier
===================
Block Kit cards via the Slack Web API (chat.postMessage) — the current
recommended path. Incoming webhooks remain a fallback (same blocks).

No Slack SDK. aiohttp only, matching Discord/Telegram.

Setup (bot — preferred):
  1. api.slack.com/apps → Create app → Bot Token Scopes: chat:write
  2. Install to workspace, copy Bot User OAuth Token (xoxb-…)
  3. Invite the bot to the channel
  4. SLACK_ENABLED=true SLACK_BOT_TOKEN=xoxb-… SLACK_CHANNEL=C… (or #alerts)

Setup (webhook fallback):
  Incoming Webhooks → Add to channel → SLACK_WEBHOOK_URL=https://hooks.slack.com/…

Failures are logged, never raised. Dispatcher isolation still relies on
asyncio.gather(..., return_exceptions=True).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from .base import Notifier, NotifierError
from .discord import _fmt_price
from models import BrokerResponse, Side, TVSignal

logger = logging.getLogger(__name__)

SLACK_CHAT_POST = "https://slack.com/api/chat.postMessage"

GRADE_EMOJI = {
    "A+": "🟢", "A": "🟩", "B": "🟨", "C": "🟧", "REJECT": "🟥",
}
SIDE_COLOR = {Side.BUY: "#2ECC71", Side.SELL: "#E74C3C"}


def _escape_mrkdwn(text: str) -> str:
    """Slack mrkdwn: &, <, > must be HTML-escaped."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _signal_title(sig: TVSignal) -> str:
    side = sig.side or Side.BUY
    title_action = "BUY SIGNAL" if side is Side.BUY else "SELL SIGNAL"
    setup = getattr(sig, "setup_type", None)
    strat = (sig.strategy or "").lower()
    if setup == "expansion" or "dailyexpansion" in strat:
        title_action = (
            "EXPANSION LONG — SPOT COIL-UP" if side is Side.BUY
            else "EXPANSION SHORT — SPOT COIL-DOWN"
        )
    elif setup == "breakout" or "dailybreakout" in strat:
        title_action = (
            "BREAKOUT LONG — SPOT" if side is Side.BUY
            else "BREAKOUT SHORT — SPOT"
        )
    elif "scanner" in strat:
        title_action = (
            "TEMA BUY — LEVERAGE" if side is Side.BUY
            else "TEMA SELL — LEVERAGE"
        )
    if sig.event.value in ("exit", "close"):
        title_action = "EXIT"
    title = f"{title_action} — {sig.symbol}"
    if sig.timeframe:
        title += f" · {sig.timeframe}"
    return title[:150]


def _field(label: str, value: str) -> dict[str, Any]:
    return {
        "type": "mrkdwn",
        "text": f"*{_escape_mrkdwn(label)}*\n{_escape_mrkdwn(value)}",
    }


class SlackNotifier(Notifier):
    name = "slack"

    def __init__(
        self,
        *,
        bot_token: str = "",
        channel: str = "",
        webhook_url: str = "",
        timeout: float = 5.0,
    ):
        self.bot_token = (bot_token or "").strip()
        self.channel = (channel or "").strip()
        self.webhook_url = (webhook_url or "").strip()
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None
        if not self._uses_bot and not self.webhook_url:
            raise ValueError(
                "SlackNotifier needs SLACK_BOT_TOKEN+SLACK_CHANNEL or SLACK_WEBHOOK_URL"
            )

    @property
    def _uses_bot(self) -> bool:
        return bool(self.bot_token and self.channel)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _build_blocks(
        self,
        sig: TVSignal,
        broker_resp: BrokerResponse | None,
    ) -> list[dict[str, Any]]:
        title = _signal_title(sig)
        ac = sig.asset_class
        fields: list[dict[str, Any]] = []

        fields.append(_field("Price", _fmt_price(sig.signal_price or sig.price, ac)))
        if sig.trend:
            fields.append(_field("Trend", sig.trend.title()))
        if sig.htf:
            fields.append(_field("HTF", sig.htf.title()))
        daily_trend = getattr(sig, "daily_trend", None)
        if daily_trend:
            fields.append(_field("Daily Trend", str(daily_trend).title()))

        alloc_rank = getattr(sig, "alloc_rank", None)
        if alloc_rank is not None:
            w = getattr(sig, "alloc_weight_pct", None)
            cluster = getattr(sig, "alloc_cluster", None) or "—"
            wtxt = f"{w:.1f}%" if w is not None else "—"
            fields.append(_field("Ranked slot", f"#{alloc_rank} · {wtxt} · {cluster}"))
        ns = getattr(sig, "norm_score", None)
        if ns is not None:
            fields.append(_field("ARS score", f"{ns:+.2f}% lookback"))
        regime = getattr(sig, "alloc_regime", None)
        if regime:
            fields.append(_field("ARS regime", str(regime)))

        if sig.reason:
            fields.append(_field("Setup", str(sig.reason).replace("_", " ")))
        if sig.score is not None:
            grade_str = sig.grade.value if sig.grade else "—"
            emoji = GRADE_EMOJI.get(grade_str, "")
            fields.append(
                _field("Confidence", f"{emoji} {grade_str} · {sig.score:.0f}/100")
            )
        if sig.stop_loss is not None:
            fields.append(_field("Stop", _fmt_price(sig.stop_loss, ac)))
        if sig.take_profit is not None:
            fields.append(_field("Target", _fmt_price(sig.take_profit, ac)))
        if sig.adx is not None:
            fields.append(_field("ADX", f"{sig.adx:.1f}"))
        if sig.atr is not None:
            fields.append(_field("ATR", _fmt_price(sig.atr, ac)))
        if sig.session:
            fields.append(_field("Session", sig.session))

        if broker_resp is not None:
            status = broker_resp.status.value
            extra = ""
            if broker_resp.avg_fill_price:
                extra = f" @ {_fmt_price(broker_resp.avg_fill_price, ac)}"
            fields.append(_field(f"Execution ({broker_resp.broker})", f"{status}{extra}"))
            if broker_resp.error:
                fields.append(_field("Error", str(broker_resp.error)[:1000]))

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title, "emoji": True},
            },
        ]
        # Slack section.fields max is 10.
        for i in range(0, len(fields), 10):
            chunk = fields[i:i + 10]
            blocks.append({"type": "section", "fields": chunk})

        chart_url = getattr(sig, "chart_url", None)
        if isinstance(chart_url, str) and chart_url.startswith("http"):
            blocks.append({
                "type": "actions",
                "elements": [{
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Open in TradingView",
                        "emoji": True,
                    },
                    "url": chart_url,
                    "action_id": "qmie_tv_chart",
                }],
            })

        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": _escape_mrkdwn(f"QMIE · {sig.strategy} · signal only, not an order"),
            }],
        })
        return blocks

    def _payload(
        self,
        sig: TVSignal,
        broker_resp: BrokerResponse | None,
    ) -> dict[str, Any]:
        title = _signal_title(sig)
        blocks = self._build_blocks(sig, broker_resp)
        color = SIDE_COLOR.get(sig.side or Side.BUY, "#95A5A6")
        if sig.event.value in ("exit", "close"):
            color = "#95A5A6"
        # Top-level `text` is the push/notification fallback. Block Kit sits
        # in a coloured attachment so long vs short is visible in the channel.
        return {
            "text": title,
            "attachments": [{"color": color, "blocks": blocks}],
            "unfurl_links": False,
            "unfurl_media": False,
        }

    async def send_signal(
        self,
        sig: TVSignal,
        broker_resp: BrokerResponse | None = None,
    ) -> None:
        body = self._payload(sig, broker_resp)
        try:
            await self._post(body)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error("Slack send failed: %s", e)
        except NotifierError as e:
            logger.error("%s", e)

    async def send_text(self, message: str) -> None:
        body: dict[str, Any] = {
            "text": message[:3900],
            "unfurl_links": False,
        }
        try:
            await self._post(body)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error("Slack text failed: %s", e)
        except NotifierError as e:
            logger.error("%s", e)

    async def _post(self, body: dict[str, Any]) -> None:
        session = await self._get_session()
        if self._uses_bot:
            payload = dict(body)
            payload["channel"] = self.channel
            headers = {
                "Authorization": f"Bearer {self.bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            async with session.post(
                SLACK_CHAT_POST, json=payload, headers=headers,
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise NotifierError(f"Slack HTTP {resp.status}: {text[:300]}")
                try:
                    data = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    data = {}
                if isinstance(data, dict) and data.get("ok") is False:
                    raise NotifierError(
                        f"Slack API error: {data.get('error', text[:200])}"
                    )
            return

        async with session.post(self.webhook_url, json=body) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise NotifierError(f"Slack webhook HTTP {resp.status}: {text[:300]}")
