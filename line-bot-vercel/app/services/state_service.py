"""
簡易狀態管理 — 透過 Vercel KV (Upstash Redis) 儲存狀態。
用途：
  1. /off /on Bot 開關
  2. 記住用戶是否已看過預約原則說明
  3. 預約狀態管理（per-user，含付款流程）
  4. AI 對話速率限制（防止 Token 浪費）

預約狀態流程：
  pending → awaiting_payment → payment_reported → (完成刪除)
"""

import json
import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

KV_KEY_BOT_ACTIVE = "bot_active"


def _get_kv_headers() -> dict:
    settings = get_settings()
    return {"Authorization": f"Bearer {settings.kv_rest_api_token}"}


def _get_kv_url() -> str:
    settings = get_settings()
    return settings.kv_rest_api_url


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
        return [r.get("result") for r in response.json()]
    except Exception as e:
        logger.error("KV pipeline error: %s", e)
        return [None] * len(commands)


# ============================================================
# Bot 開關
# ============================================================
def is_bot_active() -> bool:
    """檢查 Bot 是否在運作中。預設為 True（開啟）。"""
    url = _get_kv_url()
    if not url:
        return True

    try:
        response = httpx.get(
            f"{url}/get/{KV_KEY_BOT_ACTIVE}",
            headers=_get_kv_headers(),
            timeout=3.0,
        )
        result = response.json().get("result")
        if result is None:
            return True
        return result != "off"
    except Exception as e:
        logger.error("KV read error: %s", e)
        return True


def set_bot_active(active: bool):
    """設定 Bot 開關狀態。開啟時自動清除所有「老師在線」已通知紀錄。"""
    url = _get_kv_url()
    if not url:
        logger.warning("KV not configured, cannot set bot state")
        return

    value = "on" if active else "off"
    try:
        httpx.get(
            f"{url}/set/{KV_KEY_BOT_ACTIVE}/{value}",
            headers=_get_kv_headers(),
            timeout=3.0,
        )
        logger.info("Bot state set to: %s", value)

        # 開啟 Bot 時，清除「老師在線」通知計數器
        if active:
            httpx.post(
                url,
                headers=_get_kv_headers(),
                json=["DEL", "bot_off_notified"],
                timeout=3.0,
            )
    except Exception as e:
        logger.error("KV write error: %s", e)


# ============================================================
# Bot 關閉時：記錄用戶是否已收過「老師在線」通知
# ============================================================
def has_been_notified_bot_off(user_id: str) -> bool:
    """檢查該用戶是否已經收過「老師在線」通知（本次關閉期間）。"""
    url = _get_kv_url()
    if not url:
        return False

    try:
        response = httpx.post(
            url,
            headers=_get_kv_headers(),
            json=["SISMEMBER", "bot_off_notified", user_id],
            timeout=3.0,
        )
        return response.json().get("result") == 1
    except Exception:
        return False


def mark_notified_bot_off(user_id: str):
    """標記該用戶已收過「老師在線」通知。"""
    url = _get_kv_url()
    if not url:
        return

    try:
        httpx.post(
            url,
            headers=_get_kv_headers(),
            json=["SADD", "bot_off_notified", user_id],
            timeout=3.0,
        )
    except Exception:
        pass


# ============================================================
# 預約原則：記住用戶是否已看過
# ============================================================
def has_seen_principles(user_id: str) -> bool:
    """檢查用戶是否已看過預約原則說明。"""
    url = _get_kv_url()
    if not url:
        return False

    try:
        response = httpx.get(
            f"{url}/get/principles:{user_id}",
            headers=_get_kv_headers(),
            timeout=3.0,
        )
        result = response.json().get("result")
        return result == "seen"
    except Exception:
        return False


def set_seen_principles(user_id: str):
    """記錄用戶已看過預約原則說明。"""
    url = _get_kv_url()
    if not url:
        return

    try:
        httpx.get(
            f"{url}/set/principles:{user_id}/seen",
            headers=_get_kv_headers(),
            timeout=3.0,
        )
    except Exception:
        pass


