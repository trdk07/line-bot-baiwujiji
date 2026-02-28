"""
LINE Webhook 路由。

職責：
1. 接收 LINE Platform 發來的 HTTP POST
2. 用 channel_secret 驗證 X-Line-Signature（防偽造）
3. 解析事件並分發給對應 handler
"""

import logging
from fastapi import APIRouter, Request, HTTPException

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent,
)

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# --- 初始化 LINE SDK ---
settings = get_settings()

handler = WebhookHandler(settings.line_channel_secret)

configuration = Configuration(
    access_token=settings.line_channel_access_token,
)


# ============================================================
# Webhook 端點
# ============================================================
@router.post("/callback")
async def callback(request: Request):
    """
    LINE Platform 會把所有事件 POST 到這裡。
    第一件事就是驗證簽名，不合法直接 400。
    """
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")

    logger.info("Received webhook - body length: %d", len(body))

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("Invalid signature rejected")
        raise HTTPException(status_code=400, detail="Invalid signature")

    return "OK"


# ============================================================
# 事件 Handlers
# ============================================================
@handler.add(FollowEvent)
def handle_follow(event: FollowEvent):
    """用戶加好友 / 解封鎖時觸發。"""
    with AsyncApiClient(configuration) as api_client:
        line_bot_api = AsyncMessagingApi(api_client)

        welcome_text = (
            "歡迎來到「百無禁忌」。\n\n"
            "我是你的玄學諮詢助理，有任何命理、風水、擇日的問題，都可以直接問我。\n\n"
            "想預約深度諮詢？輸入「我要預約」即可開始。"
        )

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=welcome_text)],
            )
        )


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event: MessageEvent):
    """所有文字訊息的進入點。目前為 Echo 測試模式。"""
    user_text = event.message.text
    user_id = event.source.user_id

    logger.info("User [%s]: %s", user_id, user_text)

    # --- Echo Mode（確認管線暢通後會換成 AI）---
    reply = f"[Echo] 收到：{user_text}\n\n（AI 客服尚未上線，這是管線測試）"

    with AsyncApiClient(configuration) as api_client:
        line_bot_api = AsyncMessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)],
            )
        )
