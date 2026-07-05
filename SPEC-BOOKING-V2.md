# 預約系統 v2 生產規格說明書

> 本文件是實作規格，交付給執行者（AI 或人類）直接照做。
> 所有設計決策已與業主確認完畢（見附錄 A），實作時**不需要重新發問**，
> 遇到規格未涵蓋的小細節，依「精簡優先、行為可退化」原則自行判斷。
>
> **總原則：功能俱全但代碼不肥大。** 每個新模組都有行數預算（見 §7）。
> 全部 KV 操作走既有的 `kv_cmd()` / `kv_get()` / `_pipeline()`，
> 不新增任何重量級依賴（禁止引入前端框架、ORM、Notion SDK——Notion 用 httpx 直打 REST API）。

## 0. 功能總覽與架構

四個功能，彼此獨立可分批上線，依賴關係如下：

```
F1 預約確認卡片改版（請帖風）        — 獨立，先做
F2 手動開放時段（月曆資料模型）      — 核心資料層
F3 LIFF 月曆頁（客人選時段＋老師開時段）— 依賴 F2
F4 定期通知（Vercel Cron）          — 依賴 F2（讀開放時段）
F5 半自動 CRM 同步（Notion）        — 獨立，掛在 /paid 之後
```

建議實作順序：F1 → F2 → F3 → F4 → F5。每個 F 一個獨立 commit/PR，各自有驗收條件。

### 檔案增減總表

| 檔案 | 動作 | 說明 |
|---|---|---|
| `app/templates/flex_messages.py` | 修改 | F1 重寫 `booking_confirmed_card`；F3 新增 `liff_entry_card` |
| `app/services/slots_service.py` | **新增** | F2 開放時段資料層 |
| `app/services/calendar_service.py` | 修改 | F2 改讀開放時段，移除 `WEEKLY_SLOTS` |
| `app/services/crm_service.py` | **新增** | F5 Notion 讀寫 |
| `app/routers/api.py` | **新增** | F3 slots API + F4 cron 端點 |
| `app/routers/webhook.py` | 修改 | F3 預約入口改 LIFF、F5 `/crm` 指令 |
| `app/config.py` | 修改 | 新增環境變數 |
| `public/booking.html` | **新增** | F3 LIFF 單檔頁面 |
| `public/icons/*.png` | **新增** | F1 圖示（SVG 源檔放 `docs/icons-src/`） |
| `vercel.json` | 修改 | F4 crons 設定 |
| `tests/` | 修改+新增 | 各功能對應測試 |

---

## 1. F1 — 預約確認卡片改版（請帖風）

`/paid` 後發給客人的 `booking_confirmed_card` 全面改版。

### 1.1 設計原則

- **沿用既有配色 tokens**（`flex_messages.py` 頂部常數，不新增顏色，唯一例外是深棕 header 用
  既有 intake_card 的 `#3D1F1F`，可提升為常數 `BG_HEADER`）：
  - `BG_DARK #EFEBE5`（body 底）、`GOLD #C2A68C`、`TEXT_TITLE #7B3F2A`、
    `TEXT_WHITE #4A453C`、`TEXT_GREY #6E675E`、`DIVIDER #C8B8A8`、`ACCENT_RED #8B2020`
- **請帖（喜帖/邀請函）版式**：對稱置中、大量留白、日期時間是視覺主角、
  裝飾性分隔線、無 emoji——裝飾符號用「✦」字符與 PNG 圖示。
- 與現有 `intake_card`（發給老師那張）共用設計語言：深棕 header + 米色 body +
  「標籤—數值」欄位（複用/抽出 `_field()` 這個 pattern）。

### 1.2 卡片結構（由上而下）

