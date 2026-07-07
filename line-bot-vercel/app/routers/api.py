import hmac
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.config import get_settings
from app.services.calendar_service import TW_TZ, delete_event, format_date_label, update_event
from app.services.notify_service import push_text_to_user, push_flex_to_user
from app.services.slots_service import SELECTABLE_TIMES, get_open_slots, set_open_slots
from app.services.state_service import (
    kv_cmd, delete_booking, delete_done_booking, get_all_done_bookings, get_all_queue_bookings,
    remove_crm_booking, update_booking_datetime, update_done_booking_datetime, update_crm_booking_datetime, clear_intake_state,
)
from app.templates import flex_messages as fm

router = APIRouter()


class SlotsPayload(BaseModel):
    month: str
    data: dict[str, list[str]]
    token: str = ""


class ChangeBookingPayload(BaseModel):
    ref: str
    status: str
    date: str
    time: str
    token: str = ""


class DeleteBookingPayload(BaseModel):
    ref: str
    status: str
    token: str = ""
    notify: bool = True


def _month_bounds(month: str) -> tuple[str, str]:
    start = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def due_notifications(today, open_next_month: bool, tomorrow_bookings: list) -> list:
    notices = []
    if today.day == 25 and not open_next_month:
        notices.append("open_next_month")
    if today.day == 1:
        notices.append("monthly_summary")
    if tomorrow_bookings:
        notices += ["tomorrow_customer", "tomorrow_admin"]
    return notices

def _lock(name: str, date_key: str) -> bool:
    return kv_cmd("SET", f"reminder:{name}:{date_key}", "1", "NX", "EX", 172800) == "OK"

def _month_lines(month: str) -> list:
    return [f"{format_date_label(d)} {' '.join(t.replace(':00', '') for t in times)}" for d, times in sorted(get_open_slots(month).items())]


@router.get("/booking.html", response_class=HTMLResponse)
async def booking_page():
    settings = get_settings()
    html = Path(__file__).resolve().parents[1].joinpath("templates", "booking.html").read_text(encoding="utf-8")
    html = html.replace("__BOT_BASIC_ID__", json.dumps(settings.bot_basic_id))
    return HTMLResponse(html)


@router.get("/api/slots")
async def slots(month: str):
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(status_code=400, detail="invalid month")
    from app.services.calendar_service import get_busy_map

    start, end = _month_bounds(month)
    return {
        "open": get_open_slots(month),
        "taken": get_busy_map(start, end),
        "today": datetime.now(TW_TZ).date().isoformat(),
        "selectableTimes": SELECTABLE_TIMES,
    }


@router.post("/api/slots")
async def save_slots(payload: SlotsPayload):
    _assert_admin_token(payload.token)
    if not re.fullmatch(r"\d{4}-\d{2}", payload.month):
        raise HTTPException(status_code=400, detail="invalid month")
    ok, conflicts = set_open_slots(payload.month, payload.data)
    if conflicts:
        raise HTTPException(status_code=409, detail={"conflicts": conflicts})
    if not ok:
        raise HTTPException(status_code=500, detail="save failed")
    return {"ok": True}




def _assert_admin_token(token: str):
    settings = get_settings()
    if not settings.admin_page_token or not hmac.compare_digest(token, settings.admin_page_token):
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/api/bookings")
async def bookings(token: str = ""):
    _assert_admin_token(token)
    entries = get_all_queue_bookings() + get_all_done_bookings()
    return {
        "bookings": [
            {
                "ref": e["ref"],
                "userId": e["user_id"],
                "date": e["booking"].get("d", ""),
                "time": e["booking"].get("t", ""),
                "name": e["booking"].get("n", ""),
                "status": e["booking"].get("s", ""),
            }
            for e in entries
        ]
    }


@router.post("/api/bookings/change")
async def change_booking(payload: ChangeBookingPayload):
    _assert_admin_token(payload.token)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload.date):
        raise HTTPException(status_code=400, detail="invalid date")
    if not re.fullmatch(r"\d{2}:\d{2}", payload.time):
        raise HTTPException(status_code=400, detail="invalid time")

    entries = get_all_queue_bookings() + get_all_done_bookings()
    entry = next((e for e in entries if e["ref"] == payload.ref and e["booking"].get("s") == payload.status), None)
    if not entry:
        raise HTTPException(status_code=404, detail="booking not found")

    booking = entry["booking"]
    old_date, old_time = booking.get("d", ""), booking.get("t", "")
    is_done = booking.get("s") == "done"
    ok = (
        update_done_booking_datetime(payload.ref, payload.date, payload.time, booking)
        if is_done else
        update_booking_datetime(payload.ref, payload.date, payload.time, booking)
    )
    if not ok:
        raise HTTPException(status_code=500, detail="update failed")

    cal_ok, cal_error = True, ""
    if is_done and booking.get("cal_id"):
        cal_ok, cal_error = update_event(booking["cal_id"], payload.date, payload.time, booking.get("n", ""))

    crm_updated = update_crm_booking_datetime(entry["user_id"], payload.date, payload.time)
    push_ok = push_flex_to_user(
        entry["user_id"],
        fm.booking_rescheduled_card(booking.get("n", ""), format_date_label(payload.date), payload.time),
    )
    return {
        "ok": True,
        "old": {"date": old_date, "time": old_time},
        "new": {"date": payload.date, "time": payload.time},
        "calendar": {"ok": cal_ok, "error": cal_error},
        "crmPendingUpdated": crm_updated,
        "notified": push_ok,
    }


