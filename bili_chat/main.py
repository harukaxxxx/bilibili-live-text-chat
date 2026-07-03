import re
import threading
from bili_chat.bili_client import BiliClient, save_room, load_rooms
from bili_chat.ui import BiliChatUI


class App:
    def __init__(self):
        self.client = BiliClient()
        self.rooms = load_rooms()
        self.current_url = None
        self.ui = BiliChatUI(
            on_connect=self.on_connect,
            on_send=self.on_send,
            on_disconnect=self.on_disconnect,
            rooms=self.rooms
        )
        self._poll_messages()

    def _get_room_id(self, url: str) -> int:
        match = re.search(r"live\.bilibili\.com/(\d+)", url)
        if not match:
            raise ValueError("請輸入正確的 Bilibili 直播間連結")
        return int(match.group(1))

    def on_connect(self, url: str):
        try:
            room_id = self._get_room_id(url)
        except ValueError as e:
            self.ui.show_error(str(e))
            return
        
        self.current_url = url
        save_room(url)
        self.rooms = load_rooms()
        self.ui.update_rooms(self.rooms, url)
        
        has_credential = self.client.load_credential()
        if has_credential:
            self.ui.append_log("已載入登入憑證")
        else:
            self.ui.append_log("需要登入，將顯示 QR Code")
        
        self.ui.append_log("正在連接...")
        self.client.start_login_and_connect(room_id)

    def on_send(self, msg: str):
        self.client.send_message(msg)

    def on_disconnect(self):
        self.client.disconnect()
        self.ui.append_log("已斷開連接")

    def _poll_messages(self):
        has_update = False
        while not self.client.msg_queue.empty():
            msg_type, *args = self.client.msg_queue.get()
            has_update = True
            
            if msg_type == "danmaku":
                uname, msg = args
                self.ui.append_danmaku(uname, msg)
            elif msg_type == "log":
                text = args[0]
                self.ui.append_log(text)
            elif msg_type == "error":
                text = args[0]
                self.ui.show_error(text)
            elif msg_type == "qr_code":
                path = args[0]
                self.ui.show_qr_code(path)
            elif msg_type == "qr_done":
                success = args[0]
                self.ui.qr_login_done(success)
            elif msg_type == "room_info":
                room_id, room_title, uname = args
                if self.current_url:
                    save_room(self.current_url, uname)
                    self.rooms = load_rooms()
                    self.ui.update_rooms(self.rooms, self.current_url)
        
        if has_update:
            self.ui.scroll_to_end()
        
        if self.client.connected:
            self.ui.set_connected(True)
        
        self.ui.root.after(200, self._poll_messages)


def main():
    app = App()
    app.ui.run()


if __name__ == "__main__":
    main()
