"""
LINE Webhook 路由 — Step 3: Google Calendar 預約整合。

訊息處理流程：
[第零層] 管理員指令（/off /on /myid）
[      ] Bot 開關檢查 — 關閉時只回靜態訊息
[第一層] 關鍵字比對 → 固定回應（0 Token）
  ├── 預約流程：原則說明（首次）→ 日期選擇 → 時段選擇 → 建立預約
  ├── 報到登記
  └── 其他關鍵字
[第二層] AI 助理 → Gemini（花 Token，但已過濾 80% 的問題）
"""

import re
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
from app.services.notify_service import notify_admin, get_user_name
from app.services.state_service import (
    is_bot_active, set_bot_active,
    has_seen_principles, set_seen_principles,
)
from app.services.calendar_service import (
    get_next_available_dates,
    get_available_slots,
    create_event,
    format_date_label,
)
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


def is_admin(user_id: str) -> bool:
    """檢查是否為管理員。"""
    return bool(settings.admin_line_user_id and user_id == settings.admin_line_user_id)


# ============================================================
# 意圖 → 回應 對照表（簡單的一對一回應）
# ============================================================
INTENT_HANDLERS = {
    # --- 主要動作 ---
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

    # --- 報到登記 ---
    "checkin_yes": lambda event, text: reply_text(event, "登記完成 ✓"),
    "checkin_late": lambda event, text: reply_text(event, "登記完成，已備註會晚到 ✓"),
    "checkin_no": lambda event, text: reply_text(event, "好的，已登記 ✓"),
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

    # === 第零層：管理員指令（不受 Bot 開關影響）===
    intent = match_keyword(user_text)

    if intent == "bot_off":
        if is_admin(user_id):
            set_bot_active(False)
            reply_text(event, "🔴 Bot 已關閉，小夏老師親自接管。")
        else:
            reply_text(event, "只有管理員可以使用這個指令。")
        return

    if intent == "bot_on":
        if is_admin(user_id):
            set_bot_active(True)
            reply_text(event, "🟢 Bot 已開啟，助理恢復上班。")
        else:
            reply_text(event, "只有管理員可以使用這個指令。")
        return

    if intent == "get_my_id":
        reply_text(event, f"你的 LINE User ID：\n{user_id}")
        return

    # === Bot 開關檢查 ===
    if not is_bot_active():
        if not is_admin(user_id):
            reply_text(event, "小夏老師目前在線上，請稍候老師回覆 🙏")
            return

    # === 第一層：關鍵字比對（0 Token）===
    if intent:

        # 找小夏老師
        if intent == "human":
            reply_text(event, "好的，已經通知小夏老師了，老師會盡快回覆你，請稍候。🙏")
            notify_admin(user_id, user_text, reason="客人要求找小夏老師")
            return

        # --- 預約流程 ---

        # 入口：「我要預約」
        if intent == "booking":
            # 第一次：顯示原則說明（只出現一次）
            if not has_seen_principles(user_id):
                set_seen_principles(user_id)
                reply_flex(event, fm.principles_card())
                return
            # 已看過原則：直接進日期選擇
            if settings.google_service_account_json and settings.google_calendar_id:
                dates = get_next_available_dates()
                reply_flex(event, fm.date_picker_card(dates))
            else:
                reply_flex(event, fm.booking_card())
            return

        # Step 2：客人選了日期 → 查空檔 → 顯示時段
        if intent == "booking_date":
            m = re.search(r"(\d{4}-\d{2}-\d{2})", user_text)
            if m:
                date_str = m.group(1)
                date_label = format_date_label(date_str)
                slots = get_available_slots(date_str)
                if slots:
                    reply_flex(event, fm.time_picker_card(date_str, slots))
                else:
                    reply_text(
                        event,
                        f"😅 {date_label} 已經約滿了。\n\n請輸入「我要預約」重新選擇其他日期。"
                    )
            return

        # Step 3：客人選了時段 → 建立預約 + 通知老師
        if intent == "booking_confirm":
            m = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", user_text)
            if m:
                date_str = m.group(1)
                time_str = m.group(2)
                date_label = format_date_label(date_str)
                user_name = get_user_name(user_id, configuration)

                # 建立 Google Calendar 事件
                create_event(date_str, time_str, user_name)

                # 回覆客人
                reply_text(
                    event,
                    f"預約完成 ✓\n\n"
                    f"📅 {date_label} {time_str}\n\n"
                    f"已通知小夏老師，老師確認後會回覆您。\n\n"
                    f"方便的話請先提供：\n"
                    f"① 您的姓名\n"
                    f"② 出生年月日（國曆）時間（有最好）\n"
                    f"③ 想了解的問題"
                )

                # 通知管理員
                notify_admin(
                    user_id,
                    f"📅 預約 {date_label} {time_str}",
                    reason="新預約",
                )
            return

        # 一般意圖：查表回應
        handler_func = INTENT_HANDLERS.get(intent)
        if handler_func:
            handler_func(event, user_text)
            return

    # === 第二層：AI 助理（花 Token）===
    ai_reply = ask_ai(user_text)
    reply_text(event, ai_reply)