```
┌────────────────────────────┐
│ HEADER  背景 #3D1F1F        │
│     ✦  預 約 成 立  ✦       │  GOLD, lg, bold, 置中（字距可用全形空格模擬）
│      百無禁忌研究所           │  #C8B8A8, xxs, 置中
├────────────────────────────┤
│ BODY    背景 BG_DARK        │
│                            │
│        7/12（日）           │  TEXT_TITLE, xxl, bold, 置中
│      15:00 – 16:00         │  TEXT_WHITE, lg, 置中
│        共 60 分鐘           │  TEXT_GREY, xs, 置中
│                            │
│   ────────  ✦  ────────    │  裝飾分隔線（做法見 1.3）
│                            │
│   大名                      │  GOLD, xs
│   王小明                    │  TEXT_WHITE, sm
│   生辰                      │  GOLD, xs（有資料才顯示）
│   1990/05/15 辰時           │  TEXT_WHITE, sm
│   所問之事                   │  GOLD, xs（有資料才顯示）
│   最近工作方向…              │  TEXT_WHITE, sm, wrap
│                            │
│   ────────  ✦  ────────    │
│        屆時見。              │  TEXT_TITLE, sm, 置中
│   如需改期，直接在此告知即可   │  TEXT_GREY, xxs, 置中
└────────────────────────────┘
```

### 1.3 實作要點

- **裝飾分隔線**：horizontal box → `[separator(flex:1, gravity:center), text "✦"(GOLD, xs, flex:0, margin sm), separator(flex:1, gravity:center)]`。抽成 `_ornament_divider()`，此卡與後續卡片共用。
- **欄位**：複用 intake_card 內的 `_field(label, value)` 概念——把它從 intake_card 的閉包提升為模組層私有函式，兩張卡共用（順便瘦身 intake_card）。
- 生辰、所問之事**有資料才渲染該欄位**（沿用現有 consultation_section 條件邏輯）；三個資料就是客人 intake 提供的：大名（`n` 或 intake 姓名）、生辰（intake `b`）、所問之事（intake `q`）。
- 標題「預約成立」不用 ✓ 符號、不用 ACCENT_RED——請帖不是系統通知。
- `altText`：`"預約成立 ✦ {date_label} {time}"`。

### 1.4 PNG 圖示管線（漸進增強，非必要條件）

- 圖示以 **SVG 設計**（幾何線條風、單色 `GOLD`，24×24 viewBox）：`calendar.svg`（日期）、`clock.svg`（時辰）、`seal.svg`（大名，印章意象）、`star.svg`（生辰）、`scroll.svg`（所問之事）。源檔放 `docs/icons-src/`。
- 輸出 **PNG @3x（72×72，透明底）** 放 `line-bot-vercel/public/icons/`。轉檔是一次性開發步驟：寫一個 dev-only script（cairosvg，只進 requirements-dev），或手動轉檔，**不得**把轉檔依賴放進正式 requirements。
- Flex 中以 `icon` 元件引用 `{PUBLIC_BASE_URL}/icons/xxx.png`（LINE 只接受 HTTPS 的 PNG/JPEG，**不支援 SVG**）。
- **退化規則**：`PUBLIC_BASE_URL` 未設定時，卡片一律走純文字版（不放 icon 元件）。先出純文字版上線，icon 是第二層 polish。

### 1.5 驗收

- [ ] 在 LINE 實機（手機深色/淺色模式）預覽不跑版，長問題文字 wrap 正常。
- [ ] 無 intake 資料時，卡片只有日期時間＋祝詞，不出現空欄位。
- [ ] 測試：更新 `tests/test_flex_messages.py`，鎖定新結構（標題文字、欄位條件渲染、altText）。
- [ ] 產出一份 `docs/preview-confirmed-card.html`（模擬 LINE 卡片外觀的靜態預覽頁，配色照 tokens），供業主上線前確認視覺。

---

## 2. F2 — 手動開放時段（資料模型）

**移除寫死的 `WEEKLY_SLOTS`**，改為老師每月手動開放時段。未開放＝不可預約。

### 2.1 KV 資料模型

