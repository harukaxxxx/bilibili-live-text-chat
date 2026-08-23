import asyncio
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

from bili_chat.bili_client import BiliClient, parse_room_emoticons


def test_parse_room_emoticons_keeps_sendable_room_emoticons_only():
    payload = {
        "code": 0,
        "data": {
            "data": [
                {
                    "emoticons": [
                        {
                            "emoji": "官方表情",
                            "emoticon_unique": "official_1",
                            "perm": 1,
                        },
                        {
                            "emoji": "房間表情",
                            "emoticon_unique": "room_123_456",
                            "perm": 1,
                            "url": "https://example.com/emote.png",
                        },
                        {
                            "emoji": "鎖定表情",
                            "emoticon_unique": "room_123_789",
                            "perm": 0,
                        },
                        {
                            "emoji": "房間表情",
                            "emoticon_unique": "room_123_999",
                            "perm": 1,
                        },
                    ]
                }
            ]
        },
    }

    assert parse_room_emoticons(payload) == [
        {
            "text": "房間表情",
            "emoji": "房間表情",
            "display": "<房間表情>",
            "unique": "room_123_456",
            "url": "https://example.com/emote.png",
        }
    ]


@pytest.mark.asyncio
async def test_room_emoticon_request_uses_browser_headers(monkeypatch):
    request = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0, "data": {"data": []}}

    class FakeClient:
        def __init__(self, **kwargs):
            request["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, **kwargs):
            request["url"] = url
            request.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr("bili_chat.bili_client.httpx.AsyncClient", FakeClient)

    client = BiliClient()
    client.credential = SimpleNamespace(get_cookies=lambda: {"SESSDATA": "secret"})

    assert await client._get_room_emoticons(10971399) == []
    assert request["headers"]["User-Agent"].startswith("Mozilla/")
    assert request["headers"]["Referer"] == "https://live.bilibili.com/10971399"
    assert request["headers"]["Origin"] == "https://live.bilibili.com"


@pytest.mark.asyncio
async def test_send_room_emoticon_uses_emoticon_payload(monkeypatch):
    request = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0, "data": {}}

    class FakeClient:
        def __init__(self, **kwargs):
            request["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, **kwargs):
            request["url"] = url
            request.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr("bili_chat.bili_client.httpx.AsyncClient", FakeClient)

    client = BiliClient()
    client.room = object()
    client._real_room_id = 10971399
    client.credential = SimpleNamespace(
        get_cookies=lambda: {"bili_jct": "csrf", "SESSDATA": "session"}
    )

    result = await client._send_emoticon("room_10971399_123")
    assert result, client.msg_queue.get_nowait()
    assert request["data"]["msg"] == "room_10971399_123"
    assert request["data"]["dm_type"] == "1"
    assert request["data"]["emoticon_options"] == "{}"


@pytest.mark.asyncio
async def test_send_danmaku_converts_traditional_chinese_before_sending(monkeypatch):
    sent = []

    class FakeDanmaku:
        def __init__(self, *, text):
            self.text = text

    async def fake_send_danmaku(danmaku):
        sent.append(danmaku.text)

    client = BiliClient()
    client.room = SimpleNamespace(send_danmaku=fake_send_danmaku)
    client.credential = object()
    monkeypatch.setattr("bili_chat.bili_client.Danmaku", FakeDanmaku)

    assert await client._send_danmaku("繁體中文、電腦與網路")
    assert sent == ["繁体中文、电脑与网络"]


@pytest.mark.asyncio
async def test_auto_gift_response_deduplicates_each_user_for_thirty_seconds(monkeypatch):
    client = BiliClient()
    client._auto_emoticon_enabled = True
    client._auto_emoticon_unique = "room_10971399_123"
    sent = []

    async def fake_send(unique):
        sent.append(unique)
        return True

    monkeypatch.setattr(client, "_send_emoticon", fake_send)
    now = iter([100.0, 110.0, 161.0])
    client._monotonic = lambda: next(now)

    gift = {"uid": 42, "uname": "viewer", "coin_type": "gold", "total_coin": 1100}
    await client._handle_auto_gift_response(gift)
    await client._handle_auto_gift_response(gift)
    await client._handle_auto_gift_response(gift)

    assert sent == ["room_10971399_123", "room_10971399_123"]


@pytest.mark.asyncio
async def test_auto_gift_response_ignores_the_logged_in_user(monkeypatch):
    client = BiliClient()
    client.credential = SimpleNamespace(dedeuserid="42")
    client._auto_emoticon_enabled = True
    client._auto_emoticon_unique = "room_10971399_123"
    sent = []

    async def fake_send(unique):
        sent.append(unique)
        return True

    monkeypatch.setattr(client, "_send_emoticon", fake_send)

    await client._handle_auto_gift_response(
        {"uid": 42, "uname": "me", "coin_type": "gold", "total_coin": 1100}
    )

    assert sent == []
    assert client._gift_response_times == {}


@pytest.mark.asyncio
async def test_auto_gift_response_requires_more_than_ten_batteries(monkeypatch):
    client = BiliClient()
    client._auto_emoticon_enabled = True
    client._auto_emoticon_unique = "room_10971399_123"
    sent = []

    async def fake_send(unique):
        sent.append(unique)
        return True

    monkeypatch.setattr(client, "_send_emoticon", fake_send)

    await client._handle_auto_gift_response(
        {"uid": 42, "coin_type": "gold", "total_coin": 1000}
    )
    await client._handle_auto_gift_response(
        {"uid": 43, "coin_type": "gold", "total_coin": 1001}
    )

    assert sent == ["room_10971399_123"]


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
    assert logs == [
        ("send_failed", "fail"),
        ("log", "Danmaku batch stopped at message 2 after a send failure."),
    ]


@pytest.mark.asyncio
async def test_retries_a_rate_limited_message_once_after_a_longer_cooldown(monkeypatch):
    client, attempts, waits = BiliClient(), [], []

    async def fake_send(text):
        attempts.append(text)
        client._last_send_was_rate_limited = len(attempts) == 1
        return len(attempts) == 2

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(client, "_send_danmaku", fake_send)
    monkeypatch.setattr("bili_chat.bili_client.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "bili_chat.bili_client.random.uniform",
        lambda low, high: 16.0,
    )

    assert await client._send_danmaku_batch(["retry me"])
    assert attempts == ["retry me", "retry me"]
    assert waits == [16.0]


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


@pytest.mark.asyncio
async def test_serializes_rapid_batches_without_a_delay_at_batch_boundaries(monkeypatch):
    client, sent, waits = BiliClient(), [], []
    client._loop = asyncio.get_running_loop()
    client.room = object()
    finished = asyncio.Event()
    original_sleep = asyncio.sleep

    async def fake_send(text):
        sent.append(text)
        if len(sent) == 4:
            finished.set()
        return True

    async def fake_sleep(seconds):
        waits.append(seconds)
        await original_sleep(0)

    monkeypatch.setattr(client, "_send_danmaku", fake_send)
    monkeypatch.setattr("bili_chat.bili_client.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("bili_chat.bili_client.random.uniform", lambda low, high: 2.0)

    client.send_messages(["one", "two"])
    client.send_messages(["three", "four"])

    await asyncio.wait_for(finished.wait(), timeout=1)

    assert sent == ["one", "two", "three", "four"]
    assert waits == [2.0, 2.0]


def test_disconnect_reconnect_discards_old_batch_worker_and_creates_a_fresh_one(
    monkeypatch,
):
    client, sent = BiliClient(), []
    old_loop = asyncio.new_event_loop()
    new_loop = asyncio.new_event_loop()
    old_worker = old_loop.create_task(asyncio.sleep(10))
    client._loop = old_loop
    client.room = object()
    client._batch_loop = old_loop
    client._batch_queue = asyncio.Queue()
    client._batch_worker = old_worker

    async def fake_send(text):
        sent.append(text)
        return True

    monkeypatch.setattr(client, "_send_danmaku", fake_send)

    try:
        client.disconnect()
        old_loop.run_forever()
        old_loop.call_soon(old_loop.stop)
        old_loop.run_forever()

        assert old_worker.cancelled()
        assert client._batch_queue is None
        assert client._batch_worker is None

        client._loop = new_loop
        client.room = object()
        client.send_messages(["new"])
        new_loop.run_until_complete(asyncio.sleep(0))
        new_loop.run_until_complete(asyncio.sleep(0))

        assert sent == ["new"]
        assert client._batch_loop is new_loop
        assert client._batch_worker is not old_worker
    finally:
        for loop, worker in ((old_loop, old_worker), (new_loop, client._batch_worker)):
            if worker is not None and not worker.done():
                worker.cancel()
                loop.call_soon(loop.stop)
                loop.run_forever()
            loop.close()
