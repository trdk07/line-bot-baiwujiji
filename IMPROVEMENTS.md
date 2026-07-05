# 專案改善方案（Code Review 結論）

> 本文件為整個專案的審查結論，供後續實作參考。
> 每個項目都附上檔案位置與具體作法，建議依「執行順序」一節逐項處理，每項獨立 commit / PR，方便驗證沒有改壞既有行為。

程式碼規模現況（app 共約 2,500 行）：

| 檔案 | 行數 | 狀態 |
|---|---|---|
| `app/routers/webhook.py` | 729 | 過胖：巨型 if-chain |
| `app/templates/flex_messages.py` | 675 | 過胖：重複卡片結構 |
| `app/services/state_service.py` | 563 | 過胖：重複 KV 樣板 |
| `app/services/calendar_service.py` | 253 | 合理 |
| `app/services/notify_service.py` | 120 | 合理 |
| `app/services/keyword_router.py` | 65 | 合理（有冗餘 pattern） |

---

## 一、功能與正確性缺口（優先處理）

### 1-1. LINE Webhook 重送沒有去重（小改動、高價值）

**位置**：`app/routers/webhook.py` `handle_text_message()`

**問題**：LINE 在逾時或 5xx 時會重送 webhook。目前整條處理鏈（多次 KV HTTP 往返 + LINE Profile API + Google Calendar API）同步執行、全部跑完才回 200，Vercel 冷啟動時容易超時。重送一次 `booking_confirm` 就會產生重複預約（`save_booking()` 每次都生成新的 booking_id）。

**作法**：在 `handle_text_message` 開頭檢查 `event.delivery_context.is_redelivery`，為 True 就直接 return。更嚴謹可用 `event.webhook_event_id` 在 KV 做 `SET key 1 NX EX 3600` 去重，但 is_redelivery 已足夠。

### 1-2. intake_pending 攔截會吞掉客人的其他意圖（小改動、高價值）

**位置**：`app/routers/webhook.py` 「諮詢資料填寫攔截」區塊（約 line 568）

**問題**：攔截層在關鍵字比對之前。客人剛預約完（intake_pending=1）若馬上輸入「我要預約」想改時間、或問「服務項目」，訊息會被誤存為諮詢資料並回覆「已收到您的諮詢資料 ✓」。

**作法**：攔截條件加上 `intent is None`（intent 在函式開頭已經算好了）。也就是：只有訊息不匹配任何關鍵字時才當成諮詢資料。可再加一個啟發式：訊息含「1.」「①」或為多行文字時優先視為資料。注意保留現有行為：攔截成功時才 `clear_intake_pending`，未攔截（走了其他意圖）時保留 pending 狀態讓客人稍後補填。

### 1-3. `/debug/calendar`、`/debug/env` 為公開端點（小改動）

**位置**：`app/main.py`

**問題**：無任何驗證，任何人知道網址即可看到 service account email、project id、private key 前 30 字元、QR 圖片網址前綴等資訊。

**作法**：二選一：(a) 直接刪除這兩個端點（當初的連線問題已解決）；(b) 加 `DEBUG_TOKEN` 環境變數，request 需帶 `?token=...` 才回應，否則 404。建議 (a)。

### 1-4. 時段沒有「軟鎖定」，會發生雙重預約（最大業務風險）

**位置**：`app/services/calendar_service.py` `get_available_slots()`

**問題**：可用時段只查 Google Calendar freebusy，但日曆事件要等管理員 `/paid` 才建立。從客人送出預約到收款確認之間（可能數小時），該時段對其他客人仍顯示可預約，會發生兩人約到同一時段。

**作法**：`get_available_slots(date_str)` 在過濾 busy 之後，再呼叫 `state_service.get_all_queue_bookings()`，把佇列中（pending / awaiting_payment / payment_reported）同日期的 `booking["t"]` 也從可用清單移除。注意：無 Calendar 設定時的 fallback 路徑也要套用同樣過濾。

### 1-5. Push 失敗時管理員收到假成功訊息

**位置**：`app/services/notify_service.py` 的 `push_text_to_user()` / `push_flex_to_user()`，及 `webhook.py` 中 `/ok`、`/no`、`/paid`、`/change` 的呼叫端

**問題**：推送失敗（客人封鎖 Bot、push 額度用盡）只寫 log，管理員仍看到「匯款資訊已發送給客人」等成功訊息。

**作法**：兩個 push 函式改為回傳 `bool`。呼叫端據此調整回覆文字，失敗時顯示「⚠️ 推送給客人失敗，請手動聯繫」。