| Key | 內容 | TTL |
|---|---|---|
| `open:{YYYY-MM}` | JSON：`{"2026-07-12": ["15:00","16:00","20:00"], ...}` 只存有開放時段的日期 | 100 天 |

- 時段字串一律 `HH:MM`、長度固定 60 分鐘（保留 `SLOT_DURATION`）。跨午夜場次以 `00:00` 記在**隔天**所屬的日期鍵下？——**否**：記在被點選的那一天（與現行「週日 20:00–01:00 的 00:00 場」慣例一致：00:00 記在週日的日期鍵，實際事件落在隔天凌晨，`create_event` 既有邏輯已處理跨午夜，但 `_generate_slot_times` 移除後需把「00:00 視為隔日凌晨」的換算搬進 slots_service 的一個小工具函式）。
- 可開放的時間格點（LIFF 編輯模式顯示的候選格）：常數 `SELECTABLE_TIMES = ["13:00","14:00",...,"23:00","00:00"]`，集中在 `slots_service.py` 頂部，要改範圍只動這一行。

### 2.2 新模組 `app/services/slots_service.py`

```python
get_open_slots(month: str) -> dict            # 讀 open:{month}，無資料回 {}
set_open_slots(month: str, data: dict) -> bool # 整月覆寫（LIFF 儲存用），寫入時過濾非法格式
get_open_dates(days: int = 30) -> list        # 未來 N 天內有開放時段的日期（供文字版 date picker 退化用）
slot_datetime(date_str, time_str) -> datetime  # 含跨午夜換算（00:00 → 隔日）
```

### 2.3 `calendar_service.py` 修改

- `get_available_slots(date_str)`：資料來源從 `_generate_slot_times` 改為
  `slots_service.get_open_slots(month).get(date_str, [])`，
  **其餘過濾鏈完全保留**：Google Calendar freebusy（老師私人行程仍會擋掉時段）→
  軟鎖定 `get_taken_slots` → 過去時段（用 `slot_datetime` 做完整 datetime 比較）。
- `get_next_available_dates()` → 委派給 `slots_service.get_open_dates()`。
- 刪除 `WEEKLY_SLOTS`、`_generate_slot_times`；`create_event`/`update_event` 改用 `slot_datetime` 計算起訖。
- 對應更新 `tests/test_calendar_service.py`、`test_available_slots.py`（跨午夜案例保留，改餵 open slots fixture）。

### 2.4 驗收

- [ ] 未設定任何開放時段的月份，客人進預約流程看到「本月時段尚未開放，請稍候」文案（新增於 webhook booking 分支）。
- [ ] 開放時段被預約（软鎖定）、老師行事曆有私人行程、已過去——三種都正確擋掉。
- [ ] 跨午夜 00:00 場：開在 7/12（日），實際 Calendar 事件落在 7/13 00:00–01:00。

---

## 3. F3 — LIFF 月曆頁（雙模式：客人選時段／老師開時段）

一個頁面兩種角色，用 LINE 身分自動判別。**客人端不需登入授權彈窗以外的任何操作**。

### 3.1 技術形態（防肥大的關鍵約束）

- **單檔** `public/booking.html`：vanilla JS + inline CSS，無框架、無 build step，行數預算 ≤ 450（含 CSS）。LIFF SDK 用官方 CDN `https://static.line-scdn.net/liff/edge/2/sdk.js`。
- Vercel 靜態檔案優先於 rewrites（filesystem match 先於 rewrite），所以 `public/` 下的頁面與圖示會直接被伺服，現有 `vercel.json` 的 rewrite 不用改結構。
- 行動裝置優先（頁面只會在 LINE 內開啟）。
- **開發預覽模式**：URL 帶 `?mock=1`（或 liff.init 失敗）時載入假資料渲染整頁，
  供業主在一般瀏覽器直接檢視視覺、也供不依賴 LIFF 的本機開發。

### 3.1b 視覺設計規格（強制，與 Flex 卡片同一套設計語言）

