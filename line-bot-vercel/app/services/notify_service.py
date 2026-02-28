"""
管理員通知服務 — 透過 LINE Push Message 通知小夏老師。
"""

import logging
from linebot.v3.messaging import (
    ApiClient,
    MessagingApi,
    Configuration,
    PushMessageRequest,
    TextMessage,
)
from app.config import get_settings

logger = logging.getLogger(__name__)


def notify_admin(user_id: str, user_message: str, reason: str = "客人要求找老師"):
    """
    發送 Push Message 給管理員。
    如果 ADMIN_LINE_USER_ID 未設定，只記錄 log。
    """
    settings = get_settings()

    if not settings.admin_line_user_id:
        logger.warning("ADMIN_LINE_USER_ID not set, skipping notification")
        return

    try:
        configuration = Configuration(
            access_token=settings.line_channel_access_token,
        )

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)

            notification = (
                f"📢 {reason}\n"
                f"——————————\n"
                f"用戶 ID：{user_id}\n"
                f"用戶訊息：{user_message}\n"
                f"——————————\n"
                f"請到 LINE 官方帳號後台回覆此用戶。"
            )

            line_bot_api.push_message(
                PushMessageRequest(
                    to=settings.admin_line_user_id,
                    messages=[TextMessage(text=notification)],
                )
            )

            logger.info("Admin notified for user: %s", user_id)

    except Exception as e:
        logger.error("Failed to notify admin: %s", e)
