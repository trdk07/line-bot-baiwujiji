"""
百無禁忌 LINE Bot — FastAPI 應用程式入口。
"""

import json
import logging
from fastapi import FastAPI
from app.routers import webhook

logger = logging.getLogger(__name__)

app = FastAPI(
    title="百無禁忌 LINE Bot",
    version="0.1.0",
)

# --- 掛載路由 ---
app.include_router(webhook.router)


# --- Health Check ---
@app.get("/")
async def root():
    return {"status": "ok", "message": "百無禁忌 LINE Bot is running"}


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": app.version}


# --- Google Calendar 診斷 ---
@app.get("/debug/calendar")
async def debug_calendar():
    """診斷 Google Calendar 連線問題。"""
    from app.config import get_settings
    settings = get_settings()
    result = {}

    # 1. 檢查環境變數是否存在
    result["has_service_account_json"] = bool(settings.google_service_account_json)
    result["has_calendar_id"] = bool(settings.google_calendar_id)
    result["calendar_id"] = settings.google_calendar_id or "(未設定)"

    if not settings.google_service_account_json:
        result["error"] = "GOOGLE_SERVICE_ACCOUNT_JSON 未設定"
        return result

    # 2. 嘗試解析 JSON
    try:
        creds_info = json.loads(settings.google_service_account_json)
        result["json_parse"] = "OK"
        result["service_account_email"] = creds_info.get("client_email", "(找不到)")
        result["project_id"] = creds_info.get("project_id", "(找不到)")
        has_private_key = "private_key" in creds_info
        result["has_private_key"] = has_private_key
        if has_private_key:
            pk = creds_info["private_key"]
            result["private_key_starts_with"] = pk[:30]
            result["private_key_has_literal_backslash_n"] = "\\n" in pk
    except Exception as e:
        result["json_parse"] = f"失敗：{e}"
        return result

    # 3. 嘗試建立 Calendar 服務
    from app.services.calendar_service import _get_calendar_service
    service, init_error = _get_calendar_service()
    if not service:
        result["service_build"] = f"失敗：{init_error}"
        return result
    result["service_build"] = "OK"

    # 4. 嘗試查詢行事曆
    if settings.google_calendar_id:
        try:
            from googleapiclient.errors import HttpError
            cal = service.calendars().get(calendarId=settings.google_calendar_id).execute()
            result["calendar_access"] = "OK"
            result["calendar_name"] = cal.get("summary", "(未知)")
        except Exception as e:
            result["calendar_access"] = f"失敗：{e}"
    else:
        result["calendar_access"] = "跳過（GOOGLE_CALENDAR_ID 未設定）"

    return result


@app.get("/debug/env")
async def debug_env():
    """診斷關鍵環境變數是否正確設定。"""
    from app.config import get_settings
    settings = get_settings()
    qr_url = settings.payment_qr_image_url
    return {
        "payment_qr_image_url_set": bool(qr_url),
        "payment_qr_image_url_preview": (qr_url[:60] + "...") if len(qr_url) > 60 else qr_url,
        "admin_id_set": bool(settings.admin_line_user_id),
        "kv_url_set": bool(settings.kv_rest_api_url),
        "google_calendar_id_set": bool(settings.google_calendar_id),
    }
