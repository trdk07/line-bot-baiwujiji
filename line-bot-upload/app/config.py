"""
集中管理所有環境變數，透過 pydantic-settings 自動從 .env 載入並驗證。
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """應用程式設定 — 所有欄位都必須在 .env 或環境變數中提供。"""

    # LINE Messaging API
    line_channel_secret: str
    line_channel_access_token: str

    # LINE Notify（管理員通知）
    line_notify_token: str = ""

    # Server
    port: int = 8080  # Cloud Run 預設用 8080
    env: str = "production"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


@lru_cache()
def get_settings() -> Settings:
    """單例模式取得設定，整個應用程式生命週期只讀取一次 .env。"""
    return Settings()
