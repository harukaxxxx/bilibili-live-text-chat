import sys
from types import ModuleType, SimpleNamespace

import pytest


if "bilibili_api" not in sys.modules:
    bilibili_api = ModuleType("bilibili_api")
    bilibili_api.Danmaku = object
    bilibili_api.Credential = object
    bilibili_api_live = ModuleType("bilibili_api.live")
    bilibili_api_live.LiveDanmaku = object
    bilibili_api_live.LiveRoom = object
    bilibili_api_login = ModuleType("bilibili_api.login_v2")
    bilibili_api_login.QrCodeLogin = object
    sys.modules.update(
        {
            "bilibili_api": bilibili_api,
            "bilibili_api.live": bilibili_api_live,
            "bilibili_api.login_v2": bilibili_api_login,
        }
    )

from bili_chat.bili_client import BiliClient


@pytest.mark.asyncio
async def test_sends_in_order_and_only_waits_between_messages(monkeypatch):
    client, sent, waits = BiliClient(), [], []

    async def fake_send(text):
        sent.append(text)
        return True

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(client, "_send_danmaku", fake_send)
    monkeypatch.setattr("bili_chat.bili_client.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "bili_chat.bili_client.random",
        SimpleNamespace(uniform=lambda low, high: 2.0),
        raising=False,
    )

    assert await client._send_danmaku_batch(["one", "two", "three"])
    assert sent == ["one", "two", "three"]
    assert waits == [2.0, 2.0]


@pytest.mark.asyncio
async def test_stops_after_a_failed_segment_and_logs_its_index(monkeypatch):
    client, sent, logs = BiliClient(), [], []
    client.msg_queue = SimpleNamespace(put=logs.append)

    async def fake_send(text):
        sent.append(text)
        return text != "fail"

    async def fake_sleep(seconds):
        pass

    monkeypatch.setattr(client, "_send_danmaku", fake_send)
    monkeypatch.setattr("bili_chat.bili_client.asyncio.sleep", fake_sleep)

    assert not await client._send_danmaku_batch(["first", "fail", "never"])
    assert sent == ["first", "fail"]
    assert logs == [("log", "Danmaku batch stopped at message 2 after a send failure.")]


def test_rejects_invalid_segments_before_scheduling(monkeypatch):
    client, logs, scheduled = BiliClient(), [], []
    client._loop = object()
    client.room = object()
    client.msg_queue = SimpleNamespace(put=logs.append)

    def fake_schedule(coroutine, loop):
        scheduled.append(loop)
        coroutine.close()

    monkeypatch.setattr(
        "bili_chat.bili_client.asyncio.run_coroutine_threadsafe", fake_schedule
    )

    client.send_messages(["valid", "x" * 41])

    assert scheduled == []
    assert logs == [("log", "Danmaku batch was not sent because message 2 exceeds 40 characters.")]


def test_schedules_a_valid_batch(monkeypatch):
    client, scheduled = BiliClient(), []
    client._loop = object()
    client.room = object()

    def fake_schedule(coroutine, loop):
        scheduled.append(loop)
        coroutine.close()

    monkeypatch.setattr(
        "bili_chat.bili_client.asyncio.run_coroutine_threadsafe", fake_schedule
    )

    client.send_messages(["valid"])

    assert scheduled == [client._loop]
