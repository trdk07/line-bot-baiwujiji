"""
簡易狀態管理 — 透過 Vercel KV (Upstash Redis) 儲存狀態。
用途：
  1. /off /on Bot 開關
  2. 記住用戶是否已看過預約原則說明
  3. 暫存待確認的預約（管理員 /ok /no）
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
# 待確認預約：暫存客人的預約申請
# ============================================================
def save_pending_booking(user_id: str, date_str: str, time_str: str, user_name: str):
    """儲存一筆待確認的預約。"""
    url = _get_kv_url()
    if not url:
        return

    data = json.dumps(
        {"u": user_id, "d": date_str, "t": time_str, "n": user_name},
        ensure_ascii=False,
    )
    try:
        httpx.post(
            url,
            headers=_get_kv_headers(),
            json=["SET", "pending_booking", data],
            timeout=3.0,
        )
    except Exception as e:
        logger.error("Save pending booking error: %s", e)


def get_pending_booking() -> dict:
    """取得待確認的預約，回傳 None 代表沒有。"""
    url = _get_kv_url()
    if not url:
        return None

    try:
        response = httpx.get(
            f"{url}/get/pending_booking",
            headers=_get_kv_headers(),
            timeout=3.0,
        )
        result = response.json().get("result")
        if not result:
            return None
        return json.loads(result)
    except Exception:
        return None


def delete_pending_booking():
    """刪除待確認的預約。"""
    url = _get_kv_url()
    if not url:
        return

    try:
        httpx.post(
            url,
            headers=_get_kv_headers(),
            json=["DEL", "pending_booking"],
            timeout=3.0,
        )
    except Exception:
        pass
