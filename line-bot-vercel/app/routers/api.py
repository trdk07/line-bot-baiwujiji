import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from app.config import get_settings
from app.services import booking_actions
from app.services.payment_qr import QR_IMAGE_PATH, resolve_payment_qr_url, self_hosted_qr_url
from app.services.calendar_service import TW_TZ, delete_event, format_date_label, update_event
from app.services.notify_service import push_text_to_user, push_flex_to_user
from app.services.slots_service import SELECTABLE_TIMES, get_open_slots, set_open_slots
from app.services.state_service import (
    kv_cmd, delete_booking, delete_done_booking, get_all_done_bookings, get_all_queue_bookings,
    remove_crm_booking, update_booking_datetime, update_done_booking_datetime, update_crm_booking_datetime, clear_intake_state,
    get_customer_profile, customer_link_sig,
    incr_monthly_stat, get_monthly_stats, get_all_customers,
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


# ============================================================
# 逾時預約掃描（每日 cron）：先提醒、後釋放
# ============================================================
# - pending 超過 24 小時：提醒老師處理（/ok 或 /no）。鎖 48 小時後到期，
#   老師一直沒處理就每兩天再提醒一次，預約本身不會被自動取消。
# - awaiting_payment 超過 48 小時：提醒客人匯款（一次），並預告再未回報
#   將自動釋放時段。
# - awaiting_payment 超過 72 小時：自動取消預約並釋放時段，通知雙方。
#   payment_reported（已回報匯款）永不自動取消，等老師 /paid 或 /no。
PENDING_REMIND_SECS = 24 * 3600
PAY_REMIND_SECS = 48 * 3600
PAY_RELEASE_SECS = 72 * 3600


def _booking_created_ts(ref: str) -> int | None:
    """從 ref（user_id|毫秒時間戳）取出建立時間（秒）。舊格式回 None。"""
    parts = ref.split("|")
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    return int(parts[1]) // 1000


def _booking_label(booking: dict) -> str:
    order_part = f"（編號 {booking['o']}）" if booking.get("o") else ""
    return f"{format_date_label(booking.get('d', ''))} {booking.get('t', '')}{order_part}"


def sweep_stale_bookings(now_ts: int | None = None) -> dict:
    """掃描逾時預約：提醒老師／提醒客人／釋放時段。回傳各動作的筆數統計。"""
    settings = get_settings()
    now_ts = now_ts or int(time.time())
    result = {"admin_reminded": 0, "customer_reminded": 0, "released": 0}

    for entry in get_all_queue_bookings():
        booking, ref, user_id = entry["booking"], entry["ref"], entry["user_id"]
        status = booking.get("s", "")
        created = _booking_created_ts(ref)
        label = _booking_label(booking)

        if status == "pending" and created and now_ts - created > PENDING_REMIND_SECS:
            if _lock("stale_pending", ref) and settings.admin_line_user_id:
                push_text_to_user(
                    settings.admin_line_user_id,
                    f"⏳ 提醒：{booking.get('n', '')} 的預約還沒確認\n{label}\n\n"
                    f"已等待超過 24 小時，回覆 /ok 確認或 /no 婉拒。",
                )
                result["admin_reminded"] += 1
            continue

        if status == "awaiting_payment":
            base = booking.get("u") or created
            if not base:
                continue
            waited = now_ts - base
            if waited > PAY_RELEASE_SECS:
                delete_booking(ref)
                clear_intake_state(user_id)
                incr_monthly_stat("released")
                push_text_to_user(
                    user_id,
                    f"您的預約 {label} 因久未收到匯款回報，已自動取消，時段已釋放。\n\n"
                    f"如仍需諮詢，歡迎輸入「我要預約」重新選擇時間 🙏",
                )
                if settings.admin_line_user_id:
                    push_text_to_user(
                        settings.admin_line_user_id,
                        f"🕐 已自動釋放逾時未匯款的預約\n{booking.get('n', '')}｜{label}\n（已通知客人）",
                    )
                result["released"] += 1
            elif waited > PAY_REMIND_SECS and _lock("pay_remind", ref):
                push_text_to_user(
                    user_id,
                    f"提醒您：{label} 的預約仍在等待匯款。\n\n"
                    f"完成匯款後請回報「已匯款」，預約才算成立；"
                    f"若 24 小時內未收到回報，時段將自動釋放給其他客人 🙏",
                )
                result["customer_reminded"] += 1

    return result

def _month_lines(month: str) -> list:
    return [f"{format_date_label(d)} {' '.join(t.replace(':00', '') for t in times)}" for d, times in sorted(get_open_slots(month).items())]


@router.get("/booking.html", response_class=HTMLResponse)
async def booking_page():
    settings = get_settings()
    html = Path(__file__).resolve().parents[1].joinpath("templates", "booking.html").read_text(encoding="utf-8")
    html = html.replace("__BOT_BASIC_ID__", json.dumps(settings.bot_basic_id))
    return HTMLResponse(html)


_ADMIN_PAGE_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}


