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
    """設定 Bot 開關狀態。"""
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
    except Exception as e:
        logger.error("KV write error: %s", e)


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
# admin_context: 記住管理員目前正在處理哪位客人的預約

def save_booking(user_id: str, date_str: str, time_str: str, user_name: str):
    """儲存新預約（狀態：pending）。"""
    url = _get_kv_url()
    if not url:
        return

    data = json.dumps(
        {"d": date_str, "t": time_str, "n": user_name, "s": "pending"},
        ensure_ascii=False,
    )
    try:
        httpx.post(
            url,
            headers=_get_kv_headers(),
            json=["SET", f"booking:{user_id}", data],
            timeout=3.0,
        )
    except Exception as e:
        logger.error("Save booking error: %s", e)


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


def update_booking_status(user_id: str, status: str):
    """更新預約狀態（pending → awaiting_payment → payment_reported）。"""
    booking = get_booking(user_id)
    if not booking:
        return

    booking["s"] = status
    url = _get_kv_url()
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
    """刪除預約紀錄。"""
    url = _get_kv_url()
    if not url:
        return

    try:
        httpx.post(
            url,
            headers=_get_kv_headers(),
            json=["DEL", f"booking:{user_id}"],
            timeout=3.0,
        )
    except Exception:
        pass


def set_admin_context(user_id: str):
    """記住管理員目前正在處理哪位客人的預約。"""
    url = _get_kv_url()
    if not url:
        return

    try:
        httpx.post(
            url,
            headers=_get_kv_headers(),
            json=["SET", "admin_context", user_id],
            timeout=3.0,
        )
    except Exception:
        pass


def get_admin_context() -> str:
    """取得管理員目前處理中的客人 user_id。"""
    url = _get_kv_url()
    if not url:
        return None

    try:
        response = httpx.get(
            f"{url}/get/admin_context",
            headers=_get_kv_headers(),
            timeout=3.0,
        )
        return response.json().get("result")
    except Exception:
        return None