CSS variables 一比一沿用 bot 配色 tokens，**禁止出現此表以外的色值**
（透明度變化除外，如 rgba 陰影）：

```css
:root {
  --bg:        #EFEBE5;  /* BG_DARK    頁面底色 */
  --bg-header: #3D1F1F;  /* BG_HEADER  頂欄深棕 */
  --gold:      #C2A68C;  /* GOLD       點綴/可選時段/今日圈 */
  --title:     #7B3F2A;  /* TEXT_TITLE 標題赤褐/選中日 */
  --ink:       #4A453C;  /* TEXT_WHITE 主內文 */
  --muted:     #6E675E;  /* TEXT_GREY  次要說明 */
  --line:      #C8B8A8;  /* DIVIDER    格線/停用態 */
  --accent:    #8B2020;  /* ACCENT_RED 主 CTA */
  --sheet:     #FAF8F4;  /* 底部面板底色（BG_DARK 提亮一階，唯一新增的中性色）*/
}
```

逐元件用色（客人模式）：

| 元件 | 樣式 |
|---|---|
| 頂欄 | `--bg-header` 底、置中「百無禁忌研究所」`--gold`、副標「預約時段」`--line` xs；左右不放雜項 |
| 月份導航 | 月份文字 `--title` 粗體（serif），前後月箭頭 `--gold`；月份文字兩側各一個 ✦（`--gold`, 小號） |
| 星期列 | `--muted` xs |
| 日期格（預設） | 文字 `--ink`；格子無邊框，乾淨留白 |
| 今日 | `--gold` 細圓環（outline），文字不變 |
| 有可約時段的日 | 日期下方 1–3 個 `--gold` 小圓點（時段數 ≥3 顯示 3 點） |
| 當日全被約滿 | 圓點改 `--line`（灰點＝有開放但已滿，一目了然） |
| 過去的日／未開放日 | 文字 `--line`，不可點 |
| 選中的日 | `--title` 實心圓、文字 `--bg`（米色反白） |
| 底部時段面板 | `--sheet` 底、上緣圓角 16px、頂部一條 `--line` 拖曳把手；標題「7/12（日）」`--title` serif 粗體＋✦ |
| 可約時段 chip | `--gold` 實心、文字 `#FFFFFF`、圓角 8px（對齊 Flex 時段按鈕就是 GOLD 的慣例） |
| 已被約走 chip | 透明底、`--line` 1px 邊框、文字 `--muted` 加刪除線、不可點 |
| 確認列 | 「確認預約 7/12（日）15:00」按鈕 `--accent` 實心、文字白（對齊 Flex 主按鈕慣例）、上方一行 `--muted` xs 提示「送出後老師確認日期會再通知您」 |
| 空狀態（本月無開放） | 置中 ✦＋「本月時段尚未開放，請稍候」`--muted` |

老師編輯模式追加：

| 元件 | 樣式 |
|---|---|
| 編輯開關 | 頂欄右側小型 toggle，開啟時 thumb `--gold`；編輯中頂欄下沿出現 2px `--gold` 提示線 |
| 時段格點（開放中） | `--gold` 實心（同可約 chip） |
| 時段格點（未開放） | 透明底 `--line` 虛線邊框、文字 `--muted` |
| 已有預約而鎖定 | `--line` 實心、文字 `--muted`、右上角小鎖符號「⚿」或 ✦ 替代、點擊時 shake ＋ toast 說明 |
| 儲存按鈕 | `--accent` 實心，固定底部；儲存成功 toast `--bg-header` 底 `--gold` 字「已更新 ✦」 |

字體與質感：

- 標題（頂欄、月份、面板日期）：serif 堆疊
  `"Noto Serif TC","Songti TC","PMingLiU",serif`——**不載入 webfont**，
  用系統字型退化即可，維持請帖感又不增加載入重量。
- 內文/數字：系統 sans（`-apple-system, "PingFang TC", sans-serif`）。
- 陰影極輕（`rgba(61,31,31,.08)` 一層即可）、圓角統一 8/16px 兩檔、
  不用漸層、不用 emoji——裝飾一律用 ✦ 與細線，和卡片一致。
