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
