import customtkinter as ctk
import re
from tkinter import scrolledtext
from typing import Callable, Optional
from PIL import Image, ImageTk
from bili_chat.message_segments import MAX_DANMAKU_LENGTH, segment_lengths, split_segments, validate_segments


class QRCodeDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("掃描 QR Code 登入")
        self.geometry("300x350")
        self.resizable(False, False)
        self.grab_set()
        
        self.label = ctk.CTkLabel(self, text="請使用 Bilibili APP 掃描", font=("Microsoft JhengHei UI", 14))
        self.label.pack(pady=(20, 10))
        
        self.qr_label = ctk.CTkLabel(self, text="")
        self.qr_label.pack(pady=10)
        
        self.status_label = ctk.CTkLabel(self, text="等待掃描...", text_color="gray")
        self.status_label.pack(pady=10)
    
    def show_qr_code(self, path: str):
        img = Image.open(path)
        img = img.resize((200, 200), Image.Resampling.LANCZOS)
        self.qr_image = ImageTk.PhotoImage(img)
        self.qr_label.configure(image=self.qr_image, text="")
    
    def set_success(self):
        self.status_label.configure(text="登入成功！", text_color="#2ecc71")
        self.after(1000, self.destroy)
    
    def set_failed(self):
        self.status_label.configure(text="登入失敗", text_color="#e74c3c")
        self.after(2000, self.destroy)


