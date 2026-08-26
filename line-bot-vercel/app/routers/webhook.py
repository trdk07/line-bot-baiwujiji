"""
LINE Webhook 路由 — 預約 + 付款確認三步機制。

訊息處理流程：
[第零層] 管理員指令（/off /on /ok /no /paid /list /clear /change /myid）
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
from urllib.parse import quote
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
)

from app.config import get_settings
from app.services import booking_actions
from app.services.keyword_router import match_keyword
from app.services.notify_service import notify_admin, notify_admin_flex, get_user_name, push_flex_to_user
from app.services.state_service import (
    get_message_context, set_bot_active,
    has_been_notified_bot_off, mark_notified_bot_off,
    has_seen_principles, set_seen_principles,
    save_booking, update_booking_status, delete_booking,
    get_queue_bookings_by_status, get_all_queue_bookings,
    get_user_booking_by_status,
    get_all_done_bookings,
    update_booking_datetime, update_done_booking_datetime,
    set_intake_pending, clear_intake_state, mark_intake_reprompted,
    set_intake_step, get_intake_step,
    save_intake_draft, get_intake_draft,
    save_intake_data,
    set_clear_confirm_pending, has_clear_confirm_pending, clear_confirm_pending,
    get_crm_queue, remove_crm_queue_item, update_crm_booking_datetime,
    get_customer_profile, customer_link_sig,
)
from app.services.calendar_service import (
    get_next_available_dates,
    get_available_slots,
    update_event,
    format_date_label,
)
from app.services.crm_service import (
    sync_booking_to_crm,
    parse_birth_date,
)
from app.templates import flex_messages as fm

logger = logging.getLogger(__name__)
router = APIRouter()

# --- 初始化 LINE SDK ---
settings = get_settings()
handler = WebhookHandler(settings.line_channel_secret)
configuration = Configuration(access_token=settings.line_channel_access_token)


INTAKE_TEMPLATE_TEXT = "1. 姓名\n2. 出生年月日時\n3. 想問的問題"
INTAKE_PLACEHOLDERS = {"姓名", "出生年月日時", "出生年月日", "想問的問題", "想了解的問題", "問題"}
INTAKE_PROMPT_TEXT = (
    "預約申請已送出 ✓\n\n"
    "小夏老師確認後會通知您，請稍候。\n\n"
    "也請先填寫諮詢資料，老師確認預約時會一併查閱。"
)
INTAKE_RETRY_TEXT = (
    "剛剛收到的是格式範例，還不是您的資料。\n\n"
    "請把「姓名／出生年月日時／想問的問題」改成您的實際內容後，再一次送出。"
)


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


def _parse_trailing_number(text: str) -> int | None:
    m = re.search(r"\s+(\d+)\s*$", text)
    return int(m.group(1)) if m else None


def _pick_booking(status: str, number: int | None, event, no_entry_msg: str | None):
    """
    從佇列中挑選指定狀態的預約。
    - 0 筆 → 若 no_entry_msg 不為 None 則回覆，回傳 (None, None, None)
    - 1 筆且沒指定編號 → 自動選
    - 多筆且沒指定編號 → 回覆列表讓管理員選
    - 指定編號 → 選第 N 筆
    回傳 (user_id, booking, ref) 或 (None, None, None)（已回覆過訊息）。
    """
    entries = get_queue_bookings_by_status(status)

    if not entries:
        if no_entry_msg is not None:
            reply_text(event, no_entry_msg)
        return None, None, None

    # 只有一筆：直接處理
    if number is None and len(entries) == 1:
        e = entries[0]
        return e["user_id"], e["booking"], e["ref"]

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
        return None, None, None

    # 指定編號
    idx = number - 1
    if 0 <= idx < len(entries):
        e = entries[idx]
        return e["user_id"], e["booking"], e["ref"]
    else:
        reply_text(event, f"編號 {number} 不存在，目前只有 {len(entries)} 筆。")
        return None, None, None


def _strip_intake_label(value: str, labels: tuple[str, ...]) -> str:
    """移除使用者填寫諮詢資料時常見的欄位名稱前綴。"""
    label_pattern = "|".join(re.escape(label) for label in labels)
    return re.sub(rf"^\s*(?:{label_pattern})\s*[:：,，、-]?\s*", "", value).strip()



def _parse_labeled_intake(text: str) -> tuple[str, str, str]:
    """解析「姓名：... 出生年月日時：... 問題：...」格式，可分行或同一行。"""
    name_labels = r"(?:姓名|名字|大名|本名|姓名名字)"
    birth_labels = r"(?:出生年月日時|出生年月日|出生時間|生日|生辰|生辰八字)"
    question_labels = r"(?:想問的問題|想了解的問題|問題|提問|詢問)"
    sep = r"\s*[:：,，、-]?\s*"
    name_m = re.search(name_labels + sep + r"(.+?)(?=" + birth_labels + sep + r"|" + question_labels + sep + r"|\Z)", text, re.DOTALL)
    birth_m = re.search(birth_labels + sep + r"(.+?)(?=" + question_labels + sep + r"|\Z)", text, re.DOTALL)
    quest_m = re.search(question_labels + sep + r"(.+)", text, re.DOTALL)
    return (
        name_m.group(1).strip() if name_m else "",
        birth_m.group(1).strip() if birth_m else "",
        quest_m.group(1).strip() if quest_m else "",
    )

def _parse_intake_text(text: str, allow_line_fallback: bool = True) -> tuple[str, str, str]:
    """解析諮詢資料文字，回傳 (姓名, 生日, 問題)。
    優先比對 1. / 1- / 1、/「1 空白」格式，找不到就按標籤或行分割。
    """
    marker = r"(?:^|\n)\s*{}(?:[.\-、．]|\s+)\s*"
    name_m = re.search(marker.format(1) + r"(.+?)(?=" + marker.format(2) + r"|\Z)", text, re.DOTALL)
    birth_m = re.search(marker.format(2) + r"(.+?)(?=" + marker.format(3) + r"|\Z)", text, re.DOTALL)
    quest_m = re.search(marker.format(3) + r"(.+)", text, re.DOTALL)

    name = name_m.group(1).strip() if name_m else ""
    birth = birth_m.group(1).strip() if birth_m else ""
    question = quest_m.group(1).strip() if quest_m else ""

    if not (name and birth):
        labeled_name, labeled_birth, labeled_question = _parse_labeled_intake(text)
        if labeled_name and labeled_birth:
            name, birth, question = labeled_name, labeled_birth, labeled_question

    if not (name and birth) and allow_line_fallback:
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if len(lines) >= 2 and parse_birth_date(lines[1]):
            name = lines[0]
            birth = lines[1]
            question = "\n".join(lines[2:]) if len(lines) >= 3 else ""
        elif len(lines) == 1:
            name = lines[0]

    name = _strip_intake_label(name, ("姓名", "名字", "大名", "本名", "姓名名字"))
    birth = _strip_intake_label(birth, ("出生年月日時", "出生年月日", "出生時間", "生日", "生辰", "生辰八字"))
    question = _strip_intake_label(question, ("想問的問題", "想了解的問題", "問題", "提問", "詢問"))

    return name, birth, question



def _parse_symbol_intake_form(text: str) -> tuple[str, str, str]:
    name_m = re.search(r"①\s*(.+?)(?=②|③|\Z)", text, re.DOTALL)
    birth_m = re.search(r"②\s*(.+?)(?=③|\Z)", text, re.DOTALL)
    quest_m = re.search(r"③\s*(.+)", text, re.DOTALL)
    return (
        name_m.group(1).strip() if name_m else "",
        birth_m.group(1).strip() if birth_m else "",
        quest_m.group(1).strip() if quest_m else "",
    )


def _finish_intake(event, user_id: str, name: str, birth_date: str, question: str, prefix_text: str = "提供了諮詢資料"):
    clear_intake_state(user_id)
    display_name = get_user_name(user_id, configuration)
    save_intake_data(user_id, name, birth_date, question)
    reply_text(event, "已收到您的諮詢資料 ✓\n\n老師確認預約時會一併查閱，謝謝您的配合 🙏")
    notify_admin_flex(
        user_id,
        fm.intake_card(display_name, name, birth_date, question),
        prefix_text=prefix_text,
    )

def _booking_url() -> str:
    base = settings.public_base_url.rstrip("/")
    return f"{base}/booking.html" if base else ""


def _customer_booking_url(user_id: str) -> str:
    """帶簽章 uid 的個人化預約連結，讓網頁能顯示「歡迎回來」。"""
    url = _booking_url()
    if not url:
        return ""
    return f"{url}?uid={quote(user_id)}&sig={customer_link_sig(user_id)}"


def _customer_status_line(user_id: str) -> str:
    """給管理員看的客人狀態：第一次預約或回頭客（含累積次數與上次日期）。"""
    profile = get_customer_profile(user_id)
    if not profile:
        return "🆕 第一次預約"
    count = int(profile.get("c", 0))
    last = profile.get("last", "")
    last_label = f"，上次 {format_date_label(last)}" if last else ""
    return f"↩️ 回頭客（已完成 {count} 次{last_label}）"


def _admin_booking_url() -> str:
    url = _booking_url()
    if not (url and settings.admin_page_token):
        return ""
    return f"{url}?token={settings.admin_page_token}"



def _is_placeholder_intake(name: str, birth_date: str, question: str) -> bool:
    values = [name.strip(), birth_date.strip(), question.strip()]
    return any(value in INTAKE_PLACEHOLDERS for value in values if value)


def _looks_like_placeholder_message(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(re.search(r"1[.\-、．]?姓名", compact) and re.search(r"2[.\-、．]?出生年月日時", compact) and re.search(r"3[.\-、．]?想問的問題", compact))


def _reply_intake_step_prompt(event, step: str, date_label: str = "", time_str: str = ""):
    if step == "name":
        prefix = "預約申請已送出 ✓\n"
        if date_label and time_str:
            prefix += f"📅 {date_label} {time_str}\n"
        reply_text(
            event,
            prefix + "\n小夏老師確認後會通知您。\n\n為了讓老師準備，請直接回覆您的姓名。",
        )
        return
    if step == "birth":
        reply_text(event, "收到姓名 ✓\n\n請直接回覆出生年月日時。\n例如：1990-01-01 08:00")
        return
    if step == "question":
        reply_text(event, "收到出生年月日時 ✓\n\n請直接回覆想問的問題。")
        return

def _intake_prefill_url() -> str:
    if not settings.bot_basic_id:
        return ""
    return f"https://line.me/R/oaMessage/{settings.bot_basic_id}/?{quote(INTAKE_TEMPLATE_TEXT)}"


def _reply_intake_prompt(event, date_label: str = "", time_str: str = "", prompt_text: str = INTAKE_PROMPT_TEXT, order_no: str = ""):
    reply_flex(
        event,
        fm.intake_prompt_card(
            prompt_text,
            INTAKE_TEMPLATE_TEXT,
            date_label=date_label,
            time_str=time_str,
            prefill_url=_intake_prefill_url(),
            order_no=order_no,
        ),
    )


def _reply_order_status(event, user_id: str):
    """客人查詢自己所有進行中與已成立（30 天內）預約的進度。"""
    entries = [
        e for e in get_all_queue_bookings() + get_all_done_bookings()
        if e["user_id"] == user_id
    ]
    if not entries:
        reply_text(
            event,
            "目前沒有查得到的預約紀錄。\n\n如需預約，請輸入「我要預約」。",
        )
        return
    reply_flex(event, fm.order_status_card([e["booking"] for e in entries]))

def _reply_booking_entry_or_fallback(event):
    user_id = event.source.user_id
    url = _booking_url()
    if url:
        profile = get_customer_profile(user_id)
        welcome_lines = []
        if profile:
            name = profile.get("n", "")
            count = int(profile.get("c", 0))
            last = profile.get("last", "")
            welcome_lines = [f"✦ 歡迎回來{'，' + name if name else ''}"]
            detail = f"這是您第 {count + 1} 次預約"
            if last:
                detail += f"・上次是 {format_date_label(last)}"
            welcome_lines.append(detail)
        reply_flex(event, fm.booking_entry_card(_customer_booking_url(user_id), welcome_lines=welcome_lines))
        return
    dates = get_next_available_dates()
    if dates:
        reply_flex(event, fm.date_picker_card(dates))
    else:
        reply_text(event, "本月時段尚未開放，請稍候。")


# ============================================================
# 管理員指令（需 is_admin 通過才會被呼叫，見 ADMIN_COMMANDS 對照表）
# ============================================================
def _cmd_bot_off(event, user_id, text):
    set_bot_active(False)
    reply_text(event, "🔴 Bot 已關閉，小夏老師親自接管。")


def _cmd_bot_on(event, user_id, text):
    set_bot_active(True)
    reply_text(event, "🟢 Bot 已開啟，助理恢復上班。")


def _cmd_booking_admin(event, user_id, text):
    url = _admin_booking_url()
    if not url:
        reply_text(event, "尚未設定 PUBLIC_BASE_URL 或 ADMIN_PAGE_TOKEN，暫時無法產生編輯連結。")
        return
    reply_flex(event, fm.admin_booking_link_card(url, "設定可預約時段"))


def _cmd_admin_dashboard(event, user_id, text):
    """發送管理後台總覽頁連結（進行中預約、月度統計）。"""
    base = settings.public_base_url.rstrip("/")
    if not (base and settings.admin_page_token):
        reply_text(event, "尚未設定 PUBLIC_BASE_URL 或 ADMIN_PAGE_TOKEN，暫時無法產生後台連結。")
        return
    url = f"{base}/admin.html?token={settings.admin_page_token}"
    reply_text(event, f"✦ 管理後台\n{url}\n\n此連結含管理 token，請勿轉傳。")


def _cmd_booking_ok(event, user_id, text):
    """確認日期可以 → 自動發匯款資訊給客人。"""
    num = _parse_booking_number(text)
    ctx_user, booking, ref = _pick_booking(
        "pending", num, event,
        "目前沒有待確認日期的預約。",
    )
    if not ctx_user:
        return

    date_label = format_date_label(booking["d"])

    result = booking_actions.confirm_booking({"booking": booking, "ref": ref, "user_id": ctx_user})
    if not result["ok"]:
        # KV 寫入失敗：立即告知管理員，不繼續後續流程
        reply_text(
            event,
            f"⚠️ 系統錯誤：{booking['n']} 的預約狀態更新失敗（KV 寫入異常）。\n\n"
            f"請稍後再試一次 /ok，或直接手動通知客人匯款資訊。"
        )
        return

    push_status = (
        "匯款資訊已發送給客人，等待匯款回報。"
        if result["notified"]
        else "⚠️ 推送給客人失敗，請手動聯繫客人告知匯款資訊。"
    )
    reply_text(
        event,
        f"✅ 已確認 {booking['n']} 的日期\n"
        f"{date_label} {booking['t']}\n\n"
        f"{push_status}"
    )


def _cmd_booking_no(event, user_id, text):
    """婉拒預約（支援 pending 與 awaiting_payment 狀態）。"""
    num = _parse_booking_number(text)
    # 先找 pending，找不到再找 awaiting_payment
    ctx_user, booking, ref = _pick_booking("pending", num, event, None)
    if not ctx_user:
        ctx_user, booking, ref = _pick_booking(
            "awaiting_payment", num, event,
            "目前沒有待處理的預約。",
        )
    if not ctx_user:
        return

    result = booking_actions.reject_booking({"booking": booking, "ref": ref, "user_id": ctx_user})
    push_status = "" if result["notified"] else "\n⚠️ 推送給客人失敗，請手動聯繫客人告知。"
    reply_text(event, f"❌ 已婉拒 {booking['n']} 的預約{push_status}")


def _cmd_booking_paid(event, user_id, text):
    """
    確認收到款項 → 建立日曆事件 → 完成預約。
    優先處理 payment_reported（客人已主動回報），
    fallback 到 awaiting_payment（客人未回報但管理員已確認收款）。
    """
    num = _parse_booking_number(text)
    # 先找 payment_reported（正常流程）
    ctx_user, booking, ref = _pick_booking("payment_reported", num, event, None)
    if not ctx_user:
        # Fallback：找 awaiting_payment（KV 寫入失敗或客人未回報的容錯）
        ctx_user, booking, ref = _pick_booking(
            "awaiting_payment", num, event,
            "目前沒有待確認收款的預約。\n（客人需先回報「已匯款」，或款項尚未確認）",
        )
    if not ctx_user:
        return

    date_label = format_date_label(booking["d"])

    result = booking_actions.complete_booking({"booking": booking, "ref": ref, "user_id": ctx_user})

    if result["calendarOk"]:
        cal_status = "行事曆已建立 📅"
    else:
        cal_status = f"⚠️ 行事曆建立失敗\n原因：{result['calendarError']}\n請手動新增"
    push_status = "" if result["notified"] else "\n⚠️ 推送確認卡片給客人失敗，請手動聯繫客人。"
    reply_text(
        event,
        f"✅ 已完成 {booking['n']} 的預約\n"
        f"{date_label} {booking['t']}\n"
        f"{cal_status}"
        f"{push_status}"
    )


def _cmd_booking_list(event, user_id, text):
    """顯示所有狀態的預約總覽。"""
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
        order_part = f"｜{b['o']}" if b.get("o") else ""
        lines.append(f"  {i}. {b['n']}｜{date_label} {b['t']}｜{status}{order_part}")
    reply_text(event, "\n".join(lines))


def _cmd_booking_clear(event, user_id, text):
    """一次清除所有預約（需二次確認，避免誤觸）。"""
    all_bookings = get_all_queue_bookings()
    if not all_bookings:
        reply_text(event, "📋 目前沒有任何預約需要清除。")
        return

    count = len(all_bookings)
    confirmed = bool(re.search(r"yes\s*$", text, re.IGNORECASE))

    if not confirmed:
        set_clear_confirm_pending()
        reply_text(
            event,
            f"⚠️ 即將清除全部 {count} 筆預約，此動作無法復原。\n\n"
            f"確認請在 60 秒內輸入 /clear yes",
        )
        return

    if not has_clear_confirm_pending():
        reply_text(event, "確認已逾時，請重新輸入 /clear。")
        return

    clear_confirm_pending()
    for e in all_bookings:
        delete_booking(e["ref"])
        clear_intake_state(e["user_id"])
    reply_text(event, f"🗑️ 已清除全部 {count} 筆預約。")


def _cmd_booking_change(event, user_id, text):
    """改期（付款前後皆可）。"""
    m = re.search(
        r"/change\s+(?:(\d+)\s+)?(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})",
        text,
    )
    if not m:
        reply_text(
            event,
            "格式錯誤，請用：\n"
            "/change YYYY-MM-DD HH:MM\n"
            "或指定編號：/change 1 YYYY-MM-DD HH:MM",
        )
        return

    num_str, new_date, new_time = m.group(1), m.group(2), m.group(3)
    num = int(num_str) if num_str else None

    all_active = get_all_queue_bookings()
    all_done = get_all_done_bookings()
    all_entries = all_active + all_done

    if not all_entries:
        reply_text(event, "目前沒有任何預約可以改期。")
        return

    STATUS_ICON = {
        "pending": "⏳", "awaiting_payment": "💳",
        "payment_reported": "💰", "done": "✅",
    }

    if num is None and len(all_entries) == 1:
        entry = all_entries[0]
    elif num is None:
        lines = [f"目前有 {len(all_entries)} 筆預約，請加編號：\n"]
        for i, e in enumerate(all_entries, 1):
            b = e["booking"]
            icon = STATUS_ICON.get(b["s"], "")
            lines.append(f"  {i}. {b['n']}｜{format_date_label(b['d'])} {b['t']} {icon}")
        lines.append(f"\n例如：/change 1 {new_date} {new_time}")
        reply_text(event, "\n".join(lines))
        return
    else:
        idx = num - 1
        if 0 <= idx < len(all_entries):
            entry = all_entries[idx]
        else:
            reply_text(event, f"編號 {num} 不存在，目前只有 {len(all_entries)} 筆。")
            return

    booking = entry["booking"]
    ref = entry["ref"]
    ctx_user = entry["user_id"]
    is_done = booking.get("s") == "done"

    old_date_label = format_date_label(booking["d"])
    old_time = booking["t"]
    new_date_label = format_date_label(new_date)

    if is_done:
        ok = update_done_booking_datetime(ref, new_date, new_time, booking)
    else:
        ok = update_booking_datetime(ref, new_date, new_time, booking)

    if not ok:
        reply_text(event, "⚠️ 系統錯誤：預約時間更新失敗，請稍後再試。")
        return

    cal_status = ""
    if is_done and booking.get("cal_id"):
        cal_ok, cal_error = update_event(booking["cal_id"], new_date, new_time, booking["n"])
        cal_status = "\n行事曆已更新 📅" if cal_ok else f"\n⚠️ 行事曆更新失敗：{cal_error}"

    crm_updated = update_crm_booking_datetime(ctx_user, new_date, new_time)
    crm_status = "" if not crm_updated else f"\nCRM 待確認資料已更新 {crm_updated} 筆"

    push_ok = push_flex_to_user(ctx_user, fm.booking_rescheduled_card(booking["n"], new_date_label, new_time))
    push_status = "" if push_ok else "\n⚠️ 推送改期通知給客人失敗，請手動聯繫客人。"

    reply_text(
        event,
        f"✅ 已改期 {booking['n']}\n"
        f"原：{old_date_label} {old_time}\n"
        f"新：{new_date_label} {new_time}"
        f"{cal_status}"
        f"{crm_status}"
        f"{push_status}",
    )


def _pick_crm_item(event, number: int | None):
    queue = get_crm_queue()
    if not queue:
        reply_text(event, "目前沒有待處理的 CRM 資料。")
        return None
    if number is None and len(queue) == 1:
        return queue[0]
    if number is None:
        lines = [f"目前有 {len(queue)} 筆待寫入 CRM：\n"]
        for item in queue:
            p = item["payload"]
            lines.append(f"  {item['index']}. {p.get('n', '')}｜{p.get('d', '')} {p.get('t', '')}")
        lines.append("\n請回覆 /crm ok 1 或 /crm skip 1")
        reply_text(event, "\n".join(lines))
        return None
    for item in queue:
        if item["index"] == number:
            return item
    reply_text(event, f"編號 {number} 不存在，目前只有 {len(queue)} 筆。")
    return None


def _cmd_crm(event, user_id, text):
    if re.fullmatch(r"/crm\s*$", text):
        _pick_crm_item(event, None)
        return
    if re.search(r"/crm\s+ok", text):
        item = _pick_crm_item(event, _parse_trailing_number(text))
        if not item:
            return
        ok, msg = sync_booking_to_crm(item["payload"])
        if ok:
            remove_crm_queue_item(item["raw"])
            reply_text(event, f"已寫入 ✦ {item['payload'].get('n', '')}（{msg}）")
            url = _admin_booking_url()
            if url:
                push_flex_to_user(user_id, fm.admin_booking_link_card(url, "設定可預約時段"))
        else:
            reply_text(event, f"寫入失敗：{msg}\n資料已保留，可稍後重試。")
        return
    if re.search(r"/crm\s+skip", text):
        item = _pick_crm_item(event, _parse_trailing_number(text))
        if item:
            remove_crm_queue_item(item["raw"])
            reply_text(event, f"已略過 ✦ {item['payload'].get('n', '')}")
            url = _admin_booking_url()
            if url:
                push_flex_to_user(user_id, fm.admin_booking_link_card(url, "設定可預約時段"))
        return
    reply_text(event, "格式：/crm、/crm ok [編號]、/crm skip [編號]")


ADMIN_COMMANDS = {
    "bot_off": _cmd_bot_off,
    "bot_on": _cmd_bot_on,
    "booking_ok": _cmd_booking_ok,
    "booking_no": _cmd_booking_no,
    "booking_paid": _cmd_booking_paid,
    "booking_list": _cmd_booking_list,
    "booking_clear": _cmd_booking_clear,
    "booking_change": _cmd_booking_change,
    "crm": _cmd_crm,
    "booking_admin": _cmd_booking_admin,
    "admin_dashboard": _cmd_admin_dashboard,
}


# ============================================================
# 意圖 → 回應 對照表（簡單的一對一回應）
# ============================================================
INTENT_HANDLERS = {
    # --- 主要動作 ---
    "services": lambda event, text: reply_flex(event, fm.service_menu()),
    "schedule": lambda event, text: _reply_booking_entry_or_fallback(event),

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

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event: MessageEvent):
    """所有文字訊息的主路由。"""
    if event.delivery_context.is_redelivery:
        logger.info("Skip redelivered webhook event: %s", event.webhook_event_id)
        return

    user_text = event.message.text.strip()
    user_id = event.source.user_id

    logger.info("User [%s]: %s", user_id, user_text)

    # === 第零層：管理員指令（不受 Bot 開關影響）===
    intent = match_keyword(user_text)

    if intent == "get_my_id":
        admin_status = "✅ 這支帳號目前是管理員" if is_admin(user_id) else "⚠️ 這支帳號不是目前設定的管理員"
        configured = "已設定" if settings.admin_line_user_id else "尚未設定"
        reply_text(
            event,
            f"你的 LINE User ID：\n{user_id}\n\n"
            f"{admin_status}\n"
            f"ADMIN_LINE_USER_ID：{configured}",
        )
        return

    if intent in ADMIN_COMMANDS:
        if not is_admin(user_id):
            reply_text(event, "只有管理員可以使用這個指令。")
            return
        ADMIN_COMMANDS[intent](event, user_id, user_text)
        return

    # 一次 pipeline 取代兩次獨立 KV 查詢（每則訊息都會用到）
    bot_active, intake_pending = get_message_context(user_id)

    # === Bot 開關檢查 ===
    if not bot_active:
        if not is_admin(user_id):
            if not has_been_notified_bot_off(user_id):
                mark_notified_bot_off(user_id)
                reply_text(event, "小夏老師目前在線上，請稍候老師回覆 🙏")
            return

    # === 諮詢資料填寫攔截（優先於關鍵字比對）===
    # order_status 也放行：客人剛預約完最常想查的就是進度，不能被攔截吃掉。
    if not is_admin(user_id) and intake_pending and intent not in {"human", "payment_reported", "order_status"}:
        if intent in {"intake_help"}:
            _reply_intake_prompt(event)
            return

        if intent == "intake_form":
            name, birth_date, question = _parse_symbol_intake_form(user_text)
            _finish_intake(event, user_id, name, birth_date, question, prefix_text="補填了諮詢資料")
            return

        if _looks_like_placeholder_message(user_text):
            reply_text(event, INTAKE_RETRY_TEXT)
            return

        step = get_intake_step(user_id)
        name, birth_date, question = _parse_intake_text(user_text, allow_line_fallback=not bool(step))
        if _is_placeholder_intake(name, birth_date, question):
            reply_text(event, INTAKE_RETRY_TEXT)
            return
        if name and birth_date:
            _finish_intake(event, user_id, name, birth_date, question)
            return

        if step:
            if step == "name":
                save_intake_draft(user_id, n=user_text)
                set_intake_step(user_id, "birth")
                _reply_intake_step_prompt(event, "birth")
                return
            if step == "birth":
                save_intake_draft(user_id, b=user_text)
                set_intake_step(user_id, "question")
                _reply_intake_step_prompt(event, "question")
                return
            if step == "question":
                draft = get_intake_draft(user_id)
                _finish_intake(event, user_id, draft.get("n", ""), draft.get("b", ""), user_text)
                return

        if intent is not None:
            if mark_intake_reprompted(user_id):
                _reply_intake_prompt(event)
            return

        save_intake_draft(user_id, n=user_text)
        set_intake_step(user_id, "birth")
        _reply_intake_step_prompt(event, "birth")
        return

    # === 第一層：關鍵字比對（0 Token）===
    if intent:

        if intent == "intake_help":
            _reply_intake_prompt(event)
            return

        # 進度查詢：列出該客人所有預約的目前狀態
        if intent == "order_status":
            _reply_order_status(event, user_id)
            return

        # 找小夏老師
        if intent == "human":
            reply_text(event, "好的，已經通知小夏老師了，老師會盡快回覆你，請稍候。🙏")
            notify_admin(user_id, user_text, reason="客人要求找小夏老師")
            return

        # ----------------------------------------------------------
        # 諮詢資料後備：①②③ 格式（intake_pending 已消耗後仍可補填）
        # ----------------------------------------------------------
        if intent == "intake_form":
            name, birth_date, question = _parse_symbol_intake_form(user_text)
            _finish_intake(event, user_id, name, birth_date, question, prefix_text="補填了諮詢資料")
            return

        # ----------------------------------------------------------
        # 客人回報：已匯款
        # ----------------------------------------------------------
        if intent == "payment_reported":
            entry = get_user_booking_by_status(user_id, "awaiting_payment")
            if entry:
                ref, booking = entry["ref"], entry["booking"]
                # 更新狀態（傳入已有的 booking 避免重複 GET）
                ok = update_booking_status(ref, "payment_reported", booking)
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
            # 第一次：顯示原則說明（只出現一次）
            if not has_seen_principles(user_id):
                set_seen_principles(user_id)
                reply_flex(event, fm.principles_card())
                return
            # 已看過原則：直接進日期選擇
            _reply_booking_entry_or_fallback(event)
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
                if time_str not in get_available_slots(date_str):
                    reply_text(event, "這個時段目前無法預約，請輸入「我要預約」重新選擇。")
                    return

                # 儲存預約（狀態：pending，等管理員確認日期），取得對外訂單編號
                order_no = save_booking(user_id, date_str, time_str, user_name)

                # 標記等待填寫諮詢資料（24 小時有效），先以模板卡片引導；逐步問答作為 fallback。
                clear_intake_state(user_id)
                set_intake_pending(user_id)

                # 回覆客人：模板卡片 + deep link 預填格式
                _reply_intake_prompt(event, date_label, time_str, order_no=order_no)

                # 通知管理員
                order_line = f"編號 {order_no}\n" if order_no else ""
                notify_admin(
                    user_id,
                    f"📅 預約申請\n"
                    f"{date_label} {time_str}\n"
                    f"{order_line}"
                    f"{_customer_status_line(user_id)}\n\n"
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
