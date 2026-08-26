"""
簡易狀態管理 — 透過 Vercel KV (Upstash Redis) 儲存狀態。
用途：
  1. /off /on Bot 開關
  2. 記住用戶是否已看過預約原則說明
  3. 預約狀態管理（per-user，含付款流程）

預約狀態流程：
  pending → awaiting_payment → payment_reported → (完成刪除)
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

KV_KEY_BOT_ACTIVE = "bot_active"


def _entry_user_id(ref: str) -> str:
    """從佇列條目（'user_id|booking_id'）中提取 user_id。"""
    return ref.split("|")[0]


def _get_kv_headers() -> dict:
    settings = get_settings()
    return {"Authorization": f"Bearer {settings.kv_rest_api_token}"}


def _get_kv_url() -> str:
    settings = get_settings()
    return settings.kv_rest_api_url


def kv_cmd(*args) -> Any:
    """
    送出單一 Redis 指令（Upstash REST POST /）。
    例如 kv_cmd("SET", "key", "val", "EX", 60)、kv_cmd("DEL", "key")。
    KV 未設定、HTTP 非 200、或例外時皆回傳 None 並記錄錯誤。
    """
    url = _get_kv_url()
    if not url:
        return None
    try:
        response = httpx.post(url, headers=_get_kv_headers(), json=list(args), timeout=3.0)
        if response.status_code != 200:
            logger.error("KV command %s failed, HTTP %d: %s", args[0] if args else "?", response.status_code, response.text)
            return None
        return response.json().get("result")
    except Exception as e:
        logger.error("KV command %s error: %s", args[0] if args else "?", e)
        return None


def kv_get(key: str) -> str | None:
    """語法糖：kv_cmd("GET", key)。"""
    return kv_cmd("GET", key)


def _pipeline(commands: list) -> list:
    """
    Upstash REST Pipeline：一次 HTTP 請求送出多個 Redis 指令。
    commands: [["SET", "key", "val"], ["GET", "key"], ...]
    回傳: 每個指令的 result 列表。
    """
    url = _get_kv_url()
    if not url:
        return [None] * len(commands)

    try:
        response = httpx.post(
            f"{url}/pipeline",
            headers=_get_kv_headers(),
            json=commands,
            timeout=5.0,
        )
        if response.status_code != 200:
            logger.error("KV pipeline HTTP error %d: %s", response.status_code, response.text)
            return [None] * len(commands)
        return [r.get("result") for r in response.json()]
    except Exception as e:
        logger.error("KV pipeline error: %s", e)
        return [None] * len(commands)


# ============================================================
# Bot 開關
# ============================================================
def is_bot_active() -> bool:
    """檢查 Bot 是否在運作中。預設為 True（開啟）。"""
    return kv_get(KV_KEY_BOT_ACTIVE) != "off"


def set_bot_active(active: bool):
    """設定 Bot 開關狀態。開啟時自動清除所有「老師在線」已通知紀錄。"""
    if not _get_kv_url():
        logger.warning("KV not configured, cannot set bot state")
        return

    value = "on" if active else "off"
    kv_cmd("SET", KV_KEY_BOT_ACTIVE, value)
    logger.info("Bot state set to: %s", value)

    if active:
        kv_cmd("DEL", "bot_off_notified")


# ============================================================
# Bot 關閉時：記錄用戶是否已收過「老師在線」通知
# ============================================================
def has_been_notified_bot_off(user_id: str) -> bool:
    """檢查該用戶是否已經收過「老師在線」通知（本次關閉期間）。"""
    return kv_cmd("SISMEMBER", "bot_off_notified", user_id) == 1


def mark_notified_bot_off(user_id: str):
    """標記該用戶已收過「老師在線」通知。"""
    kv_cmd("SADD", "bot_off_notified", user_id)


CLEAR_CONFIRM_TTL = 60  # /clear 二次確認有效秒數


def set_clear_confirm_pending():
    """標記 /clear 已發出，等待管理員在 60 秒內輸入 /clear yes 確認。"""
    kv_cmd("SET", "clear_confirm_pending", "1", "EX", CLEAR_CONFIRM_TTL)


def has_clear_confirm_pending() -> bool:
    """檢查是否有待確認的 /clear。"""
    return kv_get("clear_confirm_pending") == "1"


def clear_confirm_pending():
    """清除 /clear 二次確認狀態。"""
    kv_cmd("DEL", "clear_confirm_pending")


# ============================================================
# 預約原則：記住用戶是否已看過
# ============================================================
def has_seen_principles(user_id: str) -> bool:
    """檢查用戶是否已看過預約原則說明。"""
    return kv_get(f"principles:{user_id}") == "seen"


def set_seen_principles(user_id: str):
    """記錄用戶已看過預約原則說明。"""
    kv_cmd("SET", f"principles:{user_id}", "seen")


# ============================================================
# 預約管理（支援同一用戶多筆預約）
# ============================================================
# KV key:   booking:{user_id|booking_id}  (booking_id = 毫秒時間戳)
# KV value:  JSON {"d": "2026-03-15", "t": "14:00", "n": "小明", "s": "pending", "o": "B-2026-0012"}
#
# booking_queue: 預約佇列（Redis List），存放 ref（user_id|booking_id），按時間順序

_TW_TZ = timezone(timedelta(hours=8))

ORDER_PREFIX_BOOKING = "B"  # 預約諮詢；未來點燈 L、法會 F 共用同一組流水號


def next_order_no(prefix: str = ORDER_PREFIX_BOOKING) -> str:
    """產生對外訂單編號（例如 B-2026-0012），給客人看與對帳用。

    以年度流水號遞增（KV INCR，原子操作不會重號）；KV 未設定時回傳空字串，
    呼叫端一律以「有值才顯示」處理。
    """
    year = datetime.now(_TW_TZ).year
    seq = kv_cmd("INCR", f"order_seq:{year}")
    if seq is None:
        return ""
    return f"{prefix}-{year}-{int(seq):04d}"


def save_booking(user_id: str, date_str: str, time_str: str, user_name: str) -> str:
    """儲存新預約（狀態：pending）並加入佇列。每筆預約有獨立 key。

    回傳對外訂單編號（KV 未設定時為空字串）。
    """
    booking_id = str(int(time.time() * 1000))
    ref = f"{user_id}|{booking_id}"
    order_no = next_order_no()
    booking = {"d": date_str, "t": time_str, "n": user_name, "s": "pending"}
    if order_no:
        booking["o"] = order_no
    data = json.dumps(booking, ensure_ascii=False)
    _pipeline([
        ["SET", f"booking:{ref}", data],
        ["RPUSH", "booking_queue", ref],
    ])
    incr_monthly_stat("new")
    return order_no


def update_booking_status(ref: str, status: str, booking: dict = None) -> bool:
    """
    更新預約狀態（pending → awaiting_payment → payment_reported）。
    ref 為佇列條目（user_id|booking_id 或舊版 user_id）。
    可傳入已讀取的 booking 避免重複 GET。
    回傳 True 代表寫入成功，False 代表失敗。
    """
    if not booking:
        raw = kv_get(f"booking:{ref}")
        if not raw:
            return False
        try:
            booking = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return False

    booking["s"] = status
    booking["u"] = int(time.time())  # 狀態變更時間，供逾時掃描（cron）計算等待時長
    data = json.dumps(booking, ensure_ascii=False)
    return kv_cmd("SET", f"booking:{ref}", data) == "OK"


def delete_booking(ref: str):
    """刪除預約紀錄並從佇列移除。ref 為佇列條目（user_id|booking_id）。"""
    _pipeline([
        ["DEL", f"booking:{ref}"],
        ["LREM", "booking_queue", 0, ref],
    ])


def _fetch_queue_with_bookings() -> tuple[list, list]:
    """
    內部輔助：取得佇列 ref 列表與對應的 booking 資料。
    回傳 (queue, booking_list)，booking_list 與 queue 等長。
    """
    queue = kv_cmd("LRANGE", "booking_queue", 0, -1) or []
    if not queue:
        return [], []

    booking_jsons = _pipeline([["GET", f"booking:{ref}"] for ref in queue])
    return queue, booking_jsons


def get_queue_bookings_by_status(status: str) -> list:
    """
    取得佇列中指定狀態的預約列表（用 pipeline 批次查詢）。
    回傳 [{"ref": ..., "user_id": ..., "booking": {...}}, ...]，按佇列順序。
    """
    queue, booking_jsons = _fetch_queue_with_bookings()
    if not queue:
        return []

    results = []
    for ref, raw in zip(queue, booking_jsons):
        if raw:
            try:
                booking = json.loads(raw)
                if booking.get("s") == status:
                    results.append({
                        "ref": ref,
                        "user_id": _entry_user_id(ref),
                        "booking": booking,
                    })
            except (json.JSONDecodeError, TypeError):
                pass
    return results


def get_user_booking_by_status(user_id: str, status: str) -> dict | None:
    """找出指定用戶中符合狀態的第一筆預約（按佇列順序，最早的優先）。
    回傳 {"ref": ..., "user_id": ..., "booking": {...}} 或 None。
    """
    entries = get_queue_bookings_by_status(status)
    for entry in entries:
        if entry["user_id"] == user_id:
            return entry
    return None


DONE_TTL = 30 * 24 * 60 * 60  # 30 天（秒）
INTAKE_PENDING_TTL = 24 * 60 * 60  # 24 小時（秒）


def set_intake_pending(user_id: str):
    """預約後標記用戶需填寫諮詢資料，24 小時有效。"""
    kv_cmd("SET", f"intake_pending:{user_id}", "1", "EX", INTAKE_PENDING_TTL)


def has_intake_pending(user_id: str) -> bool:
    """檢查用戶是否在等待填寫諮詢資料。"""
    return kv_get(f"intake_pending:{user_id}") == "1"


def clear_intake_pending(user_id: str):
    """清除諮詢資料等待狀態。"""
    kv_cmd("DEL", f"intake_pending:{user_id}")


def clear_intake_state(user_id: str):
    """一次清除諮詢資料流程狀態；不清除已完成的 intake_data。"""
    _pipeline([
        ["DEL", f"intake_pending:{user_id}"],
        ["DEL", f"intake_step:{user_id}"],
        ["DEL", f"intake_draft:{user_id}"],
        ["DEL", f"intake_reprompted:{user_id}"],
    ])


def mark_intake_reprompted(user_id: str) -> bool:
    """標記本輪 intake pending 已重發過卡片；首次標記回 True。"""
    return kv_cmd("SET", f"intake_reprompted:{user_id}", "1", "NX", "EX", INTAKE_PENDING_TTL) == "OK"


def get_message_context(user_id: str) -> tuple:
    """
    合併查詢每則訊息都會用到的兩個狀態：Bot 是否運作中、該用戶是否在等待
    填寫諮詢資料。用一次 pipeline HTTP 請求取代兩次獨立查詢，降低延遲與
    KV 用量。回傳 (bot_active, intake_pending)。
    """
    results = _pipeline([
        ["GET", KV_KEY_BOT_ACTIVE],
        ["GET", f"intake_pending:{user_id}"],
    ])
    bot_active = results[0] != "off"
    intake_pending = results[1] == "1"
    return bot_active, intake_pending


INTAKE_DATA_TTL = 30 * 24 * 60 * 60  # 30 天（秒）



def set_intake_step(user_id: str, step: str):
    """設定諮詢資料逐步填寫步驟：name / birth / question。"""
    kv_cmd("SET", f"intake_step:{user_id}", step, "EX", INTAKE_PENDING_TTL)


def get_intake_step(user_id: str) -> str:
    """取得目前諮詢資料填寫步驟。"""
    return kv_get(f"intake_step:{user_id}") or ""


def clear_intake_step(user_id: str):
    """清除諮詢資料填寫步驟。"""
    kv_cmd("DEL", f"intake_step:{user_id}")


def save_intake_draft(user_id: str, **fields):
    """暫存逐步填寫中的諮詢資料。"""
    raw = kv_get(f"intake_draft:{user_id}")
    try:
        data = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        data = {}
    data.update({k: v for k, v in fields.items() if v is not None})
    kv_cmd("SET", f"intake_draft:{user_id}", json.dumps(data, ensure_ascii=False), "EX", INTAKE_PENDING_TTL)


def get_intake_draft(user_id: str) -> dict:
    """取得逐步填寫中的諮詢資料。"""
    raw = kv_get(f"intake_draft:{user_id}")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def clear_intake_draft(user_id: str):
    """清除逐步填寫暫存資料。"""
    kv_cmd("DEL", f"intake_draft:{user_id}")

def save_intake_data(user_id: str, name: str = "", birth_date: str = "", question: str = ""):
    """儲存諮詢資料（姓名、出生年月日、問題），30 天有效。"""
    data = json.dumps({"n": name, "b": birth_date, "q": question}, ensure_ascii=False)
    kv_cmd("SET", f"intake_data:{user_id}", data, "EX", INTAKE_DATA_TTL)


def get_intake_data(user_id: str) -> tuple:
    """取得諮詢資料，回傳 (name, birth_date, question)。找不到回傳 ("", "", "")。"""
    raw = kv_get(f"intake_data:{user_id}")
    if raw:
        try:
            data = json.loads(raw)
            return data.get("n", ""), data.get("b", ""), data.get("q", "")
        except (json.JSONDecodeError, TypeError):
            pass
    return "", "", ""


def clear_intake_data(user_id: str):
    """清除諮詢資料。"""
    kv_cmd("DEL", f"intake_data:{user_id}")


def save_done_booking(ref: str, booking: dict, cal_event_id: str):
    """預約完成後存入 done 區，保留 30 天供改期使用。"""
    done_data = {**booking, "s": "done", "cal_id": cal_event_id}
    data = json.dumps(done_data, ensure_ascii=False)
    _pipeline([
        ["SET", f"done:{ref}", data, "EX", DONE_TTL],
        ["RPUSH", "done_queue", ref],
    ])


def delete_done_booking(ref: str):
    """刪除已完成預約紀錄並從 done 佇列移除。"""
    _pipeline([
        ["DEL", f"done:{ref}"],
        ["LREM", "done_queue", 0, ref],
    ])


def get_all_done_bookings() -> list:
    """取得所有完成的預約（30 天內）。"""
    refs = kv_cmd("LRANGE", "done_queue", 0, -1) or []
    if not refs:
        return []

    raws = _pipeline([["GET", f"done:{ref}"] for ref in refs])
    results, stale = [], []
    for ref, raw in zip(refs, raws):
        if raw:
            try:
                results.append({
                    "ref": ref,
                    "user_id": _entry_user_id(ref),
                    "booking": json.loads(raw),
                })
            except (json.JSONDecodeError, TypeError):
                stale.append(ref)
        else:
            stale.append(ref)
    if stale:
        _pipeline([["LREM", "done_queue", 0, r] for r in stale])
    return results


def _update_datetime(key_prefix: str, ref: str, date_str: str, time_str: str, booking: dict, ttl: int = None) -> bool:
    """更新指定 key（booking: 或 done:）的日期和時間，可選擇重設 TTL。"""
    booking["d"] = date_str
    booking["t"] = time_str
    data = json.dumps(booking, ensure_ascii=False)
    args = ["SET", f"{key_prefix}:{ref}", data]
    if ttl:
        args += ["EX", ttl]
    return kv_cmd(*args) == "OK"


def update_booking_datetime(ref: str, date_str: str, time_str: str, booking: dict) -> bool:
    """更新進行中預約的日期和時間。"""
    return _update_datetime("booking", ref, date_str, time_str, booking)


def update_done_booking_datetime(ref: str, date_str: str, time_str: str, booking: dict) -> bool:
    """更新已完成預約的日期和時間（重設 30 天 TTL）。"""
    return _update_datetime("done", ref, date_str, time_str, booking, ttl=DONE_TTL)


def get_all_queue_bookings() -> list:
    """
    取得佇列中所有預約（不論狀態）。
    用於 /list 指令顯示總覽。
    回傳 [{"ref": ..., "user_id": ..., "booking": {...}}, ...]，按佇列順序。
    """
    queue, booking_jsons = _fetch_queue_with_bookings()
    if not queue:
        return []

    results = []
    for ref, raw in zip(queue, booking_jsons):
        if raw:
            try:
                booking = json.loads(raw)
                results.append({
                    "ref": ref,
                    "user_id": _entry_user_id(ref),
                    "booking": booking,
                })
            except (json.JSONDecodeError, TypeError):
                pass
    return results


ACTIVE_STATUSES = {"pending", "awaiting_payment", "payment_reported"}


def get_taken_slots(date_str: str) -> set:
    """
    取得指定日期已被進行中預約佔用的時段（軟鎖定）。
    包含 pending / awaiting_payment / payment_reported 狀態，
    避免管理員確認收款（建立日曆事件）前，該時段被其他客人重複預約。
    回傳時間字串集合，例如 {"14:00", "19:00"}。
    """
    entries = get_all_queue_bookings()
    return {
        e["booking"]["t"]
        for e in entries
        if e["booking"].get("d") == date_str and e["booking"].get("s") in ACTIVE_STATUSES
    }


# ============================================================
# 顧客檔案（永久累積，不設 TTL）
# ============================================================
# KV key:   customer:{user_id}
# KV value: JSON {"n": 顯示名稱, "c": 完成次數, "first": 首次日期, "last": 最近日期}
#
# done:{ref} 只保留 30 天，這裡另存一份永久的累積紀錄，
# 讓 Bot 與預約網頁能認出回頭客（歡迎回來、第 N 次、上次日期）。

def record_customer_visit(user_id: str, name: str, date_str: str):
    """預約完成（/paid）時累積顧客檔案：次數 +1、更新最近預約日期。

    同時把 user_id 加進 customer_index（Set），讓後台的顧客名冊
    可以列出所有累積過的顧客（Redis 無法用前綴撈 key，需自建索引）。
    """
    profile = get_customer_profile(user_id) or {}
    profile["n"] = name or profile.get("n", "")
    profile["c"] = int(profile.get("c", 0)) + 1
    profile.setdefault("first", date_str)
    profile["last"] = date_str
    _pipeline([
        ["SET", f"customer:{user_id}", json.dumps(profile, ensure_ascii=False)],
        ["SADD", "customer_index", user_id],
    ])


def get_all_customers() -> list:
    """後台顧客名冊：所有累積過的顧客檔案，按最近預約日期新到舊排序。

    回傳 [{"u": user_id, "n": 名稱, "c": 次數, "first": ..., "last": ...}, ...]。
    """
    user_ids = kv_cmd("SMEMBERS", "customer_index") or []
    if not user_ids:
        return []
    raws = _pipeline([["GET", f"customer:{uid}"] for uid in user_ids])
    customers = []
    for uid, raw in zip(user_ids, raws):
        if not raw:
            continue
        try:
            profile = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        customers.append({
            "u": uid,
            "n": profile.get("n", ""),
            "c": int(profile.get("c", 0)),
            "first": profile.get("first", ""),
            "last": profile.get("last", ""),
        })
    customers.sort(key=lambda item: item["last"], reverse=True)
    return customers


def get_customer_profile(user_id: str) -> dict | None:
    """取得顧客累積檔案。從未完成過預約（或 KV 未設定）回傳 None。"""
    raw = kv_get(f"customer:{user_id}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def customer_link_sig(user_id: str) -> str:
    """個人化預約連結的簽章：讓 /api/me 能驗證 uid 沒被竄改。

    連結只會私訊給該客人本人；簽章用 LINE channel secret 衍生，
    避免有人改網址上的 uid 查到別人的累積資料。
    """
    import hashlib
    import hmac as hmac_mod

    secret = get_settings().line_channel_secret.encode("utf-8")
    return hmac_mod.new(secret, f"me:{user_id}".encode("utf-8"), hashlib.sha256).hexdigest()[:16]


# ============================================================
# 月度彙總（儀表板用，永久保存）
# ============================================================
# KV key: stats:{YYYY-MM}:{field}，各自用 INCR 原子遞增。
# 欄位：new=新預約申請、done=完成預約（/paid）、released=逾時自動釋放。
# done: 紀錄只留 30 天，這裡的彙總是儀表板歷史數字的永久來源。

STAT_FIELDS = ["new", "done", "released"]


def incr_monthly_stat(field: str):
    """當月統計 +1。KV 未設定時靜默略過。"""
    month = datetime.now(_TW_TZ).strftime("%Y-%m")
    kv_cmd("INCR", f"stats:{month}:{field}")


def get_monthly_stats(months: list) -> list:
    """批次取得多個月份的彙總數字。回傳 [{"month": "2026-08", "new": 3, ...}, ...]。"""
    if not months:
        return []
    commands = [["GET", f"stats:{m}:{f}"] for m in months for f in STAT_FIELDS]
    raws = _pipeline(commands)
    results = []
    for i, month in enumerate(months):
        row = {"month": month}
        for j, field in enumerate(STAT_FIELDS):
            raw = raws[i * len(STAT_FIELDS) + j]
            row[field] = int(raw) if raw else 0
        results.append(row)
    return results


CRM_QUEUE_TTL = 7 * 24 * 60 * 60


def enqueue_crm(payload: dict) -> bool:
    data = json.dumps(payload, ensure_ascii=False)
    results = _pipeline([["RPUSH", "crm_queue", data], ["EXPIRE", "crm_queue", CRM_QUEUE_TTL]])
    return results[0] is not None


def get_crm_queue() -> list:
    raws = kv_cmd("LRANGE", "crm_queue", 0, -1) or []
    items = []
    for i, raw in enumerate(raws, 1):
        try:
            items.append({"index": i, "raw": raw, "payload": json.loads(raw)})
        except (json.JSONDecodeError, TypeError):
            pass
    return items



def update_crm_booking_datetime(user_id: str, date_str: str, time_str: str) -> int:
    """更新 CRM 待確認佇列中同一 LINE 用戶的預約日期時間，回傳更新筆數。"""
    raws = kv_cmd("LRANGE", "crm_queue", 0, -1) or []
    if not raws:
        return 0
    updated = 0
    commands = []
    for raw in raws:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if payload.get("u") != user_id:
            continue
        payload["d"] = date_str
        payload["t"] = time_str
        commands.append(["LREM", "crm_queue", 1, raw])
        commands.append(["RPUSH", "crm_queue", json.dumps(payload, ensure_ascii=False)])
        updated += 1
    if commands:
        commands.append(["EXPIRE", "crm_queue", CRM_QUEUE_TTL])
        _pipeline(commands)
    return updated

def remove_crm_booking(user_id: str, date_str: str, time_str: str) -> int:
    """移除同一 LINE 用戶、同一日期時間的 CRM 待確認資料，回傳移除筆數。"""
    raws = kv_cmd("LRANGE", "crm_queue", 0, -1) or []
    commands, removed = [], 0
    for raw in raws:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if payload.get("u") == user_id and payload.get("d") == date_str and payload.get("t") == time_str:
            commands.append(["LREM", "crm_queue", 1, raw])
            removed += 1
    if commands:
        _pipeline(commands)
    return removed


def remove_crm_queue_item(raw: str) -> bool:
    return kv_cmd("LREM", "crm_queue", 1, raw) is not None
