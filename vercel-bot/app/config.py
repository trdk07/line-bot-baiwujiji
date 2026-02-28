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

    # LINE Notify（管理員通知）
    line_notify_token: str = ""

    model_config = {
        "env_file": ".env" if os.path.exists(".env") else None,
        "env_file_encoding": "utf-8",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
