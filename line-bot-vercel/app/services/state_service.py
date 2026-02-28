"""
簡易狀態管理 — 透過 Vercel KV (Upstash Redis) 儲存 Bot 開關狀態。
用途：/off 關閉 Bot、/on 開啟 Bot。
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


def is_bot_active() -> bool:
    """檢查 Bot 是否在運作中。預設為 True（開啟）。"""
    url = _get_kv_url()
    if not url:
        return True  # 沒設定 KV 就預設開著

    try:
        response = httpx.get(
            f"{url}/get/{KV_KEY_BOT_ACTIVE}",
            headers=_get_kv_headers(),
            timeout=3.0,
        )
        result = response.json().get("result")
        if result is None:
            return True  # 沒有值就預設開著
        return result != "off"
    except Exception as e:
        logger.error("KV read error: %s", e)
        return True  # 出錯就預設開著，不影響服務


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
