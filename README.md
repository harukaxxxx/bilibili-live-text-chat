# Bilibili 直播彈幕聊天室

輕量級的 Bilibili 直播彈幕桌面應用，可以接收並發送彈幕。

## 功能

- QR Code 掃描登入（自動保存憑證）
- 連接直播間即時接收彈幕
- 發送彈幕到直播間
- 深色主題現代化 UI

## 系統需求

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) 套件管理工具

## 安裝

```bash
git clone https://github.com/harukaxxxx/bilibili-live-text-chat.git
```

## 啟動

### Windows
雙擊 `start.bat`

## 使用說明

1. 輸入直播間連結（預設為 `https://live.bilibili.com/10971399`）
2. 點擊「連接」
3. 首次使用會彈出 QR Code，使用 Bilibili APP 掃描登入
4. 登入成功後自動連接直播間
5. 在輸入框輸入訊息，按 Enter 發送彈幕

## 注意事項

- 登入憑證保存在 `credential.json`，請不要分享此檔案
- 發送彈幕需要登入 Bilibili 帳號

## License

MIT