import asyncio
import json
import os
from queue import Queue
from typing import Callable, Optional
from bilibili_api.live import LiveDanmaku, LiveRoom
from bilibili_api.login_v2 import QrCodeLogin
from bilibili_api import Danmaku, Credential


CREDENTIAL_FILE = "credential.json"


class BiliClient:
    def __init__(self):
        self.credential: Optional[Credential] = None
        self.room: Optional[LiveRoom] = None
        self.danmaku: Optional[LiveDanmaku] = None
        self.msg_queue: Queue = Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread = None
        self.connected = False

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
        
        self.danmaku = LiveDanmaku(room_display_id=real_room_id, credential=self.credential)

        @self.danmaku.on("DANMU_MSG")
        async def on_danmaku(event):
            info = event['data']['info']
            uname = info[2][1]
            msg = info[1]
            self.msg_queue.put(("danmaku", uname, msg))

        await self.danmaku.connect()
        self.connected = True
        self.msg_queue.put(("log", f"已連接房間 ID: {real_room_id}"))
        return real_room_id

    async def _send_danmaku(self, text: str) -> bool:
        if self.room is None or self.credential is None:
            return False
        try:
            danmaku = Danmaku(text=text)
            await self.room.send_danmaku(danmaku)
            return True
        except Exception as e:
            self.msg_queue.put(("log", f"發送失敗: {e}"))
            return False

    def start_login_and_connect(self, room_id: int):
        import threading
        
        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            async def _task():
                if self.credential is None:
                    success = await self._qr_login()
                    if not success:
                        self.msg_queue.put(("error", "登入失敗"))
                        return
                else:
                    self.msg_queue.put(("log", "已載入登入憑證"))
                
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

    def disconnect(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.connected = False