- 動效只允許兩處：底部面板滑入（150ms ease-out）、chip 按下的 opacity 變化。

### 3.2 後端 API（新增 `app/routers/api.py`，掛進 main.py）

| 端點 | 方法 | 授權 | 功能 |
|---|---|---|---|
| `/api/slots?month=YYYY-MM` | GET | 公開（無個資） | 回 `{open: {date:[times]}, taken: {date:[times]}, today: "..."}`。taken 來自 `get_taken_slots` 逐日彙整＋（若有 Calendar）freebusy；一次回整月。 |
| `/api/slots` | POST | LINE ID token | Body `{month, data, id_token}`。後端拿 id_token 打 LINE `POST https://api.line.me/oauth2/v2.1/verify`（帶 `client_id=LOGIN_CHANNEL_ID`），驗 `sub == ADMIN_LINE_USER_ID` 才允許 `set_open_slots`。 |

- 驗證失敗回 403；不做 session，每次儲存都重新驗 token（每月才存幾次，夠了）。
- `/api/slots` GET 的 freebusy 整月查詢只打一次 Google API（timeMin=月初、timeMax=月末），不要逐日打。

### 3.3 頁面 UX

**共通**：月曆網格（週一起始），今日高亮；日期格上以小圓點數量示意當日剩餘可約時段數；上下月切換箭頭（客人只能看本月＋下月，老師可再往後）。

**客人模式**（預設）：
1. 點有開放的日期 → 底部滑出時段列表：可約時段為實心可點按鈕（GOLD 底），已被約走的顯示灰色刪除線、不可點，已過去的不顯示。
2. 點時段 → 確認條「預約 7/12（日）15:00？」→ 確定 →
   `liff.sendMessages([{type:'text', text:'預約 2026-07-12 15:00'}])` → `liff.closeWindow()`。
   **關鍵設計：LIFF 只負責發出與現有按鈕一模一樣的文字訊息，整個預約狀態機、軟鎖定、通知流程零改動、全複用。**
3. 送出後若該時段其實已被搶（軟鎖定在 webhook 端把關）：現有流程本來就會在查無時段時回覆約滿，行為不變。

**老師模式**（`liff.getProfile().userId == ADMIN_LINE_USER_ID`，由 GET `/api/slots` 附帶的 `admin_hint` 或前端向後端要一次判定；簡單做法：前端把 userId 連同 GET 帶上，後端回 `is_admin` 布林——**不可**只信前端判斷，寫入時仍验 id_token）：
1. 右上角出現「編輯時段」開關。
2. 編輯模式下點日期 → 顯示 `SELECTABLE_TIMES` 全格點，已開放的高亮，點擊切換開/關。
3. 「儲存」→ POST 整月資料。已有預約佔用的時段在前端鎖定不可關閉（後端也要防：`set_open_slots` 不得移除已被 active booking 佔用的時段，若衝突回 409 與衝突清單）。

### 3.4 入口改動（webhook.py）

- `booking` intent（已看過原則後）：改回覆 `fm.liff_entry_card()` —— 一張小卡：「選擇方便的時間 ✦」＋ uri button 開 `https://liff.line.me/{LIFF_ID}`。
- **退化**：`LIFF_ID` 未設定時，回覆既有的 `date_picker_card(get_next_available_dates())` 文字流程（此路徑保留不刪，資料來源已在 F2 換成 open slots）。
- 新增關鍵字 `本週|下週|時段|什麼時候` → `intent: schedule` → 回 `liff_entry_card`（放在 booking pattern 之前，注意優先序並補測試）。

### 3.5 業主待辦（寫進交付 checklist，代碼做不了的）

