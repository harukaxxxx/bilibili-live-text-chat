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

    def insert(self, index: str, text: str) -> None:
        self.text += text


class FakeEmoticonCombo:
    def __init__(self):
        self.set_values = []

    def set(self, value: str) -> None:
        self.set_values.append(value)

    def configure(self, **kwargs) -> None:
        return None


class FakeChatDisplay:
    def __init__(self):
        self.configure_calls = []
        self.insert_calls = []
        self.delete_calls = []

    def configure(self, **kwargs) -> None:
        self.configure_calls.append(kwargs)

    def insert(self, index: str, text: str, *tags: str) -> None:
        self.insert_calls.append((index, text, tags))

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


def test_empty_count_row_reserves_layout_space():
    assert BiliChatUI.EMPTY_COUNT_PLACEHOLDER == " "


def test_failed_danmaku_is_shown_with_warning_tag():
    ui = BiliChatUI.__new__(BiliChatUI)
    ui.chat_display = FakeChatDisplay()
    ui._line_count = 0

    ui.append_failed_danmaku("這則彈幕沒有送出")

    assert ui.chat_display.insert_calls == [
        (
            "end",
            "[我][發送失敗] 這則彈幕沒有送出\n",
            (BiliChatUI.FAILED_DANMAKU_TAG,),
        )
    ]


def test_selecting_an_emoticon_inserts_its_trigger_text():
    ui = BiliChatUI.__new__(BiliChatUI)
    ui.msg_entry = FakeMessageEntry("")
    ui.emoticon_combo = FakeEmoticonCombo()
    ui._emoticon_map = {
        "<房間表情>": {
            "text": "房間表情",
            "emoji": "房間表情",
            "display": "<房間表情>",
            "unique": "room_123_456",
        }
    }
    ui._selected_emoticon = None
    ui._update_message_state = lambda: None

    ui._on_emoticon_selected("<房間表情>")

    assert ui.msg_entry.text == "<房間表情>"
    assert ui._selected_emoticon["unique"] == "room_123_456"
    assert ui.emoticon_combo.set_values == [BiliChatUI.EMOTICON_PLACEHOLDER]


def test_selected_emoticon_is_sent_by_unique_id():
    ui = BiliChatUI.__new__(BiliChatUI)
    ui._is_connected = True
    ui.msg_entry = FakeMessageEntry("<房間表情>")
    ui._emoticon_map = {
        "<房間表情>": {
            "text": "房間表情",
            "emoji": "房間表情",
            "display": "<房間表情>",
            "unique": "room_123_456",
        }
    }
    ui._selected_emoticon = ui._emoticon_map["<房間表情>"]
    ui.on_send = lambda segments: (_ for _ in ()).throw(AssertionError("sent as text"))
    sent = []
    ui.on_send_emoticon = sent.append
    ui._update_message_state = lambda: None

    ui._on_send_click()

    assert sent == ["room_123_456"]


def test_auto_emoticon_toggle_forwards_selected_unique_id():
    ui = BiliChatUI.__new__(BiliChatUI)
    ui._is_connected = True
    ui._emoticon_map = {
        "<房間表情>": {
            "text": "房間表情",
            "emoji": "房間表情",
            "display": "<房間表情>",
            "unique": "room_123_456",
        }
    }
    ui._auto_emoticon_selection = ui._emoticon_map["<房間表情>"]
    ui._auto_emoticon_enabled = False
    ui.auto_emoticon_btn = FakeEmoticonCombo()
    sent = []
    ui.on_auto_emoticon = lambda enabled, unique: sent.append((enabled, unique))

    ui._toggle_auto_emoticon()

    assert sent == [(True, "room_123_456")]
