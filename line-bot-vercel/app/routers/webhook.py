"""
LINE Webhook 路由 — Step 2: 關鍵字路由 + Flex Message + AI 助理。

訊息處理流程：
[第一層] 關鍵字比對 → 固定回應（0 Token）
[第二層] AI 助理 → Gemini（花 Token，但已過濾 80% 的問題）
"""

import logging
from fastapi import APIRouter, Request, HTTPException

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    MessagingApi,
    Configuration,
    ReplyMessageRequest,
    TextMessage,
    FlexMessage,
    FlexContainer,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent,
)

from app.config import get_settings
from app.services.keyword_router import match_keyword
from app.services.ai_service import ask_ai
from app.services.notify_service import notify_admin
from app.templates import flex_messages as fm

logger = logging.getLogger(__name__)
router = APIRouter()

# --- 初始化 LINE SDK ---
settings = get_settings()
handler = WebhookHandler(settings.line_channel_secret)
configuration = Configuration(access_token=settings.line_channel_access_token)


# ============================================================
# Webhook 端點
# ============================================================
@router.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    return "OK"


# ============================================================
# 回覆輔助函式
# ============================================================
def reply_text(event, text: str):
    """回覆純文字訊息。"""
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=text)],
            )
        )


def reply_flex(event, flex_dict: dict):
    """回覆 Flex Message 卡片。"""
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    FlexMessage(
                        alt_text=flex_dict["altText"],
                        contents=FlexContainer.from_dict(flex_dict["contents"]),
                    )
                ],
            )
        )


# ============================================================
# 意圖 → 回應 對照表
# ============================================================
INTENT_HANDLERS = {
    # --- 主要動作 ---
    "booking": lambda event, text: reply_flex(event, fm.booking_card()),
    "services": lambda event, text: reply_flex(event, fm.service_menu()),

    # --- 價格防禦 ---
    "pricing": lambda event, text: reply_text(
        event,
        "費用會依每個人的狀況和需求不同，老師會在諮詢時跟您說明。\n\n"
        "想了解更多，可以輸入「服務項目」看看我們提供的服務，"
        "或直接輸入「我要預約」開始預約諮詢。"
    ),

    # --- 諮詢說明 ---
    "what_is_consultation": lambda event, text: reply_flex(event, fm.consultation_card()),
    "category_consultation": lambda event, text: reply_flex(event, fm.consultation_card()),

    # --- 服務分類 ---
    "category_fortune": lambda event, text: reply_flex(event, fm.fortune_card()),
    "category_wealth": lambda event, text: reply_flex(event, fm.wealth_card()),
    "category_love": lambda event, text: reply_flex(event, fm.love_card()),
    "category_fengshui": lambda event, text: reply_flex(event, fm.fengshui_card()),
    "category_custom": lambda event, text: reply_flex(event, fm.custom_card()),
}


# ============================================================
# 事件 Handlers
# ============================================================
@handler.add(FollowEvent)
def handle_follow(event: FollowEvent):
    """用戶加好友時觸發。"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        welcome = (
            "歡迎來到「百無禁忌」。\n\n"
            "我是工作室的助理，有任何問題都可以問我。\n\n"
            "👉 輸入「服務項目」查看我們的服務\n"
            "👉 輸入「我要預約」直接預約諮詢\n"
            "👉 輸入「找小夏老師」由老師親自回覆"
        )

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=welcome)],
            )
        )


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event: MessageEvent):
    """所有文字訊息的主路由。"""
    user_text = event.message.text.strip()
    user_id = event.source.user_id

    logger.info("User [%s]: %s", user_id, user_text)

    # === 第一層：關鍵字比對（0 Token）===
    intent = match_keyword(user_text)

    if intent:
        # 特殊處理：找小夏老師
        if intent == "human":
            reply_text(event, "好的，已經通知小夏老師了，老師會盡快回覆你，請稍候。🙏")
            notify_admin(user_id, user_text, reason="客人要求找小夏老師")
            return

        # 特殊處理：取得自己的 User ID（管理員設定用）
        if intent == "get_my_id":
            reply_text(event, f"你的 LINE User ID：\n{user_id}")
            return

        # 一般意圖：查表回應
        handler_func = INTENT_HANDLERS.get(intent)
        if handler_func:
            handler_func(event, user_text)
            return

    # === 第二層：AI 助理（花 Token）===
    ai_reply = ask_ai(user_text)
    reply_text(event, ai_reply)
