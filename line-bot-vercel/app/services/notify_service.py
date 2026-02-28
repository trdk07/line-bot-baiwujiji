"""
通知服務 — 透過 LINE Push Message 推送訊息。
"""

import logging
from linebot.v3.messaging import (
    ApiClient, MessagingApi, Configuration,
    PushMessageRequest, TextMessage,
    FlexMessage, FlexContainer,
)
from app.config import get_settings

logger = logging.getLogger(__name__)


def get_user_name(user_id: str, configuration) -> str:
    """取得用戶的 LINE 顯示名稱。"""
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            profile = line_bot_api.get_profile(user_id)
            return profile.display_name
    except Exception:
        return "未知用戶"


def notify_admin(user_id: str, user_message: str, reason: str = "客人找你"):
    """推送通知給管理員。"""
    settings = get_settings()
    if not settings.admin_line_user_id:
        logger.warning("ADMIN_LINE_USER_ID not set, skipping notification")
        return

    try:
        configuration = Configuration(access_token=settings.line_channel_access_token)
        user_name = get_user_name(user_id, configuration)
        notification = f"📢 {user_name}：{user_message}"

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=settings.admin_line_user_id,
                    messages=[TextMessage(text=notification)],
                )
            )
            logger.info("Admin notified for user: %s (%s)", user_name, user_id)
    except Exception as e:
        logger.error("Failed to notify admin: %s", e)


def push_text_to_user(target_user_id: str, text: str):
    """推送文字訊息給指定用戶（用於確認/拒絕預約時通知客人）。"""
    settings = get_settings()
    try:
        configuration = Configuration(access_token=settings.line_channel_access_token)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=target_user_id,
                    messages=[TextMessage(text=text)],
                )
            )
    except Exception as e:
        logger.error("Push to user %s failed: %s", target_user_id, e)


def push_flex_to_user(target_user_id: str, flex_dict: dict):
    """推送 Flex Message 卡片給指定用戶（用於發送匯款資訊等）。"""
    settings = get_settings()
    try:
        configuration = Configuration(access_token=settings.line_channel_access_token)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=target_user_id,
                    messages=[
                        FlexMessage(
                            alt_text=flex_dict["altText"],
                            contents=FlexContainer.from_dict(flex_dict["contents"]),
                        )
                    ],
                )
            )
    except Exception as e:
        logger.error("Push flex to user %s failed: %s", target_user_id, e)
