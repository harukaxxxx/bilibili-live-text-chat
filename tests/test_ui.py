import sys
from types import ModuleType, SimpleNamespace


sys.modules.setdefault("customtkinter", SimpleNamespace(CTkToplevel=object))
pil = ModuleType("PIL")
pil.Image = object
pil.ImageTk = object
sys.modules.setdefault("PIL", pil)

from bili_chat.ui import BiliChatUI


class FakeMessageEntry:
    def __init__(self, text: str):
        self.text = text
        self.delete_calls = []

    def get(self, start: str, end: str) -> str:
        return self.text

    def delete(self, start: str, end: str) -> None:
        self.delete_calls.append((start, end))


def test_disconnected_send_does_not_forward_a_valid_batch():
    ui = BiliChatUI.__new__(BiliChatUI)
    ui._is_connected = False
    ui.msg_entry = FakeMessageEntry("valid message")
    forwarded = []
    ui.on_send = forwarded.append
    ui._update_message_state = lambda: None

    ui._on_send_click()

    assert forwarded == []
    assert ui.msg_entry.delete_calls == []
