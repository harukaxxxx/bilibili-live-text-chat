import customtkinter as ctk
import re
from tkinter import scrolledtext
from typing import Callable, Optional
from PIL import Image, ImageTk


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
    def __init__(self, on_connect: Callable, on_send: Callable, on_disconnect: Callable):
        self.on_connect = on_connect
        self.on_send = on_send
        self.on_disconnect = on_disconnect
        
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
        
        self.url_entry = ctk.CTkEntry(top_frame, placeholder_text="https://live.bilibili.com/10971399")
        self.url_entry.grid(row=0, column=1, padx=(0, 5), sticky="ew")
        self.url_entry.insert(0, "https://live.bilibili.com/10971399")
        self.url_entry.bind("<Return>", lambda e: self._on_connect_click())
        
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
        self.chat_display.configure(state="disabled")
        
        bottom_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        bottom_frame.grid(row=3, column=0, padx=10, pady=(5, 10), sticky="ew")
        bottom_frame.grid_columnconfigure(0, weight=1)
        
        self.msg_entry = ctk.CTkEntry(bottom_frame, placeholder_text="輸入訊息...")
        self.msg_entry.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.msg_entry.bind("<Return>", lambda e: self._on_send_click())
        
        self.send_btn = ctk.CTkButton(bottom_frame, text="發送", width=70, command=self._on_send_click, state="disabled")
        self.send_btn.grid(row=0, column=1)

    def _on_connect_click(self):
        url = self.url_entry.get().strip()
        if not url:
            return
        self.on_connect(url)

    def _on_send_click(self):
        msg = self.msg_entry.get().strip()
        if not msg:
            return
        self.msg_entry.delete(0, "end")
        self.on_send(msg)

    def append_danmaku(self, uname: str, msg: str):
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", f"[{uname}]: {msg}\n")
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

    def append_log(self, text: str):
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", f"[系統] {text}\n")
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

    def set_connected(self, connected: bool):
        if connected:
            self.connect_btn.configure(text="斷開", command=self._on_disconnect_click)
            self.send_btn.configure(state="normal")
            self.url_entry.configure(state="disabled")
        else:
            self.connect_btn.configure(text="連接", command=self._on_connect_click)
            self.send_btn.configure(state="disabled")
            self.url_entry.configure(state="normal")

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

    def run(self):
        self.root.mainloop()

    def stop(self):
        self.root.quit()
