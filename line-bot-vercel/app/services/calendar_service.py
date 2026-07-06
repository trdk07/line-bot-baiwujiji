"""
Google Calendar 整合 — 查詢可用時段 + 建立預約事件。
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from dateutil.parser import isoparse

from app.config import get_settings

logger = logging.getLogger(__name__)

TIMEZONE = "Asia/Taipei"
TW_TZ = timezone(timedelta(hours=8))

SLOT_DURATION = 60  # 每個時段 60 分鐘

WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


def _get_calendar_service():
    """建立 Google Calendar API 連線。回傳 (service, error_msg)。"""
    settings = get_settings()
    if not settings.google_service_account_json:
        return None, "GOOGLE_SERVICE_ACCOUNT_JSON 未設定"
    if not settings.google_calendar_id:
        return None, "GOOGLE_CALENDAR_ID 未設定"
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds_info = json.loads(settings.google_service_account_json)
        # Vercel 環境變數可能將 private_key 裡的 \n 存成 \\n，這裡自動修正
        if "private_key" in creds_info:
            creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        return build("calendar", "v3", credentials=creds), None
    except json.JSONDecodeError as e:
        msg = f"JSON 格式錯誤：{e}"
        logger.error("Calendar service init failed: %s", msg)
        return None, msg
    except Exception as e:
        msg = f"認證建立失敗：{e}"
        logger.error("Calendar service init failed: %s", msg)
        return None, msg


def get_next_available_dates(days: int = 14) -> list:
    """回傳未來已手動開放的日期，最多 6 個。"""
    from app.services.slots_service import get_open_dates

    return get_open_dates(days)


def _filter_taken_and_past(slots: list, taken: set) -> list:
    """
    套用軟鎖定（進行中預約佔用）與已過去時段的過濾。
    slots: [(datetime, "HH:MM"), ...]。
    用完整 datetime（而非時間字串）比較「是否已過去」，
    避免跨午夜時段（例如隔天 00:00）被字串比較誤判為已過去。
    """
    now = datetime.now(TW_TZ)
    return [s for dt, s in slots if s not in taken and dt > now]


def get_available_slots(date_str: str) -> list:
    """
    查詢指定日期的可用時段。
    軟鎖定：pending / awaiting_payment / payment_reported 狀態的進行中預約
    也視為佔用，避免管理員確認收款（建立日曆事件）前該時段被重複預約。
    回傳: ["14:00", "15:00", "23:00", ...]
    """
    from app.services.state_service import get_taken_slots
    from app.services.slots_service import get_open_slots, slot_datetime

    open_times = get_open_slots(date_str[:7]).get(date_str, [])
    if not open_times:
        return []
    all_slots = [(slot_datetime(date_str, t), t) for t in open_times]

    taken = get_taken_slots(date_str)
    service, _ = _get_calendar_service()
    settings = get_settings()

    # 如果沒有 Google Calendar，直接回傳所有時段（扣除軟鎖定）
    if not service or not settings.google_calendar_id:
        return _filter_taken_and_past(all_slots, taken)

    try:
        # 查詢範圍：當天最早到隔天凌晨（涵蓋跨午夜時段）
        query_start = min(dt for dt, _ in all_slots)
        query_end = max(dt for dt, _ in all_slots) + timedelta(minutes=SLOT_DURATION)

        body = {
            "timeMin": query_start.isoformat(),
            "timeMax": query_end.isoformat(),
            "timeZone": TIMEZONE,
            "items": [{"id": settings.google_calendar_id}],
        }
        result = service.freebusy().query(body=body).execute()
        busy_times = result["calendars"][settings.google_calendar_id]["busy"]

        # 過濾已被佔用的時段
        available = []
        for slot, label in all_slots:
            slot_end = slot + timedelta(minutes=SLOT_DURATION)
            is_busy = any(
                slot < isoparse(b["end"]) and slot_end > isoparse(b["start"])
                for b in busy_times
            )
            if not is_busy:
                available.append((slot, label))

        return _filter_taken_and_past(available, taken)

    except Exception as e:
        logger.error("FreeBusy query error: %s", e, exc_info=True)
        # API 失敗時降級：回傳所有時段（仍扣除軟鎖定），避免誤顯示「已約滿」
        return _filter_taken_and_past(all_slots, taken)


def get_busy_map(start_date: str, end_date: str) -> dict:
    """回傳日期區間內已被行事曆或進行中預約佔用的時段。"""
    from app.services.state_service import get_taken_slots
    from app.services.slots_service import get_open_slots, slot_datetime

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    months = sorted({(start + timedelta(days=i)).strftime("%Y-%m") for i in range((end - start).days + 1)})
    open_by_date = {}
    for month in months:
        open_by_date.update(get_open_slots(month))

    busy = {d: set(get_taken_slots(d)) for d in open_by_date if start_date <= d <= end_date}
    service, _ = _get_calendar_service()
    settings = get_settings()
    if not service or not settings.google_calendar_id:
        return {d: sorted(times) for d, times in busy.items()}

    try:
        query_start = datetime.combine(start, datetime.min.time(), tzinfo=TW_TZ)
        query_end = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=TW_TZ)
        body = {
            "timeMin": query_start.isoformat(),
            "timeMax": query_end.isoformat(),
            "timeZone": TIMEZONE,
            "items": [{"id": settings.google_calendar_id}],
        }
        result = service.freebusy().query(body=body).execute()
        busy_times = result["calendars"][settings.google_calendar_id]["busy"]
        for date_str, times in open_by_date.items():
            if not (start_date <= date_str <= end_date):
                continue
            for time_str in times:
                slot = slot_datetime(date_str, time_str)
                slot_end = slot + timedelta(minutes=SLOT_DURATION)
                if any(slot < isoparse(b["end"]) and slot_end > isoparse(b["start"]) for b in busy_times):
                    busy.setdefault(date_str, set()).add(time_str)
    except Exception as e:
        logger.error("FreeBusy range query error: %s", e, exc_info=True)
    return {d: sorted(times) for d, times in busy.items()}


def create_event(date_str: str, time_str: str, customer_name: str) -> tuple[bool, str, str]:
    """在 Google Calendar 建立預約事件。回傳 (成功與否, 錯誤訊息, 事件ID)。"""
    service, init_error = _get_calendar_service()
    settings = get_settings()

    if not service:
        return False, init_error or "無法建立 Calendar 服務", ""

    try:
        from app.services.slots_service import slot_datetime

        start_dt = slot_datetime(date_str, time_str)

        end_dt = start_dt + timedelta(minutes=SLOT_DURATION)

        event = {
            "summary": f"【預約】{customer_name}",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
        }

        created = service.events().insert(
            calendarId=settings.google_calendar_id,
            body=event,
        ).execute()

        logger.info("Event created: %s %s %s", date_str, time_str, customer_name)
        return True, "", created.get("id", "")

    except Exception as e:
        msg = str(e)
        logger.error("Calendar create event error: %s", msg, exc_info=True)
        return False, msg, ""


def update_event(event_id: str, date_str: str, time_str: str, customer_name: str) -> tuple[bool, str]:
    """更新 Google Calendar 事件的時間。回傳 (成功與否, 錯誤訊息)。"""
    service, init_error = _get_calendar_service()
    settings = get_settings()

    if not service:
        return False, init_error or "無法建立 Calendar 服務"

    try:
        from app.services.slots_service import slot_datetime

        start_dt = slot_datetime(date_str, time_str)

        end_dt = start_dt + timedelta(minutes=SLOT_DURATION)

        patch_body = {
            "summary": f"【預約】{customer_name}",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
        }
        service.events().patch(
            calendarId=settings.google_calendar_id,
            eventId=event_id,
            body=patch_body,
        ).execute()

        logger.info("Event updated: %s %s %s", date_str, time_str, customer_name)
        return True, ""

    except Exception as e:
        msg = str(e)
        logger.error("Calendar update event error: %s", msg, exc_info=True)
        return False, msg


def format_date_label(date_str: str) -> str:
    """格式化日期，例如 '3/2（二）'。"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAY_NAMES[d.weekday()]
    return f"{d.month}/{d.day}（{weekday}）"