- [ ] LINE Developers Console：建立 LINE Login channel（同 provider），新增 LIFF app（Size: Tall，Endpoint: `https://{domain}/booking.html`），取得 `LIFF_ID`、`LOGIN_CHANNEL_ID` 填入 Vercel env。
- [ ] （建議）Rich menu 加一顆「預約」按鈕直開 LIFF 連結。

### 3.6 驗收

- [ ] 客人：開頁 → 點日 → 點時段 → 聊天室出現「預約 …」訊息且流程接上。
- [ ] 老師：開時段 → 客人端立即可見；嘗試關閉已被預約時段被擋下。
- [ ] 非老師帶偽造 userId POST → 403。
- [ ] `LIFF_ID` 未設定時文字流程照舊可用。
- [ ] **視覺對照**：頁面上出現的每個色值都能對回 §3.1b 的 token 表；
      `?mock=1` 模式截圖與 Flex 卡片並排比對，質感一致（同一品牌一眼可辨）。
- [ ] 業主用手機瀏覽器開 `booking.html?mock=1` 確認視覺後才接 LIFF 上線。

---

## 4. F4 — 定期通知（Vercel Cron）

### 4.1 機制

- `vercel.json` 加 `crons`: `[{ "path": "/api/cron", "schedule": "0 13 * * *" }]`
  （每日 UTC 13:00 ＝ 台北 21:00 執行一次；Hobby 方案上限為每日一次，所以**一個 cron 端點內部分流**）。
- `/api/cron`（GET，放在 api.py）：驗 `Authorization: Bearer {CRON_SECRET}`（Vercel 設定 `CRON_SECRET` env 後會自動帶上），否則 403。
- 冪等：每種通知發送前先 `SET reminder:{type}:{date} 1 NX EX 172800`，搶不到鎖就跳過（防 cron 重試重複推播）。

### 4.2 每日執行的分流規則（全部用 push 發給老師，客人提醒發給客人）

| 條件 | 通知 | 對象 |
|---|---|---|
| 今天是 25 號 且 下個月 `open:{YYYY-MM}` 為空 | 「📅 {M+1} 月時段尚未開放，點此設定」＋ LIFF 連結按鈕 | 老師 |
| 今天是 1 號 | 本月總覽：開放 X 天 Y 時段、已成立預約 Z 筆（掃 done_queue + booking_queue） | 老師 |
| 明天有已成立（done）的預約 | 「明日預約提醒：{date_label} {time} ✦ 屆時見」 | **每位客人** |
| 明天有已成立的預約 | 「明日行程：N 筆——{清單}」 | 老師 |

- 明日預約掃描：`get_all_done_bookings()` 過濾 `d == 明天`，逐筆 `push_text_to_user`；失敗照 F1-5 慣例通知老師。
- 通知文案風格與卡片一致（✦、不堆 emoji）。25 號/1 號這兩個日期做成常數。

### 4.3 驗收

- [ ] 手動帶正確/錯誤 secret 打 `/api/cron` 驗證授權。
- [ ] 測試：分流規則抽成純函式 `due_notifications(today, open_next_month, tomorrow_bookings) -> list`，對其做單元測試（日期邊界：25 號、1 號、有無明日預約）。
- [ ] 同一天重打 `/api/cron` 不會重複推播。

---

## 5. F5 — 半自動 CRM 同步（Notion）

`/paid` 完成後推「客戶資料預覽卡」給老師，老師按「寫入 CRM」才真正寫入 Notion。

### 5.1 Notion 目標（實際 ID，直接使用）

| 資料庫 | data source ID | 用途 |
|---|---|---|
| 客户档案 | `1c250abc-cc15-8103-aa87-000bad27de6f` | 一客一檔，`LINE` 欄位存 LINE User ID 當唯一鍵 |
| 沟通记录 | `1c250abc-cc15-810a-8561-000b682503ff` | 每次預約成立寫一筆 |

欄位對映（只寫這些，其餘欄位一律不碰）：

