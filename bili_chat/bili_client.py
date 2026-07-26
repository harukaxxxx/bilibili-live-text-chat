import asyncio
import json
import os
import random
import tempfile
import threading
from queue import Queue
from typing import Callable, Optional
from bilibili_api.live import LiveDanmaku, LiveRoom
from bilibili_api.login_v2 import QrCodeLogin
from bilibili_api import Danmaku, Credential
from bili_chat.message_segments import validate_segments


CREDENTIAL_FILE = "credential.json"
ROOMS_FILE = "rooms.json"
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


class BiliClient:
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
        self._has_sent_danmaku = False
        self._last_send_was_rate_limited = False

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
        
        self.danmaku = LiveDanmaku(room_display_id=real_room_id, credential=self.credential)

        @self.danmaku.on("DANMU_MSG")
        async def on_danmaku(event):
            info = event['data']['info']
            uname = info[2][1]
            msg = info[1]
            self.msg_queue.put(("danmaku", uname, msg))

        self.msg_queue.put(("room_info", real_room_id, room_title, uname))
        self.msg_queue.put(("log", f"已連接: {uname} - {room_title}"))
        self.connected = True
        
        await self.danmaku.connect()
        return real_room_id

    async def _send_danmaku(self, text: str) -> bool:
        if self.room is None or self.credential is None:
            return False
        self._last_send_was_rate_limited = False
        try:
            danmaku = Danmaku(text=text)
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
            if self._has_sent_danmaku:
                await asyncio.sleep(random.uniform(5.0, 8.0))
            if not await self._send_danmaku(segment):
                if self._last_send_was_rate_limited:
                    self.msg_queue.put(("log", "發送過快，等待後重試一次..."))
                    await asyncio.sleep(random.uniform(15.0, 20.0))
                    if await self._send_danmaku(segment):
                        self._has_sent_danmaku = True
                        continue
                self.msg_queue.put(
                    ("log", f"Danmaku batch stopped at message {index} after a send failure.")
                )
                return False
            self._has_sent_danmaku = True
        return True

    async def _enqueue_danmaku_batch(self, segments: list[str]) -> None:
        loop = asyncio.get_running_loop()
        if self._batch_loop is not loop:
            self._batch_queue = asyncio.Queue()
            self._batch_worker = None
            self._batch_loop = loop
            self._has_sent_danmaku = False
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
        self._batch_queue = None
        self._batch_worker = None
        self._batch_loop = None
        self._has_sent_danmaku = False

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