### 1-6. 跨午夜 00:00 時段的當日過濾 bug（低優先）

**位置**：`app/services/calendar_service.py` `get_available_slots()` 的「今天過濾」邏輯（三處重複的 `t > current_time` 字串比較）

**問題**：週日 20:00–01:00 產生的「00:00」時段實際是隔天凌晨，但字串比較會把它誤判為已過去而濾掉。目前日期選單只提供明天起的日期所以踩不到，但客人手動輸入「預約 <今天日期>」就會觸發。

**作法**：過濾時改用 datetime 比較（`_generate_slot_times` 回傳的本來就是含日期的 datetime，直接 `slot > now` 再轉字串），順便把三處重複的過濾邏輯抽成一個小函式。

### 1-7. `/clear` 沒有二次確認（低優先）

**位置**：`app/routers/webhook.py` `booking_clear` 區塊

**問題**：一個誤觸就刪光所有進行中預約，且不可復原。

**作法**：改為兩步：`/clear` 先回覆「將刪除 N 筆，確認請輸入 /clear yes」，`/clear yes` 才執行。可用 KV 短 TTL key（60 秒）記錄待確認狀態。

---

## 二、代碼瘦身（去肥大）

三個過胖檔案的共同病因是**重複樣板**，以下依收益排序。

### 2-1. state_service.py：收斂 KV 樣板（563 行 → 約 250 行）

每個函式都重複同一套：`_get_kv_url()` → 判空 → `httpx.get/post` → try/except → 解析 `result`，全檔約 15 處幾乎相同的區塊。

**作法**：建立三個底層函式，其餘函式全部改寫成 2-4 行：

```python
def kv_cmd(*args) -> Any | None:
    """單一 Redis 指令（POST /），失敗回 None。"""

def kv_get(key: str) -> str | None:
    """語法糖：kv_cmd("GET", key)。"""

def _pipeline(commands: list) -> list:
    """既有的批次指令，保留。"""
```

同時合併 `update_booking_datetime` 與 `update_done_booking_datetime`（只差 key 前綴與 TTL，合成一個帶參數的函式）。

### 2-2. state_service.py：移除 legacy `admin_context` 相容碼

**位置**：`_fetch_queue_with_bookings()`（GET admin_context 與 legacy_uid 附加）、`get_queue_bookings_by_status()`（自動遷移區塊）、`delete_booking()`（順手 DEL admin_context）、`_entry_user_id()` 的舊格式註解。

這是舊版「單一預約」時代的遷移邏輯，佇列制上線已久，舊資料早已消化完。移除後可再減約 50 行，且佇列讀取邏輯清爽許多。移除後 `_fetch_queue_with_bookings` 只剩 1 次 pipeline 呼叫（LRANGE + 批次 GET）。

### 2-3. webhook.py：管理員指令表化（729 行 → 約 400 行）

`handle_text_message()` 一個函式 470 行，其中「只有管理員可以使用這個指令」的 `if is_admin(): ... else: ...` 巨型縮排重複了 **8 次**。

**作法**：

1. 把 `/off` `/on` `/ok` `/no` `/paid` `/list` `/clear` `/change` 各抽成獨立的模組層函式 `_cmd_ok(event, user_id, text)` 等。
2. 建立 `ADMIN_COMMANDS = {"bot_off": _cmd_off, "booking_ok": _cmd_ok, ...}` 對照表（比照現有的 `INTENT_HANDLERS` 模式）。
3. 主函式入口統一處理：

```python
if intent in ADMIN_COMMANDS:
    if not is_admin(user_id):
        reply_text(event, "只有管理員可以使用這個指令。")
        return
    ADMIN_COMMANDS[intent](event, user_id, user_text)
    return
```

`/ok` `/no` `/paid` 三段的「解析編號 → `_pick_booking` → 更新 → 推送客人 → 回覆管理員」結構相同，抽出後可視情況再共用小工具，但不必過度抽象——保持每個指令函式可獨立閱讀即可。

### 2-4. flex_messages.py：通用服務卡 builder（675 行 → 約 400 行）

六張服務卡（consultation / fortune / wealth / love / fengshui / custom）結構完全相同：標題 + 價格 + 分隔線 + 說明段落 + 按鈕。

**作法**：新增一個通用 builder，六個函式各改成一筆資料宣告：

```python
def _service_card(alt_text, title, price, paragraphs, button_label="預約諮詢", button_text="我要預約") -> dict:
    ...
```

