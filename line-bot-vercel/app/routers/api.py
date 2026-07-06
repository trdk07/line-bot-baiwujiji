from datetime import datetime, timedelta
from fastapi import APIRouter, Header, HTTPException
from app.config import get_settings
from app.services.calendar_service import TW_TZ, format_date_label
from app.services.notify_service import push_text_to_user
from app.services.slots_service import get_open_slots
from app.services.state_service import kv_cmd, get_all_done_bookings

router = APIRouter()

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
        ref = "\n".join(_month_lines(this_month)) or "本月尚未開放"
        m = next_month_day.month
        push_text_to_user(admin, f"✦ {m} 月時段尚未開放\n回覆 /open 開放時段，每行一天，例如：\n\n/open\n{m}/3 15 16 20\n{m}/5 15 16\n\n參考：{today.month} 月開放的是——\n{ref}")
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
