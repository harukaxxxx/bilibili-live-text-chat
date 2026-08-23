import asyncio
import json
import os
import random
import tempfile
import threading
import time
from queue import Queue
from typing import Callable, Optional

import httpx
from bilibili_api.live import LiveDanmaku, LiveRoom
from bilibili_api.login_v2 import QrCodeLogin
from bilibili_api import Danmaku, Credential
from bili_chat.message_segments import validate_segments
from bili_chat.text_conversion import to_simplified


CREDENTIAL_FILE = "credential.json"
ROOMS_FILE = "rooms.json"
AUTO_EMOTICONS_FILE = "auto_emoticons.json"
_rooms_file_lock = threading.Lock()


def save_room(url: str, name: str = None):
    with _rooms_file_lock:
        rooms = load_rooms()
        for room in rooms:
            if room["url"] == url:
                if name:
                    room["name"] = name
                break
        else:
            rooms.append({"url": url, "name": name or url})
        fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(ROOMS_FILE)), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(rooms, f, ensure_ascii=False, indent=2)
            if os.path.exists(ROOMS_FILE):
                os.replace(temp_path, ROOMS_FILE)
            else:
                os.rename(temp_path, ROOMS_FILE)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise


def load_rooms() -> list:
    if not os.path.exists(ROOMS_FILE):
        return []
    try:
        with open(ROOMS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def load_auto_emoticon_preferences() -> dict[str, str]:
    if not os.path.exists(AUTO_EMOTICONS_FILE):
        return {}
    try:
        with open(AUTO_EMOTICONS_FILE, "r", encoding="utf-8") as f:
            preferences = json.load(f)
        if not isinstance(preferences, dict):
            return {}
        return {
            str(room_id): str(unique)
            for room_id, unique in preferences.items()
            if unique
        }
    except Exception:
        return {}


def save_auto_emoticon_preference(room_id: int, unique: Optional[str]) -> None:
    with _rooms_file_lock:
        preferences = load_auto_emoticon_preferences()
        room_key = str(room_id)
        if unique:
            preferences[room_key] = unique
        else:
            preferences.pop(room_key, None)

        fd, temp_path = tempfile.mkstemp(
            dir=os.path.dirname(os.path.abspath(AUTO_EMOTICONS_FILE)),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(preferences, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, AUTO_EMOTICONS_FILE)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise


def parse_room_emoticons(payload: dict) -> list[dict]:
    """Extract sendable room-only emoticons from the live API response."""
    result = []
    seen_triggers = set()
    packages = ((payload.get("data") or {}).get("data") or [])

    for package in packages:
        for emoticon in package.get("emoticons") or []:
            trigger = str(emoticon.get("emoji") or "").strip()
            unique = str(emoticon.get("emoticon_unique") or "")
            permission = emoticon.get("perm", 1)

            if not trigger or not unique.startswith("room_"):
                continue
            if permission not in (1, "1", True) or trigger in seen_triggers:
                continue

            seen_triggers.add(trigger)
            result.append(
                {
                    "text": trigger,
                    "emoji": trigger,
                    "display": f"<{trigger}>",
                    "unique": unique,
                    "url": emoticon.get("url", ""),
                }
            )

    return result


def _browser_headers(room_id: int) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://live.bilibili.com/{room_id}",
        "Origin": "https://live.bilibili.com",
        "Accept": "application/json, text/plain, */*",
    }


class BiliClient:
    AUTO_GIFT_MIN_BATTERIES = 10.0
    GENERAL_GIFT_RESPONSE_COOLDOWN = 60.0
    GUARD_RESPONSE_COOLDOWN = 30.0

    def __init__(self):
        self.credential: Optional[Credential] = None
        self.room: Optional[LiveRoom] = None
        self.danmaku: Optional[LiveDanmaku] = None
        self.msg_queue: Queue = Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread = None
        self.connected = False
        self._batch_queue: Optional[asyncio.Queue[list[str]]] = None
        self._batch_worker: Optional[asyncio.Task[None]] = None
        self._batch_loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_send_was_rate_limited = False
        self._real_room_id: Optional[int] = None
        self._auto_emoticon_enabled = False
        self._auto_emoticon_unique: Optional[str] = None
        self._gift_response_times: dict[int, float] = {}

    def save_credential(self):
        if self.credential is None:
            return
        cookies = self.credential.get_cookies()
        with open(CREDENTIAL_FILE, 'w') as f:
            json.dump(cookies, f)

    def load_credential(self) -> bool:
        if not os.path.exists(CREDENTIAL_FILE):
            return False
        try:
            with open(CREDENTIAL_FILE, 'r') as f:
                cookies = json.load(f)
            self.credential = Credential(
                sessdata=cookies.get('SESSDATA'),
                bili_jct=cookies.get('bili_jct'),
                buvid3=cookies.get('buvid3'),
                dedeuserid=cookies.get('DedeUserID')
            )
            return True
        except Exception:
            return False

    async def _verify_credential(self) -> bool:
        """驗證憑證是否有效"""
        if self.credential is None:
            return False
        try:
            from bilibili_api import user
            u = user.User(uid=int(self.credential.dedeuserid), credential=self.credential)
            await u.get_user_info()
            return True
        except Exception:
            return False

    async def _qr_login(self) -> bool:
        from bilibili_api.login_v2 import QrCodeLoginEvents
        
        qr_login = QrCodeLogin()
        await qr_login.generate_qrcode()
        
        qr_path = "qrcode.png"
        qr_login.get_qrcode_picture().to_file(qr_path)
        
        self.msg_queue.put(("qr_code", qr_path))

        while True:
            state = await qr_login.check_state()
            
            if state == QrCodeLoginEvents.DONE:
                self.credential = qr_login.get_credential()
                self.save_credential()
                self.msg_queue.put(("qr_done", True))
                if os.path.exists(qr_path):
                    os.remove(qr_path)
                self.msg_queue.put(("log", "登入成功！"))
                return True
            elif state == QrCodeLoginEvents.TIMEOUT:
                self.msg_queue.put(("qr_done", False))
                if os.path.exists(qr_path):
                    os.remove(qr_path)
                return False
            
            await asyncio.sleep(1)

    async def _connect_room(self, room_id: int):
        self.room = LiveRoom(room_display_id=room_id, credential=self.credential)
        room_info = await self.room.get_room_info()
        real_room_id = room_info['room_info']['room_id']
        room_title = room_info['room_info']['title']
        uname = room_info['anchor_info']['base_info']['uname']
        self._real_room_id = real_room_id
        room_emoticons = await self._get_room_emoticons(real_room_id)
        
        self.danmaku = LiveDanmaku(room_display_id=real_room_id, credential=self.credential)

        @self.danmaku.on("DANMU_MSG")
        async def on_danmaku(event):
            info = event['data']['info']
            uname = info[2][1]
            msg = info[1]
            self.msg_queue.put(("danmaku", uname, msg))

        @self.danmaku.on("SEND_GIFT")
        async def on_gift(event):
            data = ((event.get("data") or {}).get("data") or {})
            await self._handle_auto_gift_response(
                data, self.GENERAL_GIFT_RESPONSE_COOLDOWN
            )

        @self.danmaku.on("GUARD_BUY")
        async def on_guard_buy(event):
            data = ((event.get("data") or {}).get("data") or {})
            await self._handle_auto_gift_response(data, self.GUARD_RESPONSE_COOLDOWN)

        self.msg_queue.put(("room_info", real_room_id, room_title, uname))
        self.msg_queue.put(("room_emoticons", room_emoticons))
        self.msg_queue.put(("log", f"已連接: {uname} - {room_title}"))
        self.connected = True
        
        await self.danmaku.connect()
        return real_room_id

    async def _get_room_emoticons(self, room_id: int) -> list[dict]:
        if self.credential is None:
            return []

        url = "https://api.live.bilibili.com/xlive/web-ucenter/v2/emoticon/GetEmoticons"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    params={"platform": "pc", "room_id": room_id},
                    headers=_browser_headers(room_id),
                    cookies=self.credential.get_cookies(),
                )
                response.raise_for_status()
                payload = response.json()

            if payload.get("code") != 0:
                raise RuntimeError(payload.get("message") or "Bilibili API 回傳錯誤")
            return parse_room_emoticons(payload)
        except Exception as e:
            self.msg_queue.put(("log", f"房間表情載入失敗: {e}"))
            return []

    async def _send_emoticon(self, unique: str) -> bool:
        if self.room is None or self.credential is None or self._real_room_id is None:
            return False

        cookies = self.credential.get_cookies()
        csrf = cookies.get("bili_jct")
        if not csrf:
            self.msg_queue.put(("log", "發送表情失敗: 缺少 CSRF 憑證"))
            return False

        data = {
            "bubble": "0",
            "msg": unique,
            "color": "16777215",
            "mode": "1",
            "dm_type": "1",
            "emoticon_options": "{}",
            "fontsize": "25",
            "rnd": str(int(time.time())),
            "roomid": str(self._real_room_id),
            "csrf": csrf,
            "csrf_token": csrf,
        }
        url = "https://api.live.bilibili.com/msg/send"
        self._last_send_was_rate_limited = False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    data=data,
                    headers=_browser_headers(self._real_room_id),
                    cookies=cookies,
                )
                response.raise_for_status()
                payload = response.json()

            if payload.get("code") != 0:
                raise RuntimeError(payload.get("message") or "Bilibili API 回傳錯誤")
            return True
        except Exception as e:
            self._last_send_was_rate_limited = (
                getattr(e, "code", None) == 10031 or "10031" in str(e)
            )
            self.msg_queue.put(("log", f"發送表情失敗: {e}"))
            return False

    def _monotonic(self) -> float:
        return time.monotonic()

    def _current_user_uid(self) -> Optional[int]:
        if self.credential is None:
            return None

        raw_uid = getattr(self.credential, "dedeuserid", None)
        if raw_uid is None:
            try:
                raw_uid = self.credential.get_cookies().get("DedeUserID")
            except Exception:
                return None

        try:
            return int(raw_uid)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _gift_batteries(data: dict) -> float:
        if str(data.get("coin_type") or "gold").lower() != "gold":
            return 0.0

        raw_total = data.get("total_coin")
        if raw_total is None:
            raw_total = data.get("combo_total_coin")
        if raw_total is None:
            try:
                price = float(data.get("price") or data.get("gift_price") or 0)
                quantity = float(
                    data.get("num") or data.get("gift_num") or data.get("combo_num") or 1
                )
                raw_total = price * quantity
            except (TypeError, ValueError):
                return 0.0

        try:
            return float(raw_total) / 100
        except (TypeError, ValueError):
            return 0.0

    async def _handle_auto_gift_response(
        self, data: dict, response_cooldown: float = GENERAL_GIFT_RESPONSE_COOLDOWN
    ) -> None:
        if not self._auto_emoticon_enabled or not self._auto_emoticon_unique:
            return

        raw_uid = data.get("uid") or data.get("sender_uid")
        try:
            uid = int(raw_uid)
        except (TypeError, ValueError):
            return

        if self._current_user_uid() == uid:
            return

        if self._gift_batteries(data) <= self.AUTO_GIFT_MIN_BATTERIES:
            return

        now = self._monotonic()
        last_sent = self._gift_response_times.get(uid)
        if last_sent is not None and now - last_sent < response_cooldown:
            return

        unique = self._auto_emoticon_unique
        self._gift_response_times[uid] = now
        if await self._send_emoticon(unique):
            uname = data.get("uname") or data.get("username") or str(uid)
            self.msg_queue.put(("log", f"已自動回應 {uname} 的投餵"))
        else:
            self._gift_response_times.pop(uid, None)

    async def _send_danmaku(self, text: str) -> bool:
        if self.room is None or self.credential is None:
            return False
        self._last_send_was_rate_limited = False
        try:
            danmaku = Danmaku(text=to_simplified(text))
            await self.room.send_danmaku(danmaku)
            return True
        except Exception as e:
            self._last_send_was_rate_limited = (
                getattr(e, "code", None) == 10031 or "10031" in str(e)
            )
            self.msg_queue.put(("log", f"發送失敗: {e}"))
            return False

    async def _send_danmaku_batch(self, segments: list[str]) -> bool:
        for index, segment in enumerate(segments, start=1):
            if index > 1:
                await asyncio.sleep(random.uniform(5.0, 8.0))
            if not await self._send_danmaku(segment):
                if self._last_send_was_rate_limited:
                    self.msg_queue.put(("log", "發送過快，等待後重試一次..."))
                    await asyncio.sleep(random.uniform(15.0, 20.0))
                    if await self._send_danmaku(segment):
                        continue
                self.msg_queue.put(("send_failed", segment))
                self.msg_queue.put(
                    ("log", f"Danmaku batch stopped at message {index} after a send failure.")
                )
                return False
        return True

    async def _enqueue_danmaku_batch(self, segments: list[str]) -> None:
        loop = asyncio.get_running_loop()
        if self._batch_loop is not loop:
            self._batch_queue = asyncio.Queue()
            self._batch_worker = None
            self._batch_loop = loop
        assert self._batch_queue is not None
        await self._batch_queue.put(segments)
        if self._batch_worker is None or self._batch_worker.done():
            self._batch_worker = asyncio.create_task(
                self._send_queued_danmaku_batches(self._batch_queue)
            )

    async def _send_queued_danmaku_batches(
        self, queue: asyncio.Queue[list[str]]
    ) -> None:
        while True:
            segments = await queue.get()
            try:
                await self._send_danmaku_batch(segments)
            finally:
                queue.task_done()

    def start_login_and_connect(self, room_id: int):
        import threading
        
        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            async def _task():
                if self.credential is None:
                    # 沒有憑證，需要登入
                    success = await self._qr_login()
                    if not success:
                        self.msg_queue.put(("error", "登入失敗"))
                        return
                else:
                    # 有憑證，先驗證
                    self.msg_queue.put(("log", "正在驗證登入憑證..."))
                    is_valid = await self._verify_credential()
                    if not is_valid:
                        self.msg_queue.put(("log", "憑證已失效，需要重新登入"))
                        self.credential = None
                        if os.path.exists(CREDENTIAL_FILE):
                            os.remove(CREDENTIAL_FILE)
                        success = await self._qr_login()
                        if not success:
                            self.msg_queue.put(("error", "登入失敗"))
                            return
                    else:
                        self.msg_queue.put(("log", "憑證驗證成功"))
                
                try:
                    await self._connect_room(room_id)
                except Exception as e:
                    self.msg_queue.put(("error", f"連接失敗: {e}"))
            
            self._loop.run_until_complete(_task())
            self._loop.run_forever()
        
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def send_message(self, text: str):
        if self._loop is None or self.room is None:
            self.msg_queue.put(("log", "尚未連接聊天室"))
            return
        
        asyncio.run_coroutine_threadsafe(self._send_danmaku(text), self._loop)

    def send_emoticon(self, unique: str):
        if self._loop is None or self.room is None:
            self.msg_queue.put(("log", "尚未連接聊天室"))
            return

        asyncio.run_coroutine_threadsafe(self._send_emoticon(unique), self._loop)

    def configure_auto_emoticon(self, enabled: bool, unique: Optional[str]):
        self._auto_emoticon_enabled = bool(enabled and unique)
        self._auto_emoticon_unique = unique if self._auto_emoticon_enabled else None
        self._gift_response_times.clear()

    def send_messages(self, segments: list[str]):
        is_valid, invalid_index = validate_segments(segments)
        if not is_valid:
            self.msg_queue.put(
                (
                    "log",
                    f"Danmaku batch was not sent because message {invalid_index} exceeds 40 characters.",
                )
            )
            return

        if self._loop is None or self.room is None:
            self.msg_queue.put(("log", "Cannot send messages before connecting to a room."))
            return

        asyncio.run_coroutine_threadsafe(self._enqueue_danmaku_batch(segments), self._loop)

    def disconnect(self):
        loop = self._loop
        worker = self._batch_worker
        queue = self._batch_queue

        self.room = None
        self.danmaku = None
        self.connected = False
        self._real_room_id = None
        self.configure_auto_emoticon(False, None)
        self._batch_queue = None
        self._batch_worker = None
        self._batch_loop = None

        def cancel_stale_batches():
            if worker is not None and not worker.done():
                worker.cancel()
            if queue is not None:
                while not queue.empty():
                    queue.get_nowait()
                    queue.task_done()

        if loop is not None:
            loop.call_soon_threadsafe(cancel_stale_batches)
            loop.call_soon_threadsafe(loop.stop)
