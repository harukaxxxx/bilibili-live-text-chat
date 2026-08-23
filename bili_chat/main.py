import re
import threading
from bili_chat.bili_client import (
    BiliClient,
    load_auto_emoticon_preferences,
    load_rooms,
    save_auto_emoticon_preference,
    save_room,
)
from bili_chat.ui import BiliChatUI


class App:
    def __init__(self):
        self.client = BiliClient()
        self.rooms = load_rooms()
        self.auto_emoticon_preferences = load_auto_emoticon_preferences()
        self.current_url = None
        self.current_room_id = None
        self.ui = BiliChatUI(
            on_connect=self.on_connect,
            on_send=self.on_send,
            on_send_emoticon=self.on_send_emoticon,
            on_auto_emoticon=self.on_auto_emoticon,
            on_auto_emoticon_selected=self.on_auto_emoticon_selected,
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
        self.current_room_id = None
        self.ui.update_emoticons([])
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

    def on_send(self, segments: list[str]):
        self.client.send_messages(segments)

    def on_send_emoticon(self, unique: str):
        self.client.send_emoticon(unique)

    def on_auto_emoticon(self, enabled: bool, unique: str = None):
        self.client.configure_auto_emoticon(enabled, unique)

    def on_auto_emoticon_selected(self, unique: str = None):
        if self.current_room_id is None:
            return
        save_auto_emoticon_preference(self.current_room_id, unique)
        room_key = str(self.current_room_id)
        if unique:
            self.auto_emoticon_preferences[room_key] = unique
        else:
            self.auto_emoticon_preferences.pop(room_key, None)

    def on_disconnect(self):
        self.client.disconnect()
        self.current_room_id = None
        self.ui.update_emoticons([])
        self.ui.append_log("已斷開連接")

    def _poll_messages(self):
        has_update = False
        while not self.client.msg_queue.empty():
            msg_type, *args = self.client.msg_queue.get()
            has_update = True
            
            if msg_type == "danmaku":
                uname, msg = args
                self.ui.append_danmaku(uname, msg)
            elif msg_type == "send_failed":
                self.ui.append_failed_danmaku(args[0])
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
                self.current_room_id = room_id
                if self.current_url:
                    save_room(self.current_url, uname)
                    self.rooms = load_rooms()
                    self.ui.update_rooms(self.rooms, self.current_url)
            elif msg_type == "room_emoticons":
                selected_unique = (
                    self.auto_emoticon_preferences.get(str(self.current_room_id))
                    if self.current_room_id is not None
                    else None
                )
                self.ui.update_emoticons(args[0], selected_unique=selected_unique)
        
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
