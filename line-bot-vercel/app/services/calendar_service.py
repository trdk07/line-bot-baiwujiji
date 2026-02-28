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

# 工作室營業設定
WORK_HOURS_START = 13  # 下午 1 點
WORK_HOURS_END = 21    # 晚上 9 點
SLOT_DURATION = 60     # 每個時段 60 分鐘
CLOSED_WEEKDAYS = {0, 6}  # 0=週一, 6=週日 不營業

WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


def _get_calendar_service():
    """建立 Google Calendar API 連線。"""
    settings = get_settings()
    if not settings.google_service_account_json:
        return None
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds_info = json.loads(settings.google_service_account_json)
        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        logger.error("Calendar service init failed: %s", e)
        return None


def get_next_available_dates(days: int = 9) -> list:
    """回傳未來可預約的日期（跳過週一和週日），最多 6 個。"""
    today = datetime.now(TW_TZ).date()
    dates = []
    for i in range(1, days + 1):
        d = today + timedelta(days=i)
        if d.weekday() not in CLOSED_WEEKDAYS:
            dates.append(d.strftime("%Y-%m-%d"))
        if len(dates) >= 6:
            break
    return dates


def get_available_slots(date_str: str) -> list:
    """
    查詢指定日期的可用時段。
    回傳: ["13:00", "14:00", "15:00", ...]
    """
    service = _get_calendar_service()
    settings = get_settings()

    if not service or not settings.google_calendar_id:
        return []

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        day_start = date.replace(
            hour=WORK_HOURS_START, minute=0, second=0, tzinfo=TW_TZ
        )
        day_end = date.replace(
            hour=WORK_HOURS_END, minute=0, second=0, tzinfo=TW_TZ
        )

        # FreeBusy 查詢（會自動避開你行事曆上有事的時段）
        body = {
            "timeMin": day_start.isoformat(),
            "timeMax": day_end.isoformat(),
            "timeZone": TIMEZONE,
            "items": [{"id": settings.google_calendar_id}],
        }
        result = service.freebusy().query(body=body).execute()
        busy_times = result["calendars"][settings.google_calendar_id]["busy"]

        # 生成所有時段
        all_slots = []
        current = day_start
        while current < day_end:
            all_slots.append(current)
            current += timedelta(minutes=SLOT_DURATION)

        # 過濾已被佔用的時段
        available = []
        for slot in all_slots:
            slot_end = slot + timedelta(minutes=SLOT_DURATION)
            is_busy = any(
                slot < isoparse(b["end"]) and slot_end > isoparse(b["start"])
                for b in busy_times
            )
            if not is_busy:
                available.append(slot.strftime("%H:%M"))

        # 如果是今天，過濾已過去的時段
        now = datetime.now(TW_TZ)
        if date.date() == now.date():
            current_time = now.strftime("%H:%M")
            available = [t for t in available if t > current_time]

        return available

    except Exception as e:
        logger.error("FreeBusy query error: %s", e)
        return []


def create_event(date_str: str, time_str: str, customer_name: str) -> bool:
    """在 Google Calendar 建立預約事件。"""
    service = _get_calendar_service()
    settings = get_settings()

    if not service or not settings.google_calendar_id:
        return False

    try:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        start_dt = start_dt.replace(tzinfo=TW_TZ)
        end_dt = start_dt + timedelta(minutes=SLOT_DURATION)

        event = {
            "summary": f"【預約】{customer_name}",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
        }

        service.events().insert(
            calendarId=settings.google_calendar_id,
            body=event,
        ).execute()

        logger.info("Event created: %s %s %s", date_str, time_str, customer_name)
        return True

    except Exception as e:
        logger.error("Calendar create event error: %s", e)
        return False


def format_date_label(date_str: str) -> str:
    """格式化日期，例如 '3/2（二）'。"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAY_NAMES[d.weekday()]
    return f"{d.month}/{d.day}（{weekday}）"