| 來源 | 客户档案 | 沟通记录 |
|---|---|---|
| intake 姓名（缺則用 LINE 顯示名） | `客户姓名` (title) | `客户名称` (title) |
| LINE user id | `LINE` (text) | — |
| intake 生辰（**可解析出 YYYY-MM-DD 才寫**） | `阳历` (date) | — |
| 固定值 | `状态` = 新客「初次咨询」；舊客改「服务中」 | `咨询方式` = 「线上」 |
| 預約日期 | — | `沟通日期` (date) |
| intake 問題＋生辰原文 | — | `詳細溝通內容`：`【預約諮詢】{問題}\n生辰原文：{原文}` |
| 檔案關聯 | — | `客户档案` relation → 該客檔案頁 |

- 生辰解析：一個小純函式 `parse_birth_date(text) -> str|None`（regex 抓 `YYYY[-/年]M[-/月]D`，民國年 +1911）。解析失敗不擋流程，原文永遠留在溝通內容裡。

### 5.2 新模組 `app/services/crm_service.py`

用 httpx 直打 Notion REST API（`Notion-Version: 2025-09-03`，data source 端點；header `Authorization: Bearer {NOTION_API_KEY}`）：

```python
find_customer_by_line_id(user_id) -> dict|None   # query 客户档案, filter LINE equals
create_customer(payload) -> str|None              # 回傳 page_id
update_customer_status(page_id, status) -> bool
create_comm_record(payload, customer_page_id) -> bool
sync_booking_to_crm(pending: dict) -> tuple[bool, str]  # 上面四支的編排：查→建/更→寫溝通記錄
```

- 每支函式 ≤ 25 行；錯誤一律 log + 回傳失敗，由呼叫端決定文案。逾時 10 秒。
- **log 不得輸出生辰、問題內容等個資**，只 log page_id / 狀態碼。

### 5.3 流程與指令

1. `/paid` 完成（`_cmd_booking_paid` 尾端）：組 pending payload
   `{u, n(姓名), b(生辰原文), q(問題), d(預約日), t(時段)}` →
   `RPUSH crm_queue {json}`（列表；另設 `EXPIRE crm_queue 604800` 七天）→
   推預覽卡給老師。
2. 預覽卡（新 `fm.crm_preview_card(...)`，沿用深棕 header 設計語言）：
   顯示五個欄位＋新舊客判定（此時先查一次 `find_customer_by_line_id`，卡上標「新客戶」或「老客戶・第 N 次」）＋兩顆按鈕：
   「寫入 CRM」→ 文字 `/crm ok`、「略過」→ `/crm skip`。
3. 新增管理員指令（進 `ADMIN_COMMANDS`，keyword pattern `^/crm\b`）：
   - `/crm`：列出 crm_queue 待處理清單（複用 /list 的列表樣式）
   - `/crm ok [編號]`：取出該筆（無編號且僅一筆時自動選，複用 `_pick_booking` 的選取邏輯思路）→ `sync_booking_to_crm` → 成功回「已寫入 ✦ {姓名}（新客戶建檔/老客戶補記錄）」並 LREM；失敗回錯誤摘要、**保留佇列**可重試。
   - `/crm skip [編號]`：移除該筆。
4. `NOTION_API_KEY` 未設定：`/paid` 完全不推預覽卡、不進佇列（功能整體靜默停用）。

### 5.4 業主待辦

- [ ] Notion 建 internal integration，取 API key 填 `NOTION_API_KEY`。
- [ ] 把「百无禁忌工作室」CRM 頁面 share 給該 integration（否則 API 讀不到）。

### 5.5 驗收

- [ ] 新客：/paid → 卡片標「新客戶」→ /crm ok → Notion 出現檔案＋溝通記錄，關聯正確，状态=初次咨询。
- [ ] 同一客第二次預約：標「老客戶」→ 只多一筆溝通記錄，状态改服务中，不重複建檔。
- [ ] 生辰「1990/5/15 早上八點」→ 阳历=1990-05-15；「屬馬的」→ 阳历不寫，原文在溝通內容。
- [ ] Notion API 掛掉：/crm ok 回報失敗且佇列保留，重試可成功。
- [ ] 測試：mock httpx 對 crm_service 做單元測試；`parse_birth_date` 純函式測試（含民國年）。

