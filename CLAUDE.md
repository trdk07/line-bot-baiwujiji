# 百無禁忌 LINE Bot

命理諮詢工作室的 LINE Bot：關鍵字比對（0 Token）+ 預約流程 + 匯款確認三步機制。
FastAPI 應用，部署在 Vercel（Python serverless function）。

## 專案結構

```
line-bot-vercel/
  api/index.py              # Vercel 入口點（re-export app.main:app）
  app/
    main.py                 # FastAPI app、health check
    config.py                # 環境變數集中管理（pydantic Settings）
    routers/webhook.py       # 主路由：LINE webhook 處理、管理員指令
    services/
      keyword_router.py      # 關鍵字 → 意圖代碼比對
      state_service.py       # Vercel KV (Upstash Redis) 狀態管理
      calendar_service.py    # Google Calendar 查詢空檔 / 建立事件
      notify_service.py      # LINE push message 通知
    templates/flex_messages.py  # 所有 Flex Message 卡片模板
  tests/                    # pytest 測試（純函式 + 端對端整合）
  requirements.txt          # 正式環境依賴（Vercel 用）
  requirements-dev.txt      # 本地開發依賴（+ uvicorn + pytest）
docs/                       # 設計期預覽頁面（非程式碼）
```

## 訊息處理流程

1. **管理員指令**（`/off /on /ok /no /paid /list /clear /change /myid`）— 不受 Bot 開關影響，見下方「管理員指令」
2. **Bot 開關檢查** — 關閉時只回覆一次「老師在線」提示，之後靜默
3. **諮詢資料填寫攔截** — 客人剛預約完，等待填寫姓名/生日/問題
4. **關鍵字比對**（`keyword_router.match_keyword`）→ 固定回應，0 Token
5. **無匹配** → 靜默不回應（不接 AI，目前沒有 LLM 整合）

## 預約狀態機

```
pending → awaiting_payment → payment_reported → (刪除，存入 done 區)
  ↑ 客人選定日期時段        ↑ 客人回報「已匯款」
       管理員 /ok                                管理員 /paid
                                                （建立 Google Calendar 事件）
```

- 任一狀態下管理員可用 `/no` 婉拒（刪除預約，通知客人）
- `/change` 可對進行中或已完成（`done`）的預約改期
- **逾時掃描**（每日 cron `sweep_stale_bookings`，先提醒後釋放）：
  `pending` 超過 24 小時提醒管理員處理（每 48 小時再提醒）；
  `awaiting_payment` 超過 48 小時提醒客人匯款（一次）、超過 72 小時
  自動取消並釋放時段（通知雙方）；`payment_reported` 永不自動取消。
  狀態變更時間存於 booking JSON 的 `u` 欄位（epoch 秒）。
- **軟鎖定**：`calendar_service.get_available_slots()` 會把 `pending` /
  `awaiting_payment` / `payment_reported` 狀態的預約時段也視為佔用，
  避免管理員確認收款、建立日曆事件前，該時段被其他客人重複預約
  （見 `state_service.get_taken_slots`）。

## KV Key 一覽（Vercel KV / Upstash Redis）

| Key | 用途 | TTL |
|---|---|---|
| `bot_active` | Bot 開關狀態（"on"/"off"，預設 on） | 無 |
| `bot_off_notified` | Set，記錄 Bot 關閉期間已通知過的 user_id | 無（開啟時清除） |
| `principles:{user_id}` | 是否已看過預約原則說明 | 無 |
| `booking:{user_id\|booking_id}` | 單筆預約資料 JSON `{d,t,n,s}` | 無 |
| `booking_queue` | List，進行中預約的 ref 清單（`user_id\|booking_id`） | 無 |
| `done:{ref}` | 已完成預約資料（含 `cal_id`） | 30 天 |
| `done_queue` | List，已完成預約的 ref 清單 | 無 |
| `intake_pending:{user_id}` | 是否等待填寫諮詢資料 | 24 小時 |
| `intake_data:{user_id}` | 諮詢資料 JSON `{b: 生日, q: 問題}` | 30 天 |
| `clear_confirm_pending` | `/clear` 二次確認狀態 | 60 秒 |
| `customer:{user_id}` | 顧客累積檔案 JSON `{n,c,first,last}`（回頭客辨識） | 無（永久累積） |
| `order_seq:{year}` | 對外訂單編號年度流水號（INCR） | 無 |
| `stats:{YYYY-MM}:{field}` | 月度彙總（`new`/`done`/`released`，INCR，儀表板用） | 無（永久累積） |

`booking` JSON 欄位：`d`=日期、`t`=時段、`n`=客戶顯示名稱、`s`=狀態
（`pending`/`awaiting_payment`/`payment_reported`/`done`）、`o`=對外訂單編號
（`B-{年}-{4位流水號}`，前綴 B=預約諮詢，未來點燈 L／法會 F 共用同一組流水號）。
客人輸入「進度查詢」（`order_status` 意圖）可查自己所有進行中與已成立預約的狀態，
intake 攔截的逃逸名單包含此意圖。