class BiliChatUI:
    MAX_LINES = 100
    EMPTY_COUNT_PLACEHOLDER = " "
    EMOTICON_PLACEHOLDER = "選擇房間表情"
    AUTO_EMOTICON_PLACEHOLDER = "自動回應表情"
    FAILED_DANMAKU_TAG = "failed_danmaku"

    def __init__(
        self,
        on_connect: Callable,
        on_send: Callable,
        on_disconnect: Callable,
        rooms: list = None,
        on_send_emoticon: Optional[Callable] = None,
        on_auto_emoticon: Optional[Callable] = None,
        on_auto_emoticon_selected: Optional[Callable] = None,
    ):
        self.on_connect = on_connect
        self.on_send = on_send
        self.on_disconnect = on_disconnect
        self.on_send_emoticon = on_send_emoticon
        self.on_auto_emoticon = on_auto_emoticon
        self.on_auto_emoticon_selected = on_auto_emoticon_selected
        self.rooms = rooms or []
        self.url_map = {f"{r['name']} ({r['url']})": r['url'] for r in self.rooms}
        self._line_count = 0
        self._is_connected = False
        self._emoticon_map = {}
        self._selected_emoticon = None
        self._auto_emoticon_selection = None
        self._auto_emoticon_enabled = False
        
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        self.root = ctk.CTk()
        self.root.title("Bilibili 直播聊天室")
        self.root.geometry("450x600")
        self.root.minsize(350, 400)
        
        self._build_ui()

    def _build_ui(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(2, weight=1)
        
        top_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        top_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        top_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(top_frame, text="直播間:").grid(row=0, column=0, padx=(0, 5))
        
        display_names = list(self.url_map.keys())
        self.room_combo = ctk.CTkComboBox(
            top_frame,
            values=display_names,
            width=250
        )
        self.room_combo.grid(row=0, column=1, padx=(0, 5), sticky="ew")
        if display_names:
            self.room_combo.set(display_names[0])
        else:
            self.room_combo.set("https://live.bilibili.com/")
        self.room_combo.bind("<Return>", lambda e: self._on_connect_click())
        
        self.connect_btn = ctk.CTkButton(top_frame, text="連接", width=70, command=self._on_connect_click)
        self.connect_btn.grid(row=0, column=2)
        
        self.chat_display = scrolledtext.ScrolledText(
            self.root,
            wrap="word",
            font=("Microsoft JhengHei UI", 11),
            bg="#1f1f1f",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            padx=10,
            pady=10
        )
        self.chat_display.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        self.chat_display.tag_configure(
            self.FAILED_DANMAKU_TAG,
            foreground="#ff5c5c",
            overstrike=True,
        )
        self.chat_display.configure(state="disabled")
        
        bottom_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        bottom_frame.grid(row=3, column=0, padx=10, pady=(5, 10), sticky="ew")
        bottom_frame.grid_columnconfigure(0, weight=1)
        
        self.msg_entry = ctk.CTkTextbox(bottom_frame, height=70, font=("Microsoft JhengHei UI", 12))
        self.msg_entry.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.msg_entry.bind("<Shift-Return>", self._on_shift_return)
        self.msg_entry.bind("<Return>", self._on_return)
        self.msg_entry.bind("<KeyRelease>", self._on_message_change)

        self.count_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        self.count_frame.grid(row=1, column=0, padx=(0, 5), pady=(2, 0), sticky="w")
        self._show_empty_count_placeholder()

        self.emoticon_combo = ctk.CTkComboBox(
            bottom_frame,
            values=[self.EMOTICON_PLACEHOLDER],
            width=180,
            state="disabled",
            command=self._on_emoticon_selected,
        )
        self.emoticon_combo.grid(row=2, column=0, padx=(0, 5), pady=(4, 0), sticky="w")
        self.emoticon_combo.set(self.EMOTICON_PLACEHOLDER)

        self.auto_emoticon_combo = ctk.CTkComboBox(
            bottom_frame,
            values=[self.AUTO_EMOTICON_PLACEHOLDER],
            width=180,
            state="disabled",
            command=self._on_auto_emoticon_selected,
        )
        self.auto_emoticon_combo.grid(row=3, column=0, padx=(0, 5), pady=(4, 0), sticky="w")
        self.auto_emoticon_combo.set(self.AUTO_EMOTICON_PLACEHOLDER)

        self.auto_emoticon_btn = ctk.CTkButton(
            bottom_frame,
            text="自動回應：關",
            width=100,
            state="disabled",
            command=self._toggle_auto_emoticon,
        )
        self.auto_emoticon_btn.grid(row=3, column=1, pady=(4, 0))
        
        self.send_btn = ctk.CTkButton(bottom_frame, text="發送", width=70, command=self._on_send_click, state="disabled")
        self.send_btn.grid(row=0, column=1, rowspan=3)

    def _show_empty_count_placeholder(self):
        ctk.CTkLabel(
            self.count_frame,
            text=self.EMPTY_COUNT_PLACEHOLDER,
            text_color="gray",
        ).grid(row=0, column=0)

    def _on_shift_return(self, event):
        self.msg_entry.insert("insert", "\n")
        self.root.after_idle(self._update_message_state)
        return "break"

    def _on_return(self, event):
        self._on_send_click()
        return "break"

    def _on_message_change(self, event):
        self._update_message_state()

    def _on_emoticon_selected(self, selected: str):
        emoticon = self._emoticon_map.get(selected)
        if not emoticon:
            return
        current_text = self.msg_entry.get("1.0", "end-1c")
        self.msg_entry.insert("end", emoticon["display"])
        self._selected_emoticon = emoticon if not current_text.strip() else None
        self.emoticon_combo.set(self.EMOTICON_PLACEHOLDER)
        self._update_message_state()

    def _on_auto_emoticon_selected(self, selected: str):
        self._auto_emoticon_selection = self._emoticon_map.get(selected)
        if self.on_auto_emoticon_selected:
            self.on_auto_emoticon_selected(
                self._auto_emoticon_selection["unique"]
                if self._auto_emoticon_selection
                else None
            )
        if self._auto_emoticon_enabled:
            if self._auto_emoticon_selection:
                self.on_auto_emoticon(
                    True,
                    self._auto_emoticon_selection["unique"],
                )
            else:
                self._auto_emoticon_enabled = False
                self.on_auto_emoticon(False, None)
                self.auto_emoticon_btn.configure(text="自動回應：關")
        self.auto_emoticon_btn.configure(
            state="normal" if self._is_connected and self._auto_emoticon_selection else "disabled"
        )

    def _toggle_auto_emoticon(self):
        if not self._auto_emoticon_selection:
            return

        self._auto_emoticon_enabled = not self._auto_emoticon_enabled
        if self._auto_emoticon_enabled:
            self.on_auto_emoticon(
                True,
                self._auto_emoticon_selection["unique"],
            )
            self.auto_emoticon_btn.configure(text="自動回應：開")
        else:
            self.on_auto_emoticon(False, None)
            self.auto_emoticon_btn.configure(text="自動回應：關")

    def _update_message_state(self):
        text = self.msg_entry.get("1.0", "end-1c")
        lengths = segment_lengths(text)
        segments = split_segments(text)
        is_valid, _ = validate_segments(segments)

        for child in self.count_frame.winfo_children():
            child.destroy()
        if not lengths:
            self._show_empty_count_placeholder()
        for index, length in enumerate(lengths):
            if index:
                ctk.CTkLabel(self.count_frame, text="｜", text_color="gray").grid(row=0, column=index * 2)
            color = "#e74c3c" if length > MAX_DANMAKU_LENGTH else "gray"
            ctk.CTkLabel(
                self.count_frame,
                text=f"{length}/{MAX_DANMAKU_LENGTH}",
                text_color=color,
            ).grid(row=0, column=index * 2 + 1)

        state = "normal" if self._is_connected and segments and is_valid else "disabled"
        self.send_btn.configure(state=state)

    def _get_url_from_input(self) -> str:
        text = self.room_combo.get().strip()
        if text in self.url_map:
            return self.url_map[text]
        return text

    def _on_connect_click(self):
        url = self._get_url_from_input()
        if not url:
            return
        self.on_connect(url)

    def _on_send_click(self):
        text = self.msg_entry.get("1.0", "end-1c")
        segments = split_segments(text)
        is_valid, _ = validate_segments(segments)
        if not self._is_connected or not segments or not is_valid:
            return
        selected = self._selected_emoticon
        if (
            selected
            and self.on_send_emoticon
            and len(segments) == 1
            and segments[0].strip() == selected["display"]
        ):
            self.on_send_emoticon(selected["unique"])
        else:
            self.on_send(segments)
        self._selected_emoticon = None
        self.msg_entry.delete("1.0", "end")
        self._update_message_state()

    MAX_LINES = 100

    def _trim_display(self):
        if self._line_count > self.MAX_LINES:
            delete_count = self._line_count - self.MAX_LINES
            self.chat_display.delete('1.0', f'{delete_count + 1}.0')
            self._line_count = self.MAX_LINES

    def append_danmaku(self, uname: str, msg: str):
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", f"[{uname}]: {msg}\n")
        self._line_count += 1
        if self._line_count > self.MAX_LINES:
            self._trim_display()
        self.chat_display.configure(state="disabled")

    def append_failed_danmaku(self, msg: str):
        self.chat_display.configure(state="normal")
        self.chat_display.insert(
            "end",
            f"[我][發送失敗] {msg}\n",
            self.FAILED_DANMAKU_TAG,
        )
        self._line_count += 1
        if self._line_count > self.MAX_LINES:
            self._trim_display()
        self.chat_display.configure(state="disabled")

    def append_log(self, text: str):
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", f"[系統] {text}\n")
        self._line_count += 1
        if self._line_count > self.MAX_LINES:
            self._trim_display()
        self.chat_display.configure(state="disabled")

    def scroll_to_end(self):
        self.chat_display.see("end")

    def set_connected(self, connected: bool):
        if self._is_connected == connected:
            return
        self._is_connected = connected
        if connected:
            self.connect_btn.configure(text="斷開", command=self._on_disconnect_click)
            self.room_combo.configure(state="disabled")
        else:
            self.connect_btn.configure(text="連接", command=self._on_connect_click)
            self.room_combo.configure(state="normal")
        self.emoticon_combo.configure(
            state="normal" if connected and self._emoticon_map else "disabled"
        )
        self.auto_emoticon_combo.configure(
            state="normal" if connected and self._emoticon_map else "disabled"
        )
        self.auto_emoticon_btn.configure(
            state="normal" if connected and self._auto_emoticon_selection else "disabled"
        )
        self._update_message_state()

    def _on_disconnect_click(self):
        self.on_disconnect()
        self.set_connected(False)

    def show_error(self, text: str):
        self.append_log(f"錯誤: {text}")

    def show_qr_code(self, path: str):
        self.qr_dialog = QRCodeDialog(self.root)
        self.qr_dialog.show_qr_code(path)

    def qr_login_done(self, success: bool):
        if hasattr(self, 'qr_dialog') and self.qr_dialog:
            if success:
                self.qr_dialog.set_success()
            else:
                self.qr_dialog.set_failed()
            self.qr_dialog = None

    def update_rooms(self, rooms: list, current_url: str = None):
        self.rooms = rooms
        self.url_map = {f"{r['name']} ({r['url']})": r['url'] for r in rooms}
        display_names = list(self.url_map.keys())
        self.room_combo.configure(values=display_names)
        if current_url:
            for name, url in self.url_map.items():
                if url == current_url:
                    self.room_combo.set(name)
                    break
        elif display_names:
            self.room_combo.set(display_names[0])

    def update_emoticons(
        self, emoticons: list[dict], selected_unique: Optional[str] = None
    ):
        self._emoticon_map = {
            emoticon["display"]: emoticon
            for emoticon in emoticons
            if emoticon.get("emoji") and emoticon.get("text")
        }
        self._selected_emoticon = None
        if self._auto_emoticon_enabled:
            if self.on_auto_emoticon:
                self.on_auto_emoticon(False, None)
        self._auto_emoticon_selection = next(
            (
                emoticon
                for emoticon in self._emoticon_map.values()
                if emoticon.get("unique") == selected_unique
            ),
            None,
        )
        self._auto_emoticon_enabled = False
        values = [self.EMOTICON_PLACEHOLDER, *self._emoticon_map.keys()]
        self.emoticon_combo.configure(
            values=values,
            state="normal" if self._is_connected and self._emoticon_map else "disabled",
        )
        self.emoticon_combo.set(self.EMOTICON_PLACEHOLDER)
        self.auto_emoticon_combo.configure(
            values=[self.AUTO_EMOTICON_PLACEHOLDER, *self._emoticon_map.keys()],
            state="normal" if self._is_connected and self._emoticon_map else "disabled",
        )
        self.auto_emoticon_combo.set(
            self._auto_emoticon_selection["display"]
            if self._auto_emoticon_selection
            else self.AUTO_EMOTICON_PLACEHOLDER
        )
        self.auto_emoticon_btn.configure(
            text="自動回應：關",
            state=(
                "normal"
                if self._is_connected and self._auto_emoticon_selection
                else "disabled"
            ),
        )

    def run(self):
        self.root.mainloop()

    def stop(self):
        self.root.quit()
