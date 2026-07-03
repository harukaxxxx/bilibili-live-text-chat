# Bilibili 直播彈幕聊天室

輕量級的 Bilibili 直播彈幕桌面應用，可以接收並發送彈幕。

## 功能

- QR Code 掃描登入（自動保存憑證）
- 連接直播間即時接收彈幕
- 發送彈幕到直播間
- 直播間記錄：自動保存連接過的直播間，顯示主播名稱
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

1. 輸入直播間連結（例如：`https://live.bilibili.com/123456`）
2. 點擊「連接」
3. 首次使用會彈出 QR Code，使用 Bilibili APP 掃描登入
4. 登入成功後自動連接直播間
5. 連接後會自動獲取並顯示主播名稱
6. 在輸入框輸入訊息，按 Enter 發送彈幕

### 直播間記錄

- 連接過的直播間會自動保存到 `rooms.json`
- 下次啟動時，可以從下拉選單快速選擇之前連接過的直播間
- 選單會顯示「主播名稱 (直播間網址)」格式
- 可以再次連接已記錄的直播間，或直接輸入新的網址

## 注意事項

- 登入憑證保存在 `credential.json`，請不要分享此檔案
- 直播間記錄保存在 `rooms.json`，可手動編輯或刪除
- 發送彈幕需要登入 Bilibili 帳號

## License

MIT