`customer` 檔案在管理員 `/paid` 完成預約時累積（次數 +1、更新最近日期），
用於：預約入口卡片的「歡迎回來」、管理員通知的「第一次預約／回頭客」標註、
以及預約網頁 `/api/me`（簽章 uid 連結）顯示的歡迎橫幅。

所有 KV 操作都收斂在 `state_service.kv_cmd()` / `kv_get()` / `_pipeline()`，
新增狀態時直接複用這幾個底層函式即可。

## 管理員指令

| 指令 | 說明 |
|---|---|
| `/off` `/on` | 關閉／開啟 Bot（關閉後老師親自接管） |
| `/ok [編號]` | 確認預約日期 → 自動發匯款資訊給客人 |
| `/no [編號]` | 婉拒預約 → 通知客人 |
| `/paid [編號]` | 確認收款 → 建立 Google Calendar 事件 → 完成預約 |
| `/list` | 顯示所有進行中預約總覽 |
| `/clear` → `/clear yes` | 清除全部進行中預約（60 秒內二次確認） |
| `/change [編號] YYYY-MM-DD HH:MM` | 改期（進行中或已完成的預約皆可） |
| `/admin`（或「管理後台」） | 取得管理後台總覽頁連結（`admin.html`：進行中預約、月度統計） |

管理後台安全機制：`admin.html` 需帶有效 token 或 session cookie 才伺服；
首次以 token 開啟會經 `POST /api/admin/login` 換成 7 天效期的 HttpOnly 簽章
cookie（無狀態，金鑰由 LINE channel secret＋`ADMIN_PAGE_TOKEN` 衍生，
換掉 `ADMIN_PAGE_TOKEN` 即全部失效），並把 token 從網址列清除。
同一 IP 15 分鐘內驗證失敗 10 次鎖定（`authfail:{ip}`，KV 未設定時不鎖）。
後台的「確認日期／婉拒／確認收款」按鈕與 LINE 指令 `/ok` `/no` `/paid`
共用 `services/booking_actions.py` 的核心邏輯（雙軌等價）。
| `/myid` | 查詢自己的 LINE User ID（非管理員也可用） |

指令實作為 `webhook.py` 中的 `_cmd_*` 函式，統一透過 `ADMIN_COMMANDS`
對照表分派，入口只做一次 `is_admin()` 檢查。

## 環境變數（`app/config.py`）

| 變數 | 必填 | 用途 |
|---|---|---|
| `LINE_CHANNEL_SECRET` | ✓ | LINE Webhook 簽章驗證 |
| `LINE_CHANNEL_ACCESS_TOKEN` | ✓ | LINE Messaging API |
| `ADMIN_LINE_USER_ID` | | 管理員 LINE User ID |
| `KV_REST_API_URL` / `KV_REST_API_TOKEN` | | Vercel KV（不設定則所有狀態退化為預設值，Bot 仍可運作但無記憶） |
| `GOOGLE_SERVICE_ACCOUNT_JSON` / `GOOGLE_CALENDAR_ID` | | Google Calendar 整合（不設定則走 `booking_card()` 純文字填寫流程） |
| `PAYMENT_QR_IMAGE_URL` | | 匯款 QR Code 圖片網址（未設定或無效時，自動退回 app 自帶的 `app/static/qr-payment.png`，由 `/qr-payment.png` 路由伺服，需搭配 `PUBLIC_BASE_URL`） |

本地開發用 `.env` 檔（`line-bot-vercel/.env`，已在 `.gitignore`）；
Vercel 上在後台環境變數設定，不用 `.env`。

## 本地開發

```bash
cd line-bot-vercel
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

## 測試

```bash
cd line-bot-vercel
pytest
```

測試涵蓋零外部依賴的純函式（`keyword_router`、日期/時段計算、文字解析）
與模擬 LINE API + KV 的端對端整合測試（`tests/test_webhook_integration.py`）。
GitHub Actions（`.github/workflows/tests.yml`）在 push/PR 時自動執行。

修改 `keyword_router.KEYWORD_PATTERNS` 時務必留意：**pattern 順序即優先權**，
新增或調整關鍵字後先跑 `pytest tests/test_keyword_router.py` 確認沒有
破壞既有的優先順序（例如「招財項目」不可被「項目」搶先匹配成 `services`）。

## 部署

Vercel serverless function，`vercel.json` 用 `rewrites` 把所有路徑導到
`api/index.py`（該檔案 re-export `app.main:app`，Vercel 對 `api/` 目錄下的
Python 檔案會自動偵測為 function）。