@router.post("/api/bookings/delete")
async def delete_booking_api(payload: DeleteBookingPayload):
    _assert_admin_token(payload.token)
    entries = get_all_queue_bookings() + get_all_done_bookings()
    entry = next((e for e in entries if e["ref"] == payload.ref and e["booking"].get("s") == payload.status), None)
    if not entry:
        raise HTTPException(status_code=404, detail="booking not found")

    booking = entry["booking"]
    is_done = booking.get("s") == "done"
    if is_done:
        delete_done_booking(payload.ref)
    else:
        delete_booking(payload.ref)
    clear_intake_state(entry["user_id"])

    cal_ok, cal_error = True, ""
    if is_done and booking.get("cal_id"):
        cal_ok, cal_error = delete_event(booking["cal_id"])

    crm_removed = remove_crm_booking(
        entry["user_id"],
        booking.get("d", ""),
        booking.get("t", ""),
    )
    notified = False
    if payload.notify:
        notified = push_text_to_user(
            entry["user_id"],
            f"您的預約已取消：{format_date_label(booking.get('d', ''))} {booking.get('t', '')}。\n\n"
            "如需重新預約，請輸入「我要預約」。",
        )
    return {
        "ok": True,
        "calendar": {"ok": cal_ok, "error": cal_error},
        "crmPendingRemoved": crm_removed,
        "notified": notified,
    }

@router.get("/api/cron")
async def cron(authorization: str = Header(default="")):
    settings = get_settings()
    if not settings.cron_secret or authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=403, detail="forbidden")
    today = datetime.now(TW_TZ).date()
    this_month = f"{today.year:04d}-{today.month:02d}"
    tomorrow = today + timedelta(days=1)
    next_month_day = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    next_month = f"{next_month_day.year:04d}-{next_month_day.month:02d}"
    tomorrow_bookings = [e for e in get_all_done_bookings() if e["booking"].get("d") == tomorrow.strftime("%Y-%m-%d")]
    notices = due_notifications(today, bool(get_open_slots(next_month)), tomorrow_bookings)
    admin, sent = settings.admin_line_user_id, []
    if admin and "open_next_month" in notices and _lock("open_next_month", today.isoformat()):
        base_url = settings.public_base_url.rstrip("/")
        if base_url and settings.admin_page_token:
            url = f"{base_url}/booking.html?token={settings.admin_page_token}"
            push_flex_to_user(admin, fm.admin_booking_link_card(url, f"{next_month_day.month} 月時段尚未開放"))
        else:
            ref = "\n".join(_month_lines(this_month)) or "本月尚未開放"
            push_text_to_user(admin, f"✦ {next_month_day.month} 月時段尚未開放\nPUBLIC_BASE_URL 或 ADMIN_PAGE_TOKEN 未設定，暫時無法產生設定連結。\n\n參考：{today.month} 月開放的是——\n{ref}")
        sent.append("open_next_month")
    if admin and "monthly_summary" in notices and _lock("monthly_summary", today.isoformat()):
        data = get_open_slots(this_month)
        open_days, open_count = len(data), sum(len(v) for v in data.values())
        done_count = sum(1 for e in get_all_done_bookings() if e["booking"].get("d", "").startswith(this_month))
        push_text_to_user(admin, f"✦ {today.month} 月總覽\n開放 {open_days} 天 {open_count} 時段\n已成立預約 {done_count} 筆")
        sent.append("monthly_summary")
    if "tomorrow_customer" in notices and _lock("tomorrow_customer", tomorrow.isoformat()):
        for e in tomorrow_bookings:
            push_text_to_user(e["user_id"], f"明日預約提醒：{format_date_label(e['booking']['d'])} {e['booking']['t']} ✦ 屆時見")
        sent.append("tomorrow_customer")
    if admin and "tomorrow_admin" in notices and _lock("tomorrow_admin", tomorrow.isoformat()):
        lines = [f"{b['booking']['n']}｜{format_date_label(b['booking']['d'])} {b['booking']['t']}" for b in tomorrow_bookings]
        push_text_to_user(admin, f"明日行程：{len(lines)} 筆——\n" + "\n".join(lines))
        sent.append("tomorrow_admin")
    return {"ok": True, "sent": sent}
