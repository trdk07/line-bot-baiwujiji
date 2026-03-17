"""
集中管理所有環境變數。
Vercel 上的環境變數在網頁後台設定，不需要 .env 檔。
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    """應用程式設定"""

    # LINE Messaging API
    line_channel_secret: str
    line_channel_access_token: str

    # 管理員 LINE User ID（用來接收通知）
    admin_line_user_id: str = ""

    # Vercel KV（Bot 開關狀態用）
    kv_rest_api_url: str = ""
    kv_rest_api_token: str = ""

    # Google Calendar（預約功能用）
    google_service_account_json: str = ""
    google_calendar_id: str = ""

    # 匯款資訊（預約確認後發送給客人）
    payment_bank_name: str = ""
    payment_bank_account: str = ""
    payment_account_name: str = ""

    model_config = {
        "env_file": ".env" if os.path.exists(".env") else None,
        "env_file_encoding": "utf-8",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