@router.get("/admin.html", response_class=HTMLResponse)
async def admin_page(request: Request, token: str = ""):
    """管理後台總覽頁。需帶有效 token 或 session cookie 才伺服，
    避免後台介面結構對外曝光；資料與操作端點另各自驗證。"""
    if not _is_admin_request(request, token):
        ip = _client_ip(request)
        if _auth_blocked(ip):
            return HTMLResponse("<p>嘗試次數過多，請 15 分鐘後再試。</p>", status_code=429, headers=_ADMIN_PAGE_HEADERS)
        if token:
            _record_auth_failure(ip)
        return HTMLResponse(
            "<p>此頁面僅供管理員使用。請在 LINE 輸入 /admin 取得有效連結。</p>",
            status_code=403,
            headers=_ADMIN_PAGE_HEADERS,
        )
    html = Path(__file__).resolve().parents[1].joinpath("templates", "admin.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers=_ADMIN_PAGE_HEADERS)


@router.get("/api/stats")
async def stats(request: Request, token: str = ""):
    """儀表板數據：近 6 個月彙總 + 目前進行中各狀態筆數。"""
    _assert_admin(request, token)
    now = datetime.now(TW_TZ)
    months = []
    y, m = now.year, now.month
    for _ in range(6):
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    active_counts = {"pending": 0, "awaiting_payment": 0, "payment_reported": 0}
    for e in get_all_queue_bookings():
        s = e["booking"].get("s", "")
        if s in active_counts:
            active_counts[s] += 1
    return {
        "months": get_monthly_stats(months),  # 由新到舊
        "active": active_counts,
        "doneRecent": len(get_all_done_bookings()),  # 30 天內已成立
    }


@router.get("/api/customers")
async def customers(request: Request, token: str = ""):
    """後台顧客名冊：所有累積過的顧客（名稱、次數、首次/最近日期）。"""
    _assert_admin(request, token)
    return {"customers": get_all_customers()}


@router.get("/qr-payment.png")
async def payment_qr_image():
    """伺服付款 QR Code 圖檔。

    vercel.json 把所有路徑 rewrite 到 FastAPI，repo 裡的靜態圖檔不會被
    Vercel 直接伺服，必須由 app 自己回傳，LINE 才抓得到 image/png。
    """
    if not QR_IMAGE_PATH.is_file():
        raise HTTPException(status_code=404, detail="qr image not found")
    return Response(
        content=QR_IMAGE_PATH.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


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


@router.get("/api/me")
async def me(uid: str = "", sig: str = ""):
    """回頭客辨識：預約網頁用簽章 uid 查詢顧客累積檔案。

    連結由 Bot 私訊給客人本人（含 HMAC 簽章），簽章不符或查無資料時
    一律回 returning: false，網頁就當一般訪客顯示，不報錯。
    """
    if not uid or not sig or not hmac.compare_digest(sig, customer_link_sig(uid)):
        return {"ok": True, "returning": False}
    profile = get_customer_profile(uid)
    if not profile:
        return {"ok": True, "returning": False}
    return {
        "ok": True,
        "returning": True,
        "name": profile.get("n", ""),
        "count": int(profile.get("c", 0)),
        "last": profile.get("last", ""),
    }


@router.post("/api/slots")
async def save_slots(payload: SlotsPayload, request: Request):
    _assert_admin(request, payload.token)
    if not re.fullmatch(r"\d{4}-\d{2}", payload.month):
        raise HTTPException(status_code=400, detail="invalid month")
    ok, conflicts = set_open_slots(payload.month, payload.data)
    if conflicts:
        raise HTTPException(status_code=409, detail={"conflicts": conflicts})
    if not ok:
        raise HTTPException(status_code=500, detail="save failed")
    return {"ok": True}




# ============================================================
# 管理端驗證：token（LINE 連結首次開啟）或簽章 session cookie（之後）
# ============================================================
# - cookie 是無狀態簽章值「到期時間.HMAC」，金鑰由 LINE channel secret 與
#   ADMIN_PAGE_TOKEN 衍生：換掉 ADMIN_PAGE_TOKEN 即可讓所有 cookie 立即失效。
# - 同一 IP 在 15 分鐘內驗證失敗 10 次即鎖定（KV 未設定時不鎖，僅開發環境）。

SESSION_COOKIE = "admin_session"
SESSION_TTL = 7 * 24 * 3600
AUTH_FAIL_LIMIT = 10
AUTH_FAIL_WINDOW = 900


def _session_sig(exp: int) -> str:
    settings = get_settings()
    msg = f"admin-session:{settings.admin_page_token}:{exp}"
    return hmac.new(settings.line_channel_secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def make_session_cookie() -> tuple[str, int]:
    exp = int(time.time()) + SESSION_TTL
    return f"{exp}.{_session_sig(exp)}", SESSION_TTL


def _valid_session(value: str) -> bool:
    settings = get_settings()
    if not settings.admin_page_token or not value or "." not in value:
        return False
    exp_str, sig = value.split(".", 1)
    if not exp_str.isdigit() or int(exp_str) < time.time():
        return False
    return hmac.compare_digest(sig, _session_sig(int(exp_str)))


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _auth_blocked(ip: str) -> bool:
    raw = kv_cmd("GET", f"authfail:{ip}")
    return bool(raw) and int(raw) >= AUTH_FAIL_LIMIT


def _record_auth_failure(ip: str):
    kv_cmd("INCR", f"authfail:{ip}")
    kv_cmd("EXPIRE", f"authfail:{ip}", AUTH_FAIL_WINDOW)


def _is_admin_request(request: Request, token: str = "") -> bool:
    settings = get_settings()
    if not settings.admin_page_token:
        return False
    if _valid_session(request.cookies.get(SESSION_COOKIE, "")):
        return True
    return bool(token) and hmac.compare_digest(token, settings.admin_page_token)


def _assert_admin(request: Request, token: str = ""):
    if _auth_blocked(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too many attempts")
    if _is_admin_request(request, token):
        return
    _record_auth_failure(_client_ip(request))
    raise HTTPException(status_code=403, detail="forbidden")


class LoginPayload(BaseModel):
    token: str = ""


@router.post("/api/admin/login")
async def admin_login(payload: LoginPayload, request: Request):
    """用 token 換 7 天效期的 HttpOnly session cookie，讓網址不必一直帶 token。"""
    _assert_admin(request, payload.token)
    value, ttl = make_session_cookie()
    response = JSONResponse({"ok": True})
    response.set_cookie(
        SESSION_COOKIE, value,
        max_age=ttl, httponly=True, secure=True, samesite="lax", path="/",
    )
    return response


@router.get("/api/admin/me")
async def admin_me(request: Request, token: str = ""):
    """探測端點：booking.html 用來判斷是否已有管理 session（不計失敗次數）。"""
    return {"admin": _is_admin_request(request, token)}


@router.get("/api/bookings")
async def bookings(request: Request, token: str = ""):
    _assert_admin(request, token)
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


class BookingActionPayload(BaseModel):
    ref: str
    token: str = ""


def _find_queue_entry(ref: str, statuses: set):
    return next(
        (e for e in get_all_queue_bookings() if e["ref"] == ref and e["booking"].get("s") in statuses),
        None,
    )


@router.post("/api/bookings/confirm")
async def confirm_booking_api(payload: BookingActionPayload, request: Request):
    """後台按鈕版 /ok：確認日期並發匯款資訊給客人。"""
    _assert_admin(request, payload.token)
    entry = _find_queue_entry(payload.ref, {"pending"})
    if not entry:
        raise HTTPException(status_code=404, detail="booking not found")
    result = booking_actions.confirm_booking(entry)
    if not result["ok"]:
        raise HTTPException(status_code=500, detail="update failed")
    return {"ok": True, "notified": result["notified"]}


@router.post("/api/bookings/reject")
async def reject_booking_api(payload: BookingActionPayload, request: Request):
    """後台按鈕版 /no：婉拒預約並通知客人。"""
    _assert_admin(request, payload.token)
    entry = _find_queue_entry(payload.ref, {"pending", "awaiting_payment"})
    if not entry:
        raise HTTPException(status_code=404, detail="booking not found")
    result = booking_actions.reject_booking(entry)
    return {"ok": True, "notified": result["notified"]}


@router.post("/api/bookings/paid")
async def paid_booking_api(payload: BookingActionPayload, request: Request):
    """後台按鈕版 /paid：確認收款、建行事曆、完成預約。"""
    _assert_admin(request, payload.token)
    entry = _find_queue_entry(payload.ref, {"payment_reported", "awaiting_payment"})
    if not entry:
        raise HTTPException(status_code=404, detail="booking not found")
    result = booking_actions.complete_booking(entry)
    return {
        "ok": True,
        "notified": result["notified"],
        "calendar": {"ok": result["calendarOk"], "error": result["calendarError"]},
    }


@router.post("/api/bookings/change")
async def change_booking(payload: ChangeBookingPayload, request: Request):
    _assert_admin(request, payload.token)
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
async def delete_booking_api(payload: DeleteBookingPayload, request: Request):
    _assert_admin(request, payload.token)
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

@router.get("/api/debug/qr")
async def debug_qr(request: Request, token: str = ""):
    """診斷匯款 QR Code 為何顯示不出來。需帶 admin token。

    直接抓一次 PAYMENT_QR_IMAGE_URL，回報 LINE 端會遇到的實際狀況：
    是否有設定、是否 https、能否連線、Content-Type 是不是圖片。
    """
    _assert_admin(request, token)
    settings = get_settings()
    raw = settings.payment_qr_image_url or ""
    normalized = fm.normalize_image_url(raw)
    resolved = resolve_payment_qr_url()
    result = {
        "set": bool(raw.strip()),
        "raw": raw,
        "normalized": normalized,
        "self_hosted_fallback": self_hosted_qr_url(),
        "resolved": resolved,
        "https": raw.strip().lower().startswith("https://"),
        "usable_by_line": bool(resolved),
    }
    if not resolved:
        result["note"] = (
            "PAYMENT_QR_IMAGE_URL 未設定（或非 https），且 PUBLIC_BASE_URL 未設定，"
            "無法退回 app 自帶的 /qr-payment.png。兩者擇一設定即可。"
        )
        return result

    try:
        import httpx

        r = httpx.get(resolved, timeout=10.0, follow_redirects=True)
        content_type = r.headers.get("content-type", "")
        result.update({
            "reachable": True,
            "status_code": r.status_code,
            "content_type": content_type,
            "content_length": len(r.content),
            "content_type_is_image": content_type.startswith("image/"),
        })
        if r.status_code >= 300:
            result["note"] = f"HTTP {r.status_code}：圖檔無法存取，LINE 會顯示空白。"
        elif not content_type.startswith("image/"):
            result["note"] = (
                f"回傳的是 {content_type or '未知'} 而不是圖片，"
                "多半是貼了『分享頁』網址而非圖檔直連。請改用直接指向 .png／.jpg 的網址。"
            )
        else:
            result["note"] = "看起來正常：https + 圖片 Content-Type，LINE 應可正常顯示。"
    except Exception as e:
        result.update({"reachable": False, "note": f"連線失敗：{e}"})
    return result


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
    stale = sweep_stale_bookings()
    return {"ok": True, "sent": sent, "stale": stale}
