"""
預約操作核心邏輯 — LINE 管理員指令（/ok /no /paid）與管理後台按鈕共用。

這裡只做「業務動作＋推播通知客人」，不處理回覆訊息的文案：
webhook 指令拿回傳結果組 LINE 回覆，API 端點拿回傳結果組 JSON。
"""

import logging

from app.config import get_settings
from app.services.calendar_service import create_event, format_date_label
from app.services.crm_service import (
    NOTION_PREVIEW_TIMEOUT,
    find_customer_by_line_id,
)
from app.services.notify_service import notify_admin_flex, push_flex_to_user, push_text_to_user
from app.services.payment_qr import resolve_payment_qr_url
from app.services.state_service import (
    clear_intake_data, clear_intake_state,
    delete_booking, enqueue_crm,
    get_intake_data, incr_monthly_stat,
    record_customer_visit, save_done_booking,
    update_booking_status,
)
from app.templates import flex_messages as fm

logger = logging.getLogger(__name__)


def confirm_booking(entry: dict) -> dict:
    """確認日期（pending → awaiting_payment）並推送匯款資訊給客人。

    回傳 {"ok": 狀態更新成功與否, "notified": 匯款卡片推送成功與否}。
    """
    booking, ref, user_id = entry["booking"], entry["ref"], entry["user_id"]
    if not update_booking_status(ref, "awaiting_payment", booking):
        return {"ok": False, "notified": False}
    notified = push_flex_to_user(
        user_id,
        fm.payment_info_card(
            format_date_label(booking["d"]),
            booking["t"],
            resolve_payment_qr_url(),
        ),
    )
    return {"ok": True, "notified": notified}


def reject_booking(entry: dict, notify: bool = True) -> dict:
    """婉拒預約：通知客人（可選）、刪除預約、清除諮詢資料流程狀態。"""
    booking, ref, user_id = entry["booking"], entry["ref"], entry["user_id"]
    notified = False
    if notify:
        date_label = format_date_label(booking["d"])
        notified = push_text_to_user(
            user_id,
            f"很抱歉，{date_label} {booking['t']} 這個時段老師無法安排。\n\n"
            f"請輸入「我要預約」重新選擇其他時間 🙏",
        )
    delete_booking(ref)
    clear_intake_state(user_id)
    return {"ok": True, "notified": notified}


def complete_booking(entry: dict) -> dict:
    """確認收款：建立行事曆事件、發預約成立卡片、存 done 區、累積顧客檔案
    與月度統計、排入 CRM 待確認佇列（有設 Notion 時）。

    回傳 {"ok", "notified", "calendarOk", "calendarError"}。
    """
    settings = get_settings()
    booking, ref, user_id = entry["booking"], entry["ref"], entry["user_id"]
    date_label = format_date_label(booking["d"])

    cal_ok, cal_error, cal_event_id = create_event(booking["d"], booking["t"], booking["n"])

    intake_name, intake_birth, intake_question = get_intake_data(user_id)
    line_display_name = booking["n"]
    crm_customer_name = intake_name or line_display_name
    clear_intake_data(user_id)
    clear_intake_state(user_id)

    notified = push_flex_to_user(
        user_id,
        fm.booking_confirmed_card(
            line_display_name, date_label, booking["t"],
            birth_date=intake_birth, question=intake_question,
            order_no=booking.get("o", ""),
        ),
    )

    save_done_booking(ref, booking, cal_event_id)
    delete_booking(ref)
    record_customer_visit(user_id, line_display_name, booking["d"])
    incr_monthly_stat("done")

    if settings.notion_api_key:
        payload = {
            "u": user_id,
            "n": crm_customer_name,
            "b": intake_birth,
            "q": intake_question,
            "d": booking["d"],
            "t": booking["t"],
        }
        if enqueue_crm(payload):
            existing = find_customer_by_line_id(user_id, timeout=NOTION_PREVIEW_TIMEOUT)
            if existing.failed:
                customer_label = "（無法判定）"
            else:
                customer_label = "老客戶" if existing.found else "新客戶"
            notify_admin_flex(user_id, fm.crm_preview_card(payload, customer_label), prefix_text="CRM 資料待確認")

    return {"ok": True, "notified": notified, "calendarOk": cal_ok, "calendarError": cal_error}