# ============================================================
# AI 對話速率限制（防止 Token 浪費）
# ============================================================
def is_ai_rate_limited(user_id: str, max_calls: int = 5, window_seconds: int = 600) -> bool:
    """
    檢查用戶是否超過 AI 對話限制。
    每位用戶在 window_seconds（預設 10 分鐘）內最多 max_calls（預設 5）次 AI 回覆。
    超過後回傳 True，不再呼叫 AI。
    """
    url = _get_kv_url()
    if not url:
        return False

    key = f"ai_rate:{user_id}"
    try:
        # 計數 +1
        resp = httpx.post(
            url,
            headers=_get_kv_headers(),
            json=["INCR", key],
            timeout=3.0,
        )
        count = resp.json().get("result", 0)

        # 第一次呼叫時設定自動過期
        if count == 1:
            httpx.post(
                url,
                headers=_get_kv_headers(),
                json=["EXPIRE", key, window_seconds],
                timeout=3.0,
            )

        return count > max_calls

    except Exception:
        return False


# ============================================================
# 預約管理（per-user，含狀態追蹤）
# ============================================================
# KV key:   booking:{user_id}
# KV value:  JSON {"d": "2026-03-15", "t": "14:00", "n": "小明", "s": "pending"}
#
# booking_queue: 預約佇列（Redis List），存放所有待處理的 user_id（按時間順序）
# 每位客人的預約資料仍存在 booking:{user_id}

def save_booking(user_id: str, date_str: str, time_str: str, user_name: str):
    """儲存新預約（狀態：pending）並加入佇列。（1 次 HTTP pipeline）"""
    data = json.dumps(
        {"d": date_str, "t": time_str, "n": user_name, "s": "pending"},
        ensure_ascii=False,
    )
    _pipeline([
        ["SET", f"booking:{user_id}", data],
        ["LREM", "booking_queue", 0, user_id],
        ["RPUSH", "booking_queue", user_id],
    ])


def get_booking(user_id: str) -> dict:
    """取得指定用戶的預約資料。回傳 None 代表沒有。"""
    url = _get_kv_url()
    if not url:
        return None

    try:
        response = httpx.get(
            f"{url}/get/booking:{user_id}",
            headers=_get_kv_headers(),
            timeout=3.0,
        )
        result = response.json().get("result")
        if not result:
            return None
        return json.loads(result)
    except Exception:
        return None


def update_booking_status(user_id: str, status: str, booking: dict = None):
    """
    更新預約狀態（pending → awaiting_payment → payment_reported）。
    可傳入已讀取的 booking 避免重複 GET。
    """
    if not booking:
        booking = get_booking(user_id)
    if not booking:
        return

    booking["s"] = status
    url = _get_kv_url()
    if not url:
        return

    data = json.dumps(booking, ensure_ascii=False)
    try:
        httpx.post(
            url,
            headers=_get_kv_headers(),
            json=["SET", f"booking:{user_id}", data],
            timeout=3.0,
        )
    except Exception as e:
        logger.error("Update booking status error: %s", e)


def delete_booking(user_id: str):
    """刪除預約紀錄並從佇列移除。（1 次 HTTP pipeline）"""
    _pipeline([
        ["DEL", f"booking:{user_id}"],
        ["LREM", "booking_queue", 0, user_id],
    ])


def get_booking_queue() -> list:
    """取得預約佇列中所有 user_id（按先後順序）。"""
    results = _pipeline([["LRANGE", "booking_queue", 0, -1]])
    return results[0] if results[0] else []


def get_queue_bookings_by_status(status: str) -> list:
    """
    取得佇列中指定狀態的預約列表（用 pipeline 批次查詢）。
    回傳 [{"user_id": ..., "booking": {...}}, ...]，按佇列順序。
    不論佇列多長，只發 2 次 HTTP 請求（1 次取佇列 + 1 次批次取所有預約）。
    """
    queue = get_booking_queue()
    if not queue:
        return []

    # 用 pipeline 一次取出所有預約資料
    commands = [["GET", f"booking:{uid}"] for uid in queue]
    booking_jsons = _pipeline(commands)

    results = []
    for uid, raw in zip(queue, booking_jsons):
        if raw:
            try:
                booking = json.loads(raw)
                if booking.get("s") == status:
                    results.append({"user_id": uid, "booking": booking})
            except (json.JSONDecodeError, TypeError):
                pass
    return results