好處除了減行數，之後改文案只動資料、改版型只動一處。動手前先把每張卡現在的 JSON dump 存下來，重構後比對輸出完全一致（這是最可靠的驗證方式）。

### 2-5. keyword_router.py：清理冗餘 pattern + 預編譯

- `我要預約|預約|想預約|預約諮詢|我想預約` → 只需 `預約`（其餘全被涵蓋）。逐條檢查其他 pattern 的同類冗餘（如 `找小夏老師|找老師|找小夏` → `找老師|找小夏`）。
- 模組載入時 `re.compile` 一次，存成 `[(compiled, intent), ...]`，serverless 溫實例間可省重複編譯。
- **注意**：pattern 順序即優先順序，清理時不可改變相對順序；先補測試（見 3-1）再動手。

### 2-6. 部署與死檔案清理

| 項目 | 作法 |
|---|---|
| `requirements.txt` 的 `uvicorn[standard]` | Vercel 的 @vercel/python 直接跑 ASGI，用不到 uvicorn，且拖進 uvloop 等重依賴。移除，另建 `requirements-dev.txt` 供本地 `uvicorn app.main:app --reload` 使用 |
| 根目錄 `flow.html`、`preview-colors.html`、`preview-title-colors.html` | 設計期預覽產物，移到 `docs/` 或刪除 |
| `line-bot-vercel/qr-payment.png` | 死檔案：vercel.json 把所有路由導到 api/index.py，此圖不會被靜態伺服，程式碼也未引用（實際用 `PAYMENT_QR_IMAGE_URL` 環境變數）。刪除 |
| `vercel.json` | 舊式 `builds`/`routes` 語法，改用現行 `rewrites` 寫法 |

---

## 三、工程品質補強

### 3-1. 補測試（零外部依賴的純函式優先）

目前完全沒有測試。最划算的起點（不需要 mock 任何外部服務）：

1. `keyword_router.match_keyword`：意圖優先順序很脆弱（加關鍵字時容易破壞順序），列一張「輸入 → 期望意圖」對照表逐條驗證，包含負例（不該匹配的訊息）。
2. `webhook._parse_intake_text` / `_parse_booking_number`：各種格式（1. / ① / 純換行 / 缺欄位）。
3. `calendar_service._generate_slot_times` / `get_next_available_dates` / `format_date_label`：重點測跨午夜（週日 20:00–01:00）。

加一個 GitHub Actions workflow 跑 `pytest`（push / PR 觸發即可）。

### 3-2. 寫 CLAUDE.md / README

狀態機流程、KV key 結構、管理員指令表目前只散落在 docstring。建議記錄：

- 預約狀態機：`pending → awaiting_payment → payment_reported → done(30天TTL)`，以及各狀態由誰的什麼動作觸發
- KV key 一覽：`booking:{ref}`、`booking_queue`、`done:{ref}`、`done_queue`、`bot_active`、`bot_off_notified`、`principles:{uid}`、`intake_pending:{uid}`、`intake_data:{uid}`
- 管理員指令表：`/on /off /ok /no /paid /list /clear /change /myid`
- 環境變數清單（config.py 的欄位）與部署方式（Vercel）
- 本地開發啟動方式

### 3-3. 合併每則訊息的 KV 讀取（低優先的效能項）

每則客人訊息目前至少打 2-3 次 KV（`is_bot_active`、`has_intake_pending`，預約入口再加 `has_seen_principles`）。可在 `handle_text_message` 入口用一次 `_pipeline` 把需要的 key 全撈，降低延遲與 Upstash 用量。做完 2-1 之後再做這項會容易得多。

---

## 建議執行順序

1. **正確性小修**（各自獨立 commit）：1-1 webhook 去重 → 1-2 intake 誤吞 → 1-3 移除 debug 端點 → 1-5 push 失敗回報
2. **業務風險**：1-4 時段軟鎖定
3. **補測試**：3-1（先有安全網，後面的重構才敢動）
4. **瘦身**（每項獨立 PR）：2-1 KV helper → 2-2 移除 legacy 碼 → 2-3 webhook 指令表化 → 2-4 flex builder → 2-5 keyword 清理
5. **收尾**：2-6 死檔案與部署清理 → 3-2 CLAUDE.md → 1-6、1-7、3-3

**重構驗證原則**：二、瘦身類的改動不應改變任何對外行為——Flex JSON 輸出、回覆文字、KV 讀寫內容都要與重構前一致。flex 重構用 JSON dump 比對；webhook 重構後手動跑一輪完整預約流程（預約 → /ok → 已匯款 → /paid → /change）。
