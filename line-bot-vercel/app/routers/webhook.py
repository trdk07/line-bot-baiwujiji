"""
LINE Webhook 路由 — 預約 + 付款確認三步機制。

訊息處理流程：
[第零層] 管理員指令（/off /on /ok /no /paid /myid）
[      ] Bot 開關檢查
[第一層] 關鍵字比對 → 固定回應（0 Token）
  ├── 預約流程：原則說明（首次）→ 日期 → 時段 → 等待確認
  ├── 管理員確認日期：/ok → 發匯款資訊給客人
  ├── 管理員拒絕：/no → 通知客人
  ├── 客人回報匯款：已匯款 → 通知管理員
  ├── 管理員確認收款：/paid → 建立日曆事件 → 通知客人
  └── 其他關鍵字
[無匹配] 靜默不回應
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
from app.services.notify_service import notify_admin, get_user_name, push_text_to_user, push_flex_to_user
from app.services.state_service import (
    is_bot_active, set_bot_active,
    has_been_notified_bot_off, mark_notified_bot_off,
    has_seen_principles, set_seen_principles,
    save_booking, get_booking, update_booking_status, delete_booking,
    get_queue_bookings_by_status, get_all_queue_bookings,
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


def _parse_booking_number(text: str) -> int | None:
    """從指令文字中解析編號，例如 '/ok 2' → 2，'/ok' → None。"""
    m = re.search(r"/(?:ok|no|paid)\s+(\d+)", text)
    return int(m.group(1)) if m else None


def _pick_booking(status: str, number: int | None, event, no_entry_msg: str | None):
    """
    從佇列中挑選指定狀態的預約。
    - 0 筆 → 若 no_entry_msg 不為 None 則回覆，回傳 (None, None)
    - 1 筆且沒指定編號 → 自動選
    - 多筆且沒指定編號 → 回覆列表讓管理員選
    - 指定編號 → 選第 N 筆
    回傳 (user_id, booking) 或 (None, None)（已回覆過訊息）。
    """
    entries = get_queue_bookings_by_status(status)

    if not entries:
        if no_entry_msg is not None:
            reply_text(event, no_entry_msg)
        return None, None

    # 只有一筆：直接處理
    if number is None and len(entries) == 1:
        return entries[0]["user_id"], entries[0]["booking"]

    # 多筆但沒指定編號：顯示列表
    if number is None:
        status_label = {
            "pending": "待確認日期",
            "awaiting_payment": "待匯款",
            "payment_reported": "已回報匯款",
        }.get(status, status)
        lines = [f"目前有 {len(entries)} 筆{status_label}的預約：\n"]
        for i, e in enumerate(entries, 1):
            b = e["booking"]
            date_label = format_date_label(b["d"])
            lines.append(f"  {i}. {b['n']}｜{date_label} {b['t']}")
        cmd = "/ok" if status == "pending" else "/paid" if status == "payment_reported" else "/no"
        lines.append(f"\n請回覆 {cmd} 加編號，例如 {cmd} 1")
        reply_text(event, "\n".join(lines))
        return None, None

    # 指定編號
    idx = number - 1
    if 0 <= idx < len(entries):
        return entries[idx]["user_id"], entries[idx]["booking"]
    else:
        reply_text(event, f"編號 {number} 不存在，目前只有 {len(entries)} 筆。")
        return None, None


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

    # ----------------------------------------------------------
    # 管理員 /ok：確認日期可以 → 自動發匯款資訊給客人
    # ----------------------------------------------------------
    if intent == "booking_ok":
        if is_admin(user_id):
            num = _parse_booking_number(user_text)
            ctx_user, booking = _pick_booking(
                "pending", num, event,
                "目前沒有待確認日期的預約。",
            )
            if not ctx_user:
                return

            date_label = format_date_label(booking["d"])

            # 更新狀態 → 等待匯款（傳入已有的 booking 避免重複 GET）
            ok = update_booking_status(ctx_user, "awaiting_payment", booking)
            if not ok:
                # KV 寫入失敗：立即告知管理員，不繼續後續流程
                reply_text(
                    event,
                    f"⚠️ 系統錯誤：{booking['n']} 的預約狀態更新失敗（KV 寫入異常）。\n\n"
                    f"請稍後再試一次 /ok，或直接手動通知客人匯款資訊。"
                )
                return

            # 推送匯款資訊卡片給客人
            push_flex_to_user(
                ctx_user,
                fm.payment_info_card(
                    date_label,
                    booking["t"],
                    settings.payment_bank_name,
                    settings.payment_bank_account,
                    settings.payment_account_name,
                ),
            )

            reply_text(
                event,
                f"✅ 已確認 {booking['n']} 的日期\n"
                f"{date_label} {booking['t']}\n\n"
                f"匯款資訊已發送給客人，等待匯款回報。"
            )
        else:
            reply_text(event, "只有管理員可以使用這個指令。")
        return

    # ----------------------------------------------------------
    # 管理員 /no：婉拒預約（支援 pending 與 awaiting_payment 狀態）
    # ----------------------------------------------------------
    if intent == "booking_no":
        if is_admin(user_id):
            num = _parse_booking_number(user_text)
            # 先找 pending，找不到再找 awaiting_payment
            ctx_user, booking = _pick_booking("pending", num, event, None)
            if not ctx_user:
                ctx_user, booking = _pick_booking(
                    "awaiting_payment", num, event,
                    "目前沒有待處理的預約。",
                )
            if not ctx_user:
                return

            date_label = format_date_label(booking["d"])

            # 通知客人
            push_text_to_user(
                ctx_user,
                f"很抱歉，{date_label} {booking['t']} 這個時段老師無法安排。\n\n"
                f"請輸入「我要預約」重新選擇其他時間 🙏"
            )

            reply_text(event, f"❌ 已婉拒 {booking['n']} 的預約")
            delete_booking(ctx_user)
        else:
            reply_text(event, "只有管理員可以使用這個指令。")
        return

    # ----------------------------------------------------------
    # 管理員 /paid：確認收到款項 → 建立日曆事件 → 完成預約
    # 優先處理 payment_reported（客人已主動回報），
    # fallback 到 awaiting_payment（客人未回報但管理員已確認收款）。
    # ----------------------------------------------------------
    if intent == "booking_paid":
        if is_admin(user_id):
            num = _parse_booking_number(user_text)
            # 先找 payment_reported（正常流程）
            ctx_user, booking = _pick_booking("payment_reported", num, event, None)
            if not ctx_user:
                # Fallback：找 awaiting_payment（KV 寫入失敗或客人未回報的容錯）
                ctx_user, booking = _pick_booking(
                    "awaiting_payment", num, event,
                    "目前沒有待確認收款的預約。\n（客人需先回報「已匯款」，或款項尚未確認）",
                )
            if not ctx_user:
                return

            date_label = format_date_label(booking["d"])

            # 建立 Google Calendar 事件
            create_event(booking["d"], booking["t"], booking["n"])

            # 通知客人：預約完成
            push_text_to_user(
                ctx_user,
                f"您的預約已完成確認 🎉\n\n"
                f"📅 {date_label} {booking['t']}\n\n"
                f"期待為您服務 🙏"
            )

            reply_text(
                event,
                f"✅ 已完成 {booking['n']} 的預約\n"
                f"{date_label} {booking['t']}\n"
                f"行事曆已建立 📅"
            )
            delete_booking(ctx_user)
        else:
            reply_text(event, "只有管理員可以使用這個指令。")
        return

    # ----------------------------------------------------------
    # 管理員 /list：顯示所有狀態的預約總覽
    # ----------------------------------------------------------
    if intent == "booking_list":
        if is_admin(user_id):
            all_bookings = get_all_queue_bookings()
            if not all_bookings:
                reply_text(event, "📋 目前沒有任何進行中的預約。")
                return

            STATUS_LABEL = {
                "pending": "⏳待確認",
                "awaiting_payment": "💳待匯款",
                "payment_reported": "💰已回報",
            }
            lines = [f"📋 目前共 {len(all_bookings)} 筆預約：\n"]
            for i, e in enumerate(all_bookings, 1):
                b = e["booking"]
                date_label = format_date_label(b["d"])
                status = STATUS_LABEL.get(b["s"], b["s"])
                lines.append(f"  {i}. {b['n']}｜{date_label} {b['t']}｜{status}")
            reply_text(event, "\n".join(lines))
        else:
            reply_text(event, "只有管理員可以使用這個指令。")
        return

    # === Bot 開關檢查 ===
    if not is_bot_active():
        if not is_admin(user_id):
            if not has_been_notified_bot_off(user_id):
                mark_notified_bot_off(user_id)
                reply_text(event, "小夏老師目前在線上，請稍候老師回覆 🙏")
            return

    # === 第一層：關鍵字比對（0 Token）===
    if intent:

        # 找小夏老師
        if intent == "human":
            reply_text(event, "好的，已經通知小夏老師了，老師會盡快回覆你，請稍候。🙏")
            notify_admin(user_id, user_text, reason="客人要求找小夏老師")
            return

        # ----------------------------------------------------------
        # 客人回報：已匯款
        # ----------------------------------------------------------
        if intent == "payment_reported":
            booking = get_booking(user_id)
            if booking and booking.get("s") == "awaiting_payment":
                # 更新狀態（傳入已有的 booking 避免重複 GET）
                ok = update_booking_status(user_id, "payment_reported", booking)
                if not ok:
                    # KV 寫入失敗：請客人重試，不發假通知給管理員
                    reply_text(
                        event,
                        "系統暫時忙碌，請稍後再按一次「已匯款」按鈕 🙏"
                    )
                    return

                date_label = format_date_label(booking["d"])

                reply_text(
                    event,
                    "已收到您的匯款回報 ✓\n\n"
                    "確認收款後會通知您，請稍候。"
                )

                # 通知管理員
                notify_admin(
                    user_id,
                    f"💰 客人回報已匯款\n"
                    f"{date_label} {booking['t']}\n\n"
                    f"確認收款後回覆 /paid",
                    reason="匯款回報",
                )
            else:
                reply_text(
                    event,
                    "目前沒有待匯款的預約紀錄。\n如需預約，請輸入「我要預約」。"
                )
            return

        # --- 預約流程 ---

        # 入口：「我要預約」
        if intent == "booking":
            # 檢查是否已有進行中的預約
            existing = get_booking(user_id)
            if existing:
                status_msg = {
                    "pending": "您的預約正在等待老師確認日期",
                    "awaiting_payment": "您的預約已確認，請完成匯款後按「已匯款」",
                    "payment_reported": "您的匯款正在確認中",
                }.get(existing["s"], "您已有一筆預約在處理中")
                date_label = format_date_label(existing["d"])
                reply_text(
                    event,
                    f"您目前已有一筆預約：\n\n"
                    f"📅 {date_label} {existing['t']}\n"
                    f"狀態：{status_msg}\n\n"
                    f"如需取消或更改，請輸入「找小夏老師」聯繫老師。"
                )
                return

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

        # Step 3：客人選了時段 → 暫存預約 → 通知老師
        if intent == "booking_confirm":
            m = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", user_text)
            if m:
                date_str = m.group(1)
                time_str = m.group(2)
                date_label = format_date_label(date_str)
                user_name = get_user_name(user_id, configuration)

                # 儲存預約（狀態：pending，等管理員確認日期）
                save_booking(user_id, date_str, time_str, user_name)

                # 回覆客人
                reply_text(
                    event,
                    f"預約申請已送出 ✓\n\n"
                    f"📅 {date_label} {time_str}\n\n"
                    f"小夏老師確認後會通知您，請稍候。\n\n"
                    f"方便的話請先提供：\n"
                    f"① 您的大名\n"
                    f"② 出生年月日（國曆）\n"
                    f"③ 想了解的問題"
                )

                # 通知管理員
                notify_admin(
                    user_id,
                    f"📅 預約申請\n"
                    f"{date_label} {time_str}\n\n"
                    f"回覆 /ok 確認日期（會發匯款資訊）\n"
                    f"回覆 /no 婉拒",
                    reason="新預約申請",
                )
            return

        # 一般意圖：查表回應
        handler_func = INTENT_HANDLERS.get(intent)
        if handler_func:
            handler_func(event, user_text)
            return

    # === 無匹配：靜默不回應 ===
    return