---

## 6. 環境變數新增（config.py）

| 變數 | 功能 | 未設定時的退化行為 |
|---|---|---|
| `PUBLIC_BASE_URL` | F1 圖示、F3 連結組裝 | 卡片純文字版、無圖示 |
| `LIFF_ID` | F3 | 預約入口走文字版 date picker |
| `LOGIN_CHANNEL_ID` | F3 老師儲存時段的 token 驗證 | POST /api/slots 一律 403 |
| `CRON_SECRET` | F4 | /api/cron 一律 403（cron 靜默失效） |
| `NOTION_API_KEY` | F5 | CRM 功能整體停用 |

（Notion 兩個 data source ID 直接寫成 crm_service 常數即可，不必進 env——這個 bot 只服務這一個工作室。）

## 7. 行數預算與防肥大守則

| 新增/修改 | 預算 |
|---|---|
| `slots_service.py` | ≤ 100 行 |
| `crm_service.py` | ≤ 150 行 |
| `api.py` | ≤ 130 行 |
| `booking.html` | ≤ 450 行（含 CSS/JS） |
| `flex_messages.py` 淨增 | ≤ +80 行（confirmed card 改版是替換不是增加；`_field`/`_ornament_divider` 抽共用要讓 intake_card 同步瘦身） |
| `webhook.py` 淨增 | ≤ +90 行（/crm 指令 + LIFF 入口） |

守則：
1. 不引入新的正式依賴（Notion 用 httpx；LIFF 頁無框架）。
2. 每個功能都有「env 未設定 → 優雅退化」路徑，禁止 crash。
3. 卡片一律複用 `_make_text` / `_make_button` / `_field` / `_ornament_divider` / `_service_card` 這層積木，禁止再貼整坨 JSON 字典。
4. 測試跟功能同 commit；改動 keyword patterns 必跑 `test_keyword_router.py`（順序即優先權）。
5. 完成每個 F 後跑全套 `pytest`，並在 PR 描述附上驗收清單勾選狀態。

## 8. 不做的事（明確排除，避免範圍蔓延）

- 不做客人自助改期/取消（照舊：客人開口、老師 `/change`／`/no`）。
- 不做多管理員、權限系統。
- 不做付款金流串接；匯款回報三步機制照舊。
- 不做 Notion → Bot 的反向同步；Notion 端老師手動維護的欄位（玄学能量建议、文墨天機等）代碼永不觸碰。
- 不做 LIFF 內完成整個預約（LIFF 只發訊息回聊天室，狀態機留在 webhook）。

---

## 附錄 A — 已拍板的設計決策（2026-07-05 與業主確認）

| 議題 | 決定 |
|---|---|
| 開放時段管理 | **每月全手動開放**（無固定班表；月底 cron 提醒老師設定下月） |
| 時段總覽介面 | **LIFF 網頁月曆**（同頁兼老師編輯模式；保留文字流程當退化路徑） |
| CRM 同步 | **半自動**：/paid 後推預覽卡，老師按「寫入 CRM」才寫入 Notion |
| 確認卡片視覺 | **請帖風＋原有暖土配色 tokens**；圖示以 SVG 設計、輸出 PNG 託管（LINE Flex 不支援 SVG） |

## 附錄 B — 交付前業主 checklist（代碼以外）

1. Vercel env 補上 §6 五個變數。
2. LINE Developers：LINE Login channel + LIFF app（§3.5）。
3. Notion integration 建立並 share CRM 頁（§5.4）。
4. Vercel 專案確認 Cron Jobs 已啟用（部署後 Settings → Cron Jobs 可見）。
5. 檢視 `docs/preview-confirmed-card.html` 確認請帖卡視覺後，才進行 F1 實機發送測試。
