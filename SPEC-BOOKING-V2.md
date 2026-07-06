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
F1 預約確認卡片改版（請帖風）              — 獨立，先做
F2 手動開放時段（資料模型）                — 核心資料層
F3 時段總覽卡片＋ /open 指令開放時段（純 Flex）— 依賴 F2
F4 定期通知（Vercel Cron）                — 依賴 F2（讀開放時段）
F5 半自動 CRM 同步（Notion）              — 獨立，掛在 /paid 之後
```

> **2026-07-06 變更**：原 F3 為 LIFF 月曆頁，因 LINE 平台改版無法新建 LIFF app，
> 改為**全程聊天室內完成**：客人看 Flex 總覽卡片，老師用 `/open` 批次指令開放時段。
> 不需要任何網頁、LINE Login、外部授權。

建議實作順序：F1 → F2 → F3 → F4 → F5。每個 F 一個獨立 commit/PR，各自有驗收條件。

### 檔案增減總表

| 檔案 | 動作 | 說明 |
|---|---|---|
| `app/templates/flex_messages.py` | 修改 | F1 重寫 `booking_confirmed_card`；F3 新增 `schedule_overview_carousel`；F5 新增 `crm_preview_card` |
| `app/services/slots_service.py` | **新增** | F2 開放時段資料層＋ F3 `/open` 文字解析 |
| `app/services/calendar_service.py` | 修改 | F2 改讀開放時段，移除 `WEEKLY_SLOTS`；F3 新增整段 busy 查詢 |
| `app/services/crm_service.py` | **新增** | F5 Notion 讀寫 |
| `app/routers/api.py` | **新增** | F4 cron 端點（僅此一個端點） |
| `app/routers/webhook.py` | 修改 | F3 `/open /close /slots` 指令＋總覽關鍵字、F5 `/crm` 指令 |
| `app/config.py` | 修改 | 新增環境變數 |
| `public/icons/*.png` | **新增** | F1 圖示（SVG 源檔放 `docs/icons-src/`；Vercel 靜態檔優先於 rewrite，可直接伺服） |
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
- 允許開放的時間格點（`/open` 指令接受的合法值）：常數 `SELECTABLE_TIMES = ["13:00","14:00",...,"23:00","00:00"]`，集中在 `slots_service.py` 頂部，要改範圍只動這一行。

### 2.2 新模組 `app/services/slots_service.py`

```python
get_open_slots(month: str) -> dict             # 讀 open:{month}，無資料回 {}
add_open_slots(entries: list) -> bool          # 合併寫入 [(date, [times])]，/open 指令用；自動分月寫入
remove_open_slots(date: str, times: list|None) -> tuple[bool, list]
                                               # /close 用；times=None 整天。回傳 (成功, 因有預約而擋下的清單)
get_open_dates(days: int = 30) -> list         # 未來 N 天內有開放時段的日期（date picker 資料源）
slot_datetime(date_str, time_str) -> datetime  # 含跨午夜換算（00:00 → 隔日）
parse_open_lines(text) -> tuple[list, list]    # 純函式：解析 /open 多行文字 → (entries, 錯誤訊息列表)
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

## 3. F3 — 時段總覽卡片＋ `/open` 指令開放時段（純 Flex，無網頁）

> LIFF 因 LINE 平台改版無法新建，本功能**全部在聊天室內完成**：
> 老師用指令開放時段、客人看 Flex 總覽卡片。不需要 LINE Login、不需要任何網頁與外部授權。

### 3.1 老師端：`/open` / `/close` / `/slots` 指令

**`/open` 多行批次格式——一則訊息設定一整個月**：

```
/open
7/12 15 16 20
7/14 15 16
7/19 20 21 22 00
```

- 每行 `M/D` ＋空格分隔的小時（`15`＝15:00；也接受 `15:00`；`00`＝跨午夜隔日凌晨場，記在該行日期鍵下）。
- 年份自動推定：該日期若已過，視為明年（正常使用都是設定當月/下月）。
- **合併語義**：`/open` 把時段「加入」該日既有集合，不覆蓋整月——可以分多次補開。
- 只接受 `SELECTABLE_TIMES` 內的值；解析採**逐行容錯**：合法的行照常生效，錯誤的行逐行回報（「第 3 行看不懂：`7/x 25`」），不整包退回。
- 回覆成功摘要：本次開放的日期時段清單＋該月目前開放總數。
- 解析邏輯 `parse_open_lines()` 是純函式（見 §2.2），必須有完整單元測試（合法/非法混行、HH:MM 與 H 混用、跨年、非法時間值）。

**`/close 7/12 15 16`**：關閉該日指定時段；**`/close 7/12`**：整天關閉。
- 已被進行中預約（軟鎖定三狀態）佔用的時段**不可關閉**，回覆衝突清單，其餘照關。

**`/slots`**：老師查看本月＋下月的開放/已約狀態總表（純文字，複用 `/list` 的列表風格）：
```
✦ 7 月時段
7/12（日）15:00 16:00 20:00｜已約 1
7/14（二）15:00 16:00
✦ 8 月：尚未開放
```

三個指令都進 `ADMIN_COMMANDS`（keyword pattern：`^/open\b`、`^/close\b`、`^/slots$`，
注意 pattern 順序與既有指令的優先權，補 `test_keyword_router.py` 案例）。

### 3.2 客人端：時段總覽 carousel（Flex）

**觸發**：新關鍵字 `本週|下週|時段|什麼時候可以` → intent `schedule`（pattern 放在 booking 之前，補測試）。
回覆一個 **carousel，兩個 bubble：「本週」＋「下週」**（週一為一週之始）。

**Bubble 版式（沿用配色 tokens 與請帖設計語言）**：

```
┌────────────────────────────┐
│ HEADER 背景 #3D1F1F         │
│   本週時段                   │  GOLD, md, bold
│   7/7 – 7/13                │  DIVIDER 色, xs
├────────────────────────────┤
│ BODY 背景 BG_DARK           │
│  7/12（日）  15:00 16:00 2̶0̶:̶0̶0̶ │  ← 每天一行（見下）
│  7/14（二）  15:00 16:00      │
│   ────────  ✦  ────────     │  _ornament_divider()
│  [    我要預約    ]          │  ACCENT_RED 按鈕 → 文字「我要預約」
└────────────────────────────┘
```

- 每天一個 horizontal box：左側日期標籤 `TEXT_TITLE` sm bold（flex 固定寬），
  右側**單一 text 元件內用 span 陣列**呈現時段：
  - 可約：span `TEXT_WHITE`
  - 已被約走（軟鎖定/行事曆佔用）：span `TEXT_GREY` ＋ `"decoration": "line-through"`
  - 已過去的時段：不顯示
  - 時段之間以兩個空格分隔
- 沒有開放時段的日子**不列出**（卡片保持乾淨）；當週全部無開放/已過去 →
  該 bubble body 置中顯示 ✦＋「本週未開放時段」`TEXT_GREY`。
- 已被約走的判定：新增 `calendar_service.get_busy_map(start_date, end_date) -> {date: [times]}`
  ——**一次 freebusy 查詢涵蓋兩週**（timeMin=本週一、timeMax=下週日+1，只打一次 Google API），
  與 `get_taken_slots` 合併成「不可約」集合。無 Calendar 設定時只用軟鎖定。
- 實作為 `fm.schedule_overview_carousel(week1, week2)`，資料組裝放 webhook/服務層，
  卡片函式只負責渲染。

**與預約流程的關係**：總覽卡是「看」，預約照舊走「我要預約」→ date_picker → time_picker
（資料源已在 F2 換成 open slots）。總覽 bubble 底部的按鈕發文字「我要預約」接回既有流程。
歡迎詞（handle_follow）加一行「👉 輸入「時段」查看近兩週可預約時間」。

### 3.3 驗收

- [ ] `/open` 多行批次：混合合法/非法行，合法生效、非法逐行回報。
- [ ] `/close` 關閉已被預約的時段被擋下並列出衝突。
- [ ] `/slots` 總表與實際 KV 狀態一致。
- [ ] 客人輸入「時段」看到本週/下週兩頁卡片；已約時段呈灰色刪除線；
      無開放的一週顯示空狀態文案。
- [ ] 總覽卡與 date_picker 顯示的可約時段一致（同一套過濾鏈）。
- [ ] 全流程實測：/open 開時段 → 客人「時段」看到 → 預約 → 總覽卡該時段變刪除線。

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
| 今天是 25 號 且 下個月 `open:{YYYY-MM}` 為空 | 「✦ {M+1} 月時段尚未開放」＋ `/open` 使用範本＋**本月已開放清單**（方便照抄改日期後直接回傳） | 老師 |
| 今天是 1 號 | 本月總覽：開放 X 天 Y 時段、已成立預約 Z 筆（掃 done_queue + booking_queue） | 老師 |
| 明天有已成立（done）的預約 | 「明日預約提醒：{date_label} {time} ✦ 屆時見」 | **每位客人** |
| 明天有已成立的預約 | 「明日行程：N 筆——{清單}」 | 老師 |

25 號提醒文案範例（重點是老師能直接複製修改）：

```
✦ 8 月時段尚未開放
回覆 /open 開放時段，每行一天，例如：

/open
8/3 15 16 20
8/5 15 16

參考：7 月開放的是——
7/12（日）15 16 20
7/14（二）15 16
```

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
| `PUBLIC_BASE_URL` | F1 圖示網址組裝（**結尾不含斜線**） | 卡片純文字版、無圖示 |
| `CRON_SECRET` | F4 | /api/cron 一律 403（cron 靜默失效） |
| `NOTION_API_KEY` | F5 | CRM 功能整體停用 |

（Notion 兩個 data source ID 直接寫成 crm_service 常數即可，不必進 env——這個 bot 只服務這一個工作室。
原規劃的 `LIFF_ID`、`LOGIN_CHANNEL_ID` 因改走純 Flex 已**不再需要**；
若 config.py 已加過請移除，業主先前建立的 LINE Login channel 可閒置或刪除。）

## 7. 行數預算與防肥大守則

| 新增/修改 | 預算 |
|---|---|
| `slots_service.py` | ≤ 140 行（含 `/open` 解析純函式） |
| `crm_service.py` | ≤ 150 行 |
| `api.py` | ≤ 60 行（只剩 cron 端點） |
| `flex_messages.py` 淨增 | ≤ +130 行（confirmed card 是替換不是增加；新增總覽 carousel 與 crm 預覽卡；`_field`/`_ornament_divider` 抽共用要讓 intake_card 同步瘦身） |
| `webhook.py` 淨增 | ≤ +130 行（/open /close /slots /crm 指令＋schedule 意圖） |

守則：
1. 不引入新的正式依賴（Notion 用 httpx）。
2. 每個功能都有「env 未設定 → 優雅退化」路徑，禁止 crash。
3. 卡片一律複用 `_make_text` / `_make_button` / `_field` / `_ornament_divider` / `_service_card` 這層積木，禁止再貼整坨 JSON 字典。
4. 測試跟功能同 commit；改動 keyword patterns 必跑 `test_keyword_router.py`（順序即優先權）。
5. 完成每個 F 後跑全套 `pytest`，並在 PR 描述附上驗收清單勾選狀態。

## 8. 不做的事（明確排除，避免範圍蔓延）

- 不做客人自助改期/取消（照舊：客人開口、老師 `/change`／`/no`）。
- 不做多管理員、權限系統。
- 不做付款金流串接；匯款回報三步機制照舊。
- 不做 Notion → Bot 的反向同步；Notion 端老師手動維護的欄位（玄学能量建议、文墨天機等）代碼永不觸碰。
- **不做任何網頁介面**（LIFF / LINE MINI App / 一般網頁都不做）——所有互動留在聊天室內；
  `public/` 只放靜態圖示。若日後 LINE MINI App 門檻降低，可從 git 歷史（commit 0bfc091 的 §3）
  取回原 LIFF 月曆設計另開規格。

---

## 附錄 A — 已拍板的設計決策

2026-07-05 首輪確認：

| 議題 | 決定 |
|---|---|
| 開放時段管理 | **每月全手動開放**（無固定班表；月底 cron 提醒老師設定下月） |
| 時段總覽介面 | ~~LIFF 網頁月曆~~（見下方 07-06 變更） |
| CRM 同步 | **半自動**：/paid 後推預覽卡，老師按「寫入 CRM」才寫入 Notion |
| 確認卡片視覺 | **請帖風＋原有暖土配色 tokens**；圖示以 SVG 設計、輸出 PNG 託管（LINE Flex 不支援 SVG） |

2026-07-06 變更（LINE 平台改版導致無法新建 LIFF app）：

| 議題 | 決定 |
|---|---|
| 時段總覽介面 | **純 Flex 卡片**：客人用「本週/下週」carousel 總覽，老師用 `/open` 多行批次指令開放時段（§3 已全面改寫） |
| Google Calendar 串接 | **保留**。純後端使用（freebusy 擋私人行程＋/paid 建立事件），預約者從頭到尾接觸不到業主的日曆，無隱私疑慮 |

## 附錄 B — 交付前業主 checklist（代碼以外）

1. Vercel env 補上 §6 三個變數（`PUBLIC_BASE_URL` 結尾不含斜線；改完 env 要 Redeploy）。
2. Notion integration 建立並 share CRM 頁（§5.4）。**若 API key 曾在任何對話中貼出，必須先 Regenerate 再填入。**
3. Vercel 專案確認 Cron Jobs 已啟用（部署後 Settings → Cron Jobs 可見）。
4. 檢視 `docs/preview-confirmed-card.html` 確認請帖卡視覺後，才進行 F1 實機發送測試。
5. （已不需要）先前建立的 LINE Login channel（ID 2009266106）可閒置或刪除，本規格不再使用。
