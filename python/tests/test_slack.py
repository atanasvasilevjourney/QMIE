"""Slack notifier: Block Kit payload + bot/webhook POST. No real network."""
from __future__ import annotations

import json

import pytest

from config import Settings
from models import AssetClass, EventType, Side, TVSignal
from notifiers.slack import SLACK_CHAT_POST, SlackNotifier, _escape_mrkdwn, _signal_title


def _sig(**extra) -> TVSignal:
    fields = dict(
        strategy="QMIE-Scanner",
        event=EventType.ENTRY,
        symbol="BTCUSDT",
        asset_class=AssetClass.CRYPTO,
        timeframe="4h",
        side=Side.BUY,
        signal_price=65000.0,
        score=85.0,
    )
    fields.update(extra)
    return TVSignal(**fields)


class _FakeResp:
    def __init__(self, status: int = 200, body: str = '{"ok":true}'):
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeSession:
    def __init__(self, resp: _FakeResp | None = None):
        self.posts: list[dict] = []
        self._resp = resp or _FakeResp()

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return self._resp


def _install_session(n: SlackNotifier, session: _FakeSession) -> None:
    async def _get():
        return session
    n._get_session = _get  # type: ignore[method-assign]


def test_requires_bot_or_webhook():
    with pytest.raises(ValueError, match="SLACK_"):
        SlackNotifier()


def test_escape_mrkdwn():
    assert _escape_mrkdwn("A & B <C> D") == "A &amp; B &lt;C&gt; D"


def test_tema_buy_title():
    assert "TEMA BUY — LEVERAGE" in _signal_title(_sig())


def test_payload_color_buy_vs_sell():
    n = SlackNotifier(webhook_url="https://hooks.slack.com/services/x/y/z")
    buy = n._payload(_sig(side=Side.BUY), None)
    sell = n._payload(_sig(side=Side.SELL), None)
    assert buy["attachments"][0]["color"] == "#2ECC71"
    assert sell["attachments"][0]["color"] == "#E74C3C"
    assert buy["attachments"][0]["blocks"][0]["type"] == "header"


@pytest.mark.asyncio
async def test_bot_posts_chat_post_message():
    n = SlackNotifier(bot_token="xoxb-test", channel="C123")
    session = _FakeSession()
    _install_session(n, session)
    await n.send_signal(_sig(alloc_rank=1, alloc_weight_pct=25.0, alloc_cluster="BTC"))
    assert len(session.posts) == 1
    post = session.posts[0]
    assert post["url"] == SLACK_CHAT_POST
    assert post["headers"]["Authorization"] == "Bearer xoxb-test"
    body = post["json"]
    assert body["channel"] == "C123"
    assert "TEMA BUY" in body["text"]
    blobs = json.dumps(body)
    assert "Ranked slot" in blobs
    assert "#1" in blobs
    assert "xoxb-test" not in blobs  # token stays in header only


@pytest.mark.asyncio
async def test_webhook_posts_incoming_url_not_api():
    url = "https://hooks.slack.com/services/T/B/xxx"
    n = SlackNotifier(webhook_url=url)
    session = _FakeSession()
    _install_session(n, session)
    await n.send_signal(_sig())
    post = session.posts[0]
    assert post["url"] == url
    assert "headers" not in post
    assert "channel" not in post["json"]


@pytest.mark.asyncio
async def test_prefers_bot_when_both_configured():
    n = SlackNotifier(
        bot_token="xoxb-test",
        channel="#qmie",
        webhook_url="https://hooks.slack.com/services/T/B/xxx",
    )
    session = _FakeSession()
    _install_session(n, session)
    await n.send_signal(_sig())
    assert session.posts[0]["url"] == SLACK_CHAT_POST
    assert session.posts[0]["json"]["channel"] == "#qmie"


@pytest.mark.asyncio
async def test_http_error_does_not_raise():
    n = SlackNotifier(bot_token="xoxb-test", channel="C123")
    session = _FakeSession(_FakeResp(status=500, body="nope"))
    _install_session(n, session)
    await n.send_signal(_sig())  # must not raise


@pytest.mark.asyncio
async def test_api_ok_false_does_not_raise():
    n = SlackNotifier(bot_token="xoxb-test", channel="C123")
    session = _FakeSession(
        _FakeResp(status=200, body='{"ok":false,"error":"channel_not_found"}'),
    )
    _install_session(n, session)
    await n.send_signal(_sig())


@pytest.mark.asyncio
async def test_send_text_uses_same_path():
    n = SlackNotifier(webhook_url="https://hooks.slack.com/services/T/B/xxx")
    session = _FakeSession()
    _install_session(n, session)
    await n.send_text("halt: exchange 451")
    assert session.posts[0]["json"]["text"] == "halt: exchange 451"


class TestSlackSettings:
    def test_disabled_by_default(self):
        s = Settings(webhook_secret="x")
        assert s.slack_enabled is False
        assert s.slack_configured is False

    def test_bot_path_configures(self):
        s = Settings(
            webhook_secret="x",
            slack_enabled=True,
            slack_bot_token="xoxb-a",
            slack_channel="C1",
        )
        assert s.slack_configured is True

    def test_webhook_path_configures(self):
        s = Settings(
            webhook_secret="x",
            slack_enabled=True,
            slack_webhook_url="https://hooks.slack.com/services/x",
        )
        assert s.slack_configured is True

    def test_enabled_without_creds_warns(self):
        s = Settings(webhook_secret="x", slack_enabled=True)
        warnings = s.validate_runtime()
        assert any("SLACK_ENABLED" in w for w in warnings)
        assert s.slack_configured is False
