"""
簡易狀態管理 — 透過 Vercel KV (Upstash Redis) 儲存狀態。
用途：
  1. /off /on Bot 開關
  2. 記住用戶是否已看過預約原則說明
"""

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
        return False  # 沒有 KV 就每次都顯示

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